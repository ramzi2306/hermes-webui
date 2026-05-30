/**
 * Email Panel — AI-powered iMessage-style inbox for Hermes WebUI
 * Handles IMAP/SMTP accounts, conversation view, and AI drafting
 */

(function () {
  "use strict";

  // ─── State ───────────────────────────────────────────────────────────────
  let emailState = {
    accounts: [],
    activeAccount: null,
    emails: [],
    activeEmail: null,
    loading: false,
    drafts: {}, // emailId -> draft text
  };

  // ─── API Helpers ─────────────────────────────────────────────────────────
  async function apiGet(path) {
    const res = await fetch(path, { credentials: "same-origin" });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  async function apiPost(path, body) {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const res = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  // ─── Render Helpers ──────────────────────────────────────────────────────
  function esc(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/);
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
  }

  function timeAgo(timestamp) {
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  // ─── Main Panel Render ───────────────────────────────────────────────────
  function renderEmailPanel() {
    const panel = document.getElementById("email-panel");
    if (!panel) return;

    panel.innerHTML = `
      <div class="ep-container">
        <div class="ep-sidebar">
          <div class="ep-sidebar-header">
            <span class="ep-title">✉ Mail</span>
            <button class="ep-btn ep-btn-icon" id="ep-compose-btn" title="Compose">✏</button>
            <button class="ep-btn ep-btn-icon" id="ep-settings-btn" title="Settings">⚙</button>
          </div>

          <div class="ep-account-bar" id="ep-account-bar">
            ${emailState.accounts.map(a => `
              <div class="ep-account-chip ${emailState.activeAccount?.email === a.email ? "active" : ""}"
                   data-email="${esc(a.email)}" title="${esc(a.email)}">
                ${initials(a.name || a.email)}
              </div>
            `).join("")}
            ${emailState.accounts.length === 0 ? `
              <div class="ep-no-accounts">
                <button class="ep-btn ep-btn-primary" id="ep-add-account-btn">+ Add Email Account</button>
              </div>` : ""}
          </div>

          <div class="ep-email-list" id="ep-email-list">
            ${renderEmailList()}
          </div>
        </div>

        <div class="ep-main" id="ep-main">
          ${emailState.activeEmail ? renderEmailDetail(emailState.activeEmail) : renderEmptyState()}
        </div>
      </div>
    `;

    attachEmailPanelEvents();
  }

  function renderEmailList() {
    if (emailState.loading) {
      return `<div class="ep-loading"><div class="ep-spinner"></div> Loading...</div>`;
    }
    if (emailState.emails.length === 0) {
      return `<div class="ep-empty-list">No emails yet.<br>Select an account to load.</div>`;
    }

    return emailState.emails.map(e => `
      <div class="ep-email-item ${emailState.activeEmail?.id === e.id ? "active" : ""}"
           data-id="${esc(e.id)}">
        <div class="ep-avatar">${initials(e.from_name)}</div>
        <div class="ep-email-meta">
          <div class="ep-email-from">${esc(e.from_name || e.from_email)}</div>
          <div class="ep-email-subject">${esc(e.subject)}</div>
          <div class="ep-email-preview">${esc(e.preview)}</div>
        </div>
        <div class="ep-email-time">${timeAgo(e.timestamp)}</div>
      </div>
    `).join("");
  }

  function renderEmptyState() {
    return `
      <div class="ep-empty-state">
        <div class="ep-empty-icon">✉</div>
        <div class="ep-empty-text">Select an email to read</div>
      </div>
    `;
  }

  function renderEmailDetail(em) {
    const draft = emailState.drafts[em.id] || "";
    return `
      <div class="ep-detail">
        <div class="ep-detail-header">
          <div class="ep-detail-subject">${esc(em.subject)}</div>
          <div class="ep-detail-from">
            <span class="ep-detail-avatar">${initials(em.from_name)}</span>
            <div>
              <div class="ep-detail-from-name">${esc(em.from_name)}</div>
              <div class="ep-detail-from-email">&lt;${esc(em.from_email)}&gt;</div>
            </div>
            <div class="ep-detail-date">${esc(em.date)}</div>
          </div>
        </div>

        <div class="ep-conversation">
          <div class="ep-bubble ep-bubble-received">
            <div class="ep-bubble-body">${esc(em.body).replace(/\n/g, "<br>")}</div>
          </div>
          ${draft ? `
          <div class="ep-bubble ep-bubble-sent ep-bubble-draft">
            <div class="ep-bubble-label">Draft</div>
            <div class="ep-bubble-body" id="ep-draft-body">${esc(draft).replace(/\n/g, "<br>")}</div>
          </div>` : ""}
        </div>

        <div class="ep-reply-area">
          <div class="ep-ai-bar">
            <input class="ep-ai-input" id="ep-ai-input"
                   placeholder="Ask Hermes to draft a reply... (e.g. 'Decline politely')" />
            <button class="ep-btn ep-btn-ai" id="ep-draft-btn">✦ Draft</button>
          </div>
          <textarea class="ep-reply-textarea" id="ep-reply-textarea"
                    placeholder="Reply...">${draft}</textarea>
          <div class="ep-reply-actions">
            <button class="ep-btn" id="ep-discard-btn">Discard</button>
            <button class="ep-btn ep-btn-primary" id="ep-send-btn">Send ➤</button>
          </div>
        </div>
      </div>
    `;
  }

  // ─── Settings Modal ───────────────────────────────────────────────────────
  function renderSettingsModal() {
    const accounts = emailState.accounts;
    return `
      <div class="ep-modal-overlay" id="ep-modal-overlay">
        <div class="ep-modal">
          <div class="ep-modal-header">
            <span>Email Accounts</span>
            <button class="ep-btn ep-btn-icon" id="ep-modal-close">✕</button>
          </div>
          <div class="ep-modal-body">
            ${accounts.map((a, i) => `
              <div class="ep-account-row">
                <div class="ep-account-info">
                  <strong>${esc(a.name || a.email)}</strong><br>
                  <small>${esc(a.email)}</small>
                </div>
                <button class="ep-btn ep-btn-danger ep-btn-sm" data-remove="${i}">Remove</button>
              </div>
            `).join("")}

            <div class="ep-add-account-form" id="ep-add-form">
              <h4>Add Account</h4>
              <input class="ep-input" id="ep-f-name" placeholder="Display Name" />
              <input class="ep-input" id="ep-f-email" placeholder="Email address" type="email" />
              <input class="ep-input" id="ep-f-password" placeholder="Password / App Password" type="password" />
              <div class="ep-form-row">
                <input class="ep-input" id="ep-f-imap-host" placeholder="IMAP Host (e.g. imap.gmail.com)" />
                <input class="ep-input ep-input-sm" id="ep-f-imap-port" placeholder="Port" value="993" type="number" />
              </div>
              <div class="ep-form-row">
                <input class="ep-input" id="ep-f-smtp-host" placeholder="SMTP Host (e.g. smtp.gmail.com)" />
                <input class="ep-input ep-input-sm" id="ep-f-smtp-port" placeholder="Port" value="587" type="number" />
              </div>
              <button class="ep-btn ep-btn-primary" id="ep-save-account-btn">Save Account</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // ─── Compose Modal ────────────────────────────────────────────────────────
  function renderComposeModal() {
    return `
      <div class="ep-modal-overlay" id="ep-modal-overlay">
        <div class="ep-modal ep-modal-compose">
          <div class="ep-modal-header">
            <span>New Email</span>
            <button class="ep-btn ep-btn-icon" id="ep-modal-close">✕</button>
          </div>
          <div class="ep-modal-body">
            <input class="ep-input" id="ep-c-to" placeholder="To" />
            <input class="ep-input" id="ep-c-subject" placeholder="Subject" />
            <textarea class="ep-compose-textarea" id="ep-c-body" placeholder="Message..."></textarea>
            <div class="ep-reply-actions">
              <button class="ep-btn" id="ep-modal-close">Cancel</button>
              <button class="ep-btn ep-btn-primary" id="ep-compose-send-btn">Send ➤</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // ─── Event Handlers ───────────────────────────────────────────────────────
  function attachEmailPanelEvents() {
    // Account chips
    document.querySelectorAll(".ep-account-chip").forEach(chip => {
      chip.addEventListener("click", async () => {
        const email = chip.dataset.email;
        emailState.activeAccount = emailState.accounts.find(a => a.email === email);
        emailState.activeEmail = null;
        await loadEmails();
      });
    });

    // Email list items
    document.getElementById("ep-email-list")?.addEventListener("click", e => {
      const item = e.target.closest(".ep-email-item");
      if (!item) return;
      const id = item.dataset.id;
      emailState.activeEmail = emailState.emails.find(em => em.id === id);
      renderEmailPanel();
    });

    // Settings button
    document.getElementById("ep-settings-btn")?.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", renderSettingsModal());
      attachModalEvents();
    });

    // Compose button
    document.getElementById("ep-compose-btn")?.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", renderComposeModal());
      attachComposeEvents();
    });

    // Add account shortcut
    document.getElementById("ep-add-account-btn")?.addEventListener("click", () => {
      document.body.insertAdjacentHTML("beforeend", renderSettingsModal());
      attachModalEvents();
    });

    // Draft button
    document.getElementById("ep-draft-btn")?.addEventListener("click", async () => {
      if (!emailState.activeEmail) return;
      const instruction = document.getElementById("ep-ai-input")?.value || "";
      const btn = document.getElementById("ep-draft-btn");
      btn.textContent = "Drafting...";
      btn.disabled = true;
      try {
        const res = await apiPost("/api/email/draft", {
          email: emailState.activeEmail,
          instruction,
        });
        emailState.drafts[emailState.activeEmail.id] = res.draft;
        const textarea = document.getElementById("ep-reply-textarea");
        if (textarea) textarea.value = res.draft;
        renderEmailPanel();
      } catch (err) {
        alert("Draft error: " + err.message);
      } finally {
        btn.textContent = "✦ Draft";
        btn.disabled = false;
      }
    });

    // Send button
    document.getElementById("ep-send-btn")?.addEventListener("click", async () => {
      if (!emailState.activeEmail || !emailState.activeAccount) return;
      const body = document.getElementById("ep-reply-textarea")?.value;
      if (!body?.trim()) return alert("Reply is empty");
      const btn = document.getElementById("ep-send-btn");
      btn.textContent = "Sending...";
      btn.disabled = true;
      try {
        await apiPost("/api/email/send", {
          account_email: emailState.activeAccount.email,
          to: emailState.activeEmail.from_email,
          subject: "Re: " + emailState.activeEmail.subject,
          body,
          reply_to_message_id: emailState.activeEmail.message_id,
        });
        delete emailState.drafts[emailState.activeEmail.id];
        alert("Sent!");
        renderEmailPanel();
      } catch (err) {
        alert("Send error: " + err.message);
      } finally {
        btn.textContent = "Send ➤";
        btn.disabled = false;
      }
    });

    // Discard button
    document.getElementById("ep-discard-btn")?.addEventListener("click", () => {
      if (emailState.activeEmail) {
        delete emailState.drafts[emailState.activeEmail.id];
        document.getElementById("ep-reply-textarea").value = "";
        renderEmailPanel();
      }
    });

    // Sync reply textarea with draft state
    document.getElementById("ep-reply-textarea")?.addEventListener("input", e => {
      if (emailState.activeEmail) {
        emailState.drafts[emailState.activeEmail.id] = e.target.value;
      }
    });
  }

  function attachModalEvents() {
    document.getElementById("ep-modal-close")?.addEventListener("click", () => {
      document.getElementById("ep-modal-overlay")?.remove();
    });
    document.getElementById("ep-modal-overlay")?.addEventListener("click", e => {
      if (e.target.id === "ep-modal-overlay") e.target.remove();
    });

    // Remove account buttons
    document.querySelectorAll("[data-remove]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const idx = parseInt(btn.dataset.remove);
        emailState.accounts.splice(idx, 1);
        await apiPost("/api/email/accounts", { accounts: emailState.accounts });
        document.getElementById("ep-modal-overlay")?.remove();
        renderEmailPanel();
      });
    });

    // Save account
    document.getElementById("ep-save-account-btn")?.addEventListener("click", async () => {
      const account = {
        name: document.getElementById("ep-f-name")?.value.trim(),
        email: document.getElementById("ep-f-email")?.value.trim(),
        password: document.getElementById("ep-f-password")?.value,
        imap_host: document.getElementById("ep-f-imap-host")?.value.trim(),
        imap_port: parseInt(document.getElementById("ep-f-imap-port")?.value) || 993,
        smtp_host: document.getElementById("ep-f-smtp-host")?.value.trim(),
        smtp_port: parseInt(document.getElementById("ep-f-smtp-port")?.value) || 587,
      };
      if (!account.email || !account.password || !account.imap_host || !account.smtp_host) {
        return alert("Fill in all required fields");
      }
      emailState.accounts.push(account);
      await apiPost("/api/email/accounts", { accounts: emailState.accounts });
      document.getElementById("ep-modal-overlay")?.remove();
      renderEmailPanel();
    });
  }

  function attachComposeEvents() {
    document.getElementById("ep-modal-close")?.addEventListener("click", () => {
      document.getElementById("ep-modal-overlay")?.remove();
    });
    document.getElementById("ep-modal-overlay")?.addEventListener("click", e => {
      if (e.target.id === "ep-modal-overlay") e.target.remove();
    });
    document.getElementById("ep-compose-send-btn")?.addEventListener("click", async () => {
      if (!emailState.activeAccount) return alert("Select an account first");
      const to = document.getElementById("ep-c-to")?.value.trim();
      const subject = document.getElementById("ep-c-subject")?.value.trim();
      const body = document.getElementById("ep-c-body")?.value.trim();
      if (!to || !subject || !body) return alert("Fill in all fields");
      try {
        await apiPost("/api/email/send", {
          account_email: emailState.activeAccount.email,
          to, subject, body,
        });
        alert("Sent!");
        document.getElementById("ep-modal-overlay")?.remove();
      } catch (err) {
        alert("Send error: " + err.message);
      }
    });
  }

  // ─── Load Emails ─────────────────────────────────────────────────────────
  async function loadEmails() {
    if (!emailState.activeAccount) return;
    emailState.loading = true;
    renderEmailPanel();
    try {
      const res = await apiPost("/api/email/fetch", {
        account_email: emailState.activeAccount.email,
        folder: "INBOX",
        limit: 30,
      });
      emailState.emails = res.emails || [];
    } catch (err) {
      emailState.emails = [];
      console.error("Email fetch error:", err);
    } finally {
      emailState.loading = false;
      renderEmailPanel();
    }
  }

  // ─── Init ─────────────────────────────────────────────────────────────────
  async function initEmailPanel() {
    try {
      const res = await apiGet("/api/email/accounts");
      emailState.accounts = res.accounts || [];
      if (emailState.accounts.length > 0) {
        emailState.activeAccount = emailState.accounts[0];
      }
    } catch (e) {
      emailState.accounts = [];
    }
    renderEmailPanel();
  }

  // ─── Public API ──────────────────────────────────────────────────────────
  window.EmailPanel = {
    open() {
      // Panel is rendered inside #email-panel div
      // Called when user clicks the email panel button
      initEmailPanel();
    },
    refresh() {
      loadEmails();
    },
  };
})();

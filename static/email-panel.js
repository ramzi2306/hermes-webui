/**
 * Email Panel — 3-column AI supervisor inbox
 * [ Thread Queue | Thread View (read-only) | Agent Chat ]
 * The rail stays visible to the left (handled by custom-loader.js).
 */
(function () {
  "use strict";

  // ─── State ─────────────────────────────────────────────────────────────────
  const S = {
    accounts: [],
    activeAccount: null,
    emails: [],          // raw emails from server
    threads: [],         // grouped threads
    activeThread: null,  // currently open thread id
    loading: false,
    filter: "all",       // all | favorites
    search: "",
    chat: {},            // threadId|__global__ -> [{role, text}]
    chatScope: "thread", // "thread" | "global"
    profile: "collab-manager",
    importCount: 60,
    emailSessionId: null,
    sse: null,
  };

  // ─── Helpers ───────────────────────────────────────────────────────────────
  const esc = s => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const initials = n => { const p = String(n || "?").trim().split(/\s+/); return ((p[0]?.[0] || "?") + (p[1]?.[0] || "")).toUpperCase(); };
  const timeAgo = ts => { const d = Date.now() / 1000 - ts; if (d < 60) return "now"; if (d < 3600) return Math.floor(d / 60) + "m"; if (d < 86400) return Math.floor(d / 3600) + "h"; return Math.floor(d / 86400) + "d"; };
  const normalizeSubject = s => String(s || "").replace(/^(re|fwd|fw|aw|tr)\s*:\s*/gi, "").replace(/^(re|fwd|fw|aw|tr)\s*:\s*/gi, "").trim().toLowerCase();

  const FAVS_KEY = "hermes_email_favorites";
  const getFavs = () => { try { return JSON.parse(localStorage.getItem(FAVS_KEY) || "{}"); } catch { return {}; } };
  const toggleFav = id => { const f = getFavs(); f[id] ? delete f[id] : f[id] = 1; localStorage.setItem(FAVS_KEY, JSON.stringify(f)); return !!f[id]; };
  const isFav = id => !!getFavs()[id];

  // Resolve a path against the app base (handles /session/<id> + subpath mounts)
  function apiUrl(p) { const rel = p.startsWith("/") ? p.slice(1) : p; return new URL(rel, document.baseURI || location.href).href; }
  async function apiGet(p) { const r = await fetch(apiUrl(p), { credentials: "include" }); if (!r.ok) throw new Error(await r.text()); return r.json(); }
  async function apiPost(p, b) {
    const r = await fetch(apiUrl(p), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(b) });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  // ─── Thread grouping ───────────────────────────────────────────────────────
  function groupThreads(emails) {
    const map = {};
    for (const e of emails) {
      const key = e.thread_key || normalizeSubject(e.subject) || e.from_email || e.id;
      if (!map[key]) {
        map[key] = { id: key, name: (e.subject || "(no subject)").replace(/^(re|fwd|fw)\s*:\s*/i, ""), emails: [], last_ts: 0, participants: new Set(), urgency: "normal" };
      }
      map[key].emails.push(e);
      map[key].last_ts = Math.max(map[key].last_ts, e.timestamp || 0);
      // Show the OTHER party as participant (skip own sent address)
      const who = e.direction === "sent" ? (e.to || "").split(/[,<]/)[0].trim() : (e.from_name || e.from_email);
      if (who) map[key].participants.add(who);
    }
    const threads = Object.values(map).map(t => {
      t.emails.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
      t.participants = [...t.participants].filter(Boolean);
      const last = t.emails[t.emails.length - 1];
      t.preview = last?.preview || "";
      return t;
    });
    threads.sort((a, b) => b.last_ts - a.last_ts);
    return threads;
  }

  // ─── Render ────────────────────────────────────────────────────────────────
  function render() {
    const root = document.getElementById("email-panel");
    if (!root) return;
    // Preserve queue scroll position across re-render (fixes scroll-to-top on click)
    const prevScroll = document.getElementById("ep3-thread-list")?.scrollTop || 0;
    root.innerHTML = `
      <div class="ep3">
        ${renderQueue()}
        ${renderThreadView()}
        ${renderAgentChat()}
      </div>`;
    attachEvents();
    const list = document.getElementById("ep3-thread-list");
    if (list) list.scrollTop = prevScroll;
    const chatBody = document.getElementById("ep3-chat-body");
    if (chatBody) chatBody.scrollTop = chatBody.scrollHeight;
    resizeFrames(document.getElementById("ep3-conversation"));
    attachThreadViewEvents();
  }

  // Select a thread WITHOUT a full re-render (preserves queue scroll & focus)
  function selectThread(id) {
    S.activeThread = id;
    document.querySelectorAll("#ep3-thread-list .ep3-thread").forEach(el =>
      el.classList.toggle("active", el.dataset.thread === id));
    const center = document.querySelector(".ep3-thread-view");
    if (center) {
      const tmp = document.createElement("div");
      tmp.innerHTML = renderThreadView();
      center.replaceWith(tmp.firstElementChild);
    }
    // Do NOT rebuild the right column — keep the Hermes chat iframe alive.
    resizeFrames(document.getElementById("ep3-conversation"));
    attachThreadViewEvents();
  }

  function attachThreadViewEvents() {
    const conv = document.getElementById("ep3-conversation");
    if (!conv || conv.dataset.wired === "1") return;
    conv.dataset.wired = "1";
    conv.addEventListener("click", async e => {
      const orig = e.target.closest("[data-original]");
      if (orig) return showOriginal(orig.dataset.original);
      const send = e.target.closest("[data-send-draft]");
      if (send) {
        const d = findDraft(send.dataset.sendDraft);
        if (d && confirm("Send this draft?")) await sendDraft(d);
        return;
      }
      const del = e.target.closest("[data-del-draft]");
      if (del) { await apiPost("/api/email/mgmt/delete-draft", { draft_id: del.dataset.delDraft }); await loadServerThreads(); render(); }
    });
  }

  function findDraft(id) {
    for (const t of S.threads) { const d = (t.drafts || []).find(x => x.draft_id === id); if (d) return d; }
    return null;
  }

  async function sendDraft(d) {
    try {
      await apiPost("/api/email/send", { account_email: S.activeAccount.email, to: d.to_addr || "", subject: d.subject || "", body: d.body || "" });
      await apiPost("/api/email/mgmt/delete-draft", { draft_id: d.draft_id });
      toast("Sent ✓");
      await syncInbox();
    } catch (err) { toast("Send failed: " + err.message); }
  }

  function renderQueue() {
    let threads = S.threads;
    if (S.filter === "favorites") threads = threads.filter(t => isFav(t.id));
    if (S.search) {
      const q = S.search.toLowerCase();
      threads = threads.filter(t => t.name.toLowerCase().includes(q) || t.participants.join(" ").toLowerCase().includes(q));
    }

    const accountBar = S.accounts.length ? S.accounts.map(a => `
      <div class="ep3-acct ${S.activeAccount?.email === a.email ? "active" : ""}" data-acct="${esc(a.email)}" title="${esc(a.email)}">${initials(a.name || a.email)}</div>
    `).join("") : `<button class="ep3-btn ep3-btn-sm" id="ep3-add-acct">+ Add Account</button>`;

    const list = S.loading
      ? `<div class="ep3-loading"><span class="ep3-spin"></span> Loading inbox…</div>`
      : threads.length === 0
        ? `<div class="ep3-empty-sm">${S.filter === "favorites" ? "No favorites yet" : "No threads"}</div>`
        : threads.map(t => {
            const u = t.urgency === "urgent" ? "🔴" : t.urgency === "low" ? "⚪" : "🟡";
            const fav = isFav(t.id);
            return `
              <div class="ep3-thread ${S.activeThread === t.id ? "active" : ""}" data-thread="${esc(t.id)}">
                <div class="ep3-thread-avatar">${initials(t.participants[0])}</div>
                <div class="ep3-thread-meta">
                  <div class="ep3-thread-top">
                    <span class="ep3-thread-urgency">${u}</span>
                    <span class="ep3-thread-name">${esc(t.name)}</span>
                  </div>
                  <div class="ep3-thread-parts">${esc(t.participants.slice(0, 3).join(", "))}${t.emails.length > 1 ? ` · ${t.emails.length}` : ""}</div>
                  <div class="ep3-thread-preview">${esc(t.preview)}</div>
                </div>
                <div class="ep3-thread-right">
                  <span class="ep3-thread-time">${timeAgo(t.last_ts)}</span>
                  <button class="ep3-star ${fav ? "on" : ""}" data-star="${esc(t.id)}">★</button>
                </div>
              </div>`;
          }).join("");

    return `
      <div class="ep3-col ep3-queue">
        <div class="ep3-queue-head">
          <div class="ep3-accts">${accountBar}</div>
          <div class="ep3-queue-tools">
            <button class="ep3-btn ep3-btn-icon ${S.filter === "favorites" ? "on" : ""}" id="ep3-fav-filter" title="Favorites">★</button>
            <button class="ep3-btn ep3-btn-icon" id="ep3-refresh" title="Refresh">⟳</button>
            <button class="ep3-btn ep3-btn-icon" id="ep3-settings" title="Settings">⚙</button>
          </div>
        </div>
        <input class="ep3-search" id="ep3-search" placeholder="Search threads…" value="${esc(S.search)}" />
        <div class="ep3-thread-list" id="ep3-thread-list">${list}</div>
      </div>`;
  }

  function renderThreadView() {
    const t = S.threads.find(x => x.id === S.activeThread);
    if (!t) {
      return `<div class="ep3-col ep3-thread-view"><div class="ep3-empty"><div class="ep3-empty-ico">✉</div><div>Select a thread</div></div></div>`;
    }
    const bubbles = t.emails.map((e, i) => {
      const mine = e.type === "outgoing" || e.direction === "sent";
      const who = mine ? "You" : (e.from_name || e.from_email);
      const bodyHtml = renderEmailBody(e, i);
      const badge = e.is_reworked
        ? `<button class="ep3-reworked" data-original="${esc(e.id)}" title="Show original">✨ reworked · view original</button>`
        : "";
      return `
        <div class="ep3-bubble-row ${mine ? "mine" : ""}">
          <div class="ep3-bubble ${mine ? "sent" : "recv"} ${e.is_reworked ? "reworked" : ""}">
            <div class="ep3-bubble-head">
              <span class="ep3-bubble-from">${esc(who)}</span>
              <span class="ep3-bubble-date">${esc(e.date)}${e.has_attachments ? " 📎" : ""}</span>
            </div>
            ${bodyHtml}
            ${badge}
          </div>
        </div>`;
    }).join("");

    // Unsent drafts — shown dotted
    const drafts = (t.drafts || []).map(d => `
        <div class="ep3-bubble-row mine">
          <div class="ep3-bubble sent ep3-draft-bubble">
            <div class="ep3-bubble-head"><span class="ep3-bubble-from">Draft (unsent)</span></div>
            <div class="ep3-bubble-body">${esc(d.body || "").replace(/\n/g, "<br>")}</div>
            <div class="ep3-draft-actions">
              <button class="ep3-btn ep3-btn-primary ep3-btn-sm" data-send-draft="${esc(d.draft_id)}">Send</button>
              <button class="ep3-btn ep3-btn-sm" data-del-draft="${esc(d.draft_id)}">Discard</button>
            </div>
          </div>
        </div>`).join("");

    return `
      <div class="ep3-col ep3-thread-view">
        <div class="ep3-tv-head">
          <div class="ep3-tv-title">${esc(t.name)}</div>
          <div class="ep3-tv-sub">${esc((t.participants || []).join(", "))}</div>
        </div>
        <div class="ep3-conversation" id="ep3-conversation">${bubbles}${drafts}</div>
      </div>`;
  }

  // Render email body — HTML in sandboxed iframe (allow-same-origin so we can
  // measure height; NO allow-scripts so embedded JS can't run), else plain text.
  function cleanEmailHtml(html) {
    // Strip scripts, external stylesheets/fonts, and event handlers to cut CSP
    // noise and keep rendering predictable. Inline styles are kept.
    return String(html || "")
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/<link[^>]*>/gi, "")
      .replace(/<style[\s\S]*?<\/style>/gi, "")
      .replace(/\son\w+\s*=\s*"[^"]*"/gi, "")
      .replace(/\son\w+\s*=\s*'[^']*'/gi, "")
      .replace(/<meta[^>]*http-equiv[^>]*>/gi, "");
  }

  function renderEmailBody(e, idx) {
    const html = e.body_html ? cleanEmailHtml(e.body_html) : "";
    if (html && html.length > 20) {
      // Render INLINE (no iframe) — full width, natural height, no inner scroll.
      // Wrapped in .ep3-html so scoped CSS forces full-width + responsive images.
      return `<div class="ep3-html">${html}</div>`;
    }
    const txt = (e.body || "").replace(/\n{3,}/g, "\n\n").trim();
    return `<div class="ep3-bubble-body">${esc(txt).replace(/\n/g, "<br>")}</div>`;
  }

  // No-op kept for callers; inline HTML needs no resizing
  function resizeFrames(root) {
    // After inline render, force email links to open in new tab
    (root || document).querySelectorAll(".ep3-html a").forEach(a => {
      a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener");
    });
  }

  // Render markdown-ish: bold, code, links, line breaks
  function mdLite(text) {
    let h = esc(text);
    h = h.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/`([^`]+)`/g, "<code>$1</code>");
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/\n/g, "<br>");
    return h;
  }

  function renderAgentChat() {
    const t = S.threads.find(x => x.id === S.activeThread);
    const global = S.chatScope === "global";
    // The RIGHT panel is the REAL Hermes chat, embedded via iframe (same-origin),
    // pointed at a dedicated email session with the rail/sidebar hidden.
    return `
      <div class="ep3-col ep3-agent-chat">
        <div class="ep3-chat-head">
          <span class="ep3-chat-title">🤖 Hermes — mailbox assistant</span>
        </div>
        <iframe id="ep3-hermes-frame" class="ep3-hermes-frame" title="Hermes chat"></iframe>
      </div>`;
  }

  // ─── Embed the real Hermes chat ─────────────────────────────────────────────
  async function initHermesChat() {
    const frame = document.getElementById("ep3-hermes-frame");
    if (!frame) return;
    if (frame.dataset.loaded === "1") return;  // don't reload on every render
    try {
      const sid = await ensureEmailSession();
      if (!sid) { frame.outerHTML = '<div class="ep3-chat-hint">Could not start chat session.</div>'; return; }
      frame.dataset.loaded = "1";
      frame.src = apiUrl("session/" + encodeURIComponent(sid));
      frame.addEventListener("load", () => {
        try {
          const doc = frame.contentDocument;
          if (!doc) return;
          // Inject CSS to strip the app chrome → only the chat remains
          const style = doc.createElement("style");
          style.textContent = `
            nav.rail, aside.sidebar, .app-titlebar, .mobile-nav, #mobileOverlay,
            .rail, .titlebar, .window-controls { display: none !important; }
            .layout { grid-template-columns: 1fr !important; display: block !important; }
            main.main, .main { width: 100% !important; margin: 0 !important; left: 0 !important; }
            body, html { overflow: hidden !important; }
          `;
          doc.head.appendChild(style);
        } catch (e) { /* cross-origin shouldn't happen (same origin) */ }
      }, { once: true });
    } catch (e) {
      frame.outerHTML = `<div class="ep3-chat-hint">Chat error: ${esc(e.message)}</div>`;
    }
  }

  // Type the current thread into the embedded Hermes composer and send it
  function discussThread() {
    const t = S.threads.find(x => x.id === S.activeThread);
    const frame = document.getElementById("ep3-hermes-frame");
    if (!t || !frame) return;
    try {
      const doc = frame.contentDocument;
      const input = doc.getElementById("msg") || doc.querySelector("textarea");
      if (!input) return toast("Chat not ready yet — try again in a moment.");
      const thread = (t.emails || []).map(e => `--- ${e.direction === "sent" ? "Ramzi" : (e.from_name || e.from_email)} (${e.date}) ---\n${(e.body || "").slice(0, 1500)}`).join("\n\n");
      input.value = `Here is an email thread from my inbox titled "${t.name}". Help me with it (summarize, draft a reply, etc.):\n\n${thread}`;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      const sendBtn = doc.getElementById("sendBtn") || doc.querySelector('[onclick*="send"], button.send');
      if (sendBtn) sendBtn.click();
      else if (frame.contentWindow.send) frame.contentWindow.send();
    } catch (e) { toast("Could not pass thread to chat: " + e.message); }
  }

  // ─── Events ────────────────────────────────────────────────────────────────
  function attachEvents() {
    document.querySelectorAll(".ep3-acct").forEach(el => el.addEventListener("click", async () => {
      S.activeAccount = S.accounts.find(a => a.email === el.dataset.acct);
      S.activeThread = null;
      await loadInbox();
    }));
    document.getElementById("ep3-add-acct")?.addEventListener("click", openSettings);
    document.getElementById("ep3-settings")?.addEventListener("click", openSettings);
    document.getElementById("ep3-refresh")?.addEventListener("click", syncInbox);
    document.getElementById("ep3-fav-filter")?.addEventListener("click", () => { S.filter = S.filter === "favorites" ? "all" : "favorites"; render(); });
    const searchEl = document.getElementById("ep3-search");
    if (searchEl) searchEl.addEventListener("input", e => { S.search = e.target.value; refreshThreadList(); });

    // Thread selection — partial update (no full re-render, preserves scroll)
    document.getElementById("ep3-thread-list")?.addEventListener("click", e => {
      const star = e.target.closest("[data-star]");
      if (star) { e.stopPropagation(); const on = toggleFav(star.dataset.star); star.classList.toggle("on", on); return; }
      const th = e.target.closest("[data-thread]");
      if (th) selectThread(th.dataset.thread);
    });

    attachChatEvents();
    initHermesChat();
  }

  // Wire the embedded-chat toolbar
  function attachChatEvents() {
    document.getElementById("ep3-discuss")?.addEventListener("click", discussThread);
  }

  // Rebuild only the thread list (for search), preserving scroll
  function refreshThreadList() {
    const list = document.getElementById("ep3-thread-list");
    if (!list) return;
    const scroll = list.scrollTop;
    const tmp = document.createElement("div");
    tmp.innerHTML = renderQueue();
    const fresh = tmp.querySelector("#ep3-thread-list");
    if (fresh) list.innerHTML = fresh.innerHTML;
    list.scrollTop = scroll;
  }

  // ─── Actions ───────────────────────────────────────────────────────────────
  function chatKey() { return S.chatScope === "global" ? "__global__" : S.activeThread; }

  function pushMsg(role, text, extra) {
    const key = chatKey();
    if (!key) return;
    if (!S.chat[key]) S.chat[key] = [];
    S.chat[key].push({ role, text, ...extra });
    render();
  }

  function replaceTyping(role, text, extra) {
    const key = chatKey();
    const arr = S.chat[key] || [];
    const i = arr.findIndex(m => m.role === "typing");
    if (i >= 0) arr.splice(i, 1, { role, text, ...extra });
    else arr.push({ role, text, ...extra });
    render();
  }

  // Build a digest of the whole mailbox for global-scope questions
  function mailboxDigest() {
    return S.threads.slice(0, 30).map(t => {
      const last = t.emails[t.emails.length - 1];
      return { subject: t.name, from_name: t.participants[0] || "", from_email: last?.from_email || "", date: last?.date || "", body: (last?.body || "").slice(0, 400), count: t.emails.length };
    });
  }

  // ─── Real streaming chat (reuses the main Hermes chat pipeline) ─────────────
  async function ensureEmailSession() {
    if (S.emailSessionId) return S.emailSessionId;
    const stored = localStorage.getItem("hermes_email_session");
    if (stored) { S.emailSessionId = stored; return stored; }
    const r = await apiPost("/api/session/new", { profile: S.profile });
    const sid = r.session_id || r.session?.session_id || r.id;
    S.emailSessionId = sid;
    if (sid) localStorage.setItem("hermes_email_session", sid);
    return sid;
  }

  function updateStreamingBubble(msg) {
    const body = document.getElementById("ep3-chat-body");
    if (!body) return;
    const bubbles = body.querySelectorAll(".ep3-msg.agent .ep3-msg-bubble");
    const el = bubbles[bubbles.length - 1];
    if (!el) return;
    let html = mdLite(msg.text || "");
    if (msg.tools && msg.tools.length) {
      html = msg.tools.map(n => `<span class="ep3-tool-chip">⚙ ${esc(n)}</span>`).join(" ") + (html ? "<br>" + html : "");
    }
    if (msg.streaming) html += '<span class="ep3-cursor">▋</span>';
    el.innerHTML = html || '<span class="ep3-typing"><span></span><span></span><span></span></span>';
    body.scrollTop = body.scrollHeight;
  }

  async function streamSend(displayText, fullPrompt) {
    const key = chatKey();
    if (!S.chat[key]) S.chat[key] = [];
    S.chat[key].push({ role: "user", text: displayText });
    const agentMsg = { role: "agent", text: "", streaming: true, tools: [] };
    S.chat[key].push(agentMsg);
    render();
    updateStreamingBubble(agentMsg);  // show typing dots immediately
    try {
      const sid = await ensureEmailSession();
      if (!sid) throw new Error("could not create email session");
      const start = await apiPost("/api/chat/start", { session_id: sid, message: fullPrompt, profile: S.profile });
      const streamId = start.stream_id;
      if (!streamId) throw new Error(start.error || "no stream id");
      await new Promise(resolve => {
        const url = apiUrl(`api/chat/stream?stream_id=${encodeURIComponent(streamId)}&session_id=${encodeURIComponent(sid)}`);
        const src = new EventSource(url, { withCredentials: true });
        let settled = false;
        const finish = () => { if (settled) return; settled = true; agentMsg.streaming = false; try { src.close(); } catch {} updateStreamingBubble(agentMsg); resolve(); };
        src.addEventListener("token", e => { try { agentMsg.text += (JSON.parse(e.data).text || ""); updateStreamingBubble(agentMsg); } catch {} });
        src.addEventListener("interim_assistant", e => { try { const d = JSON.parse(e.data); if (d.text && !d.already_streamed) { agentMsg.text += (agentMsg.text ? "\n\n" : "") + d.text; updateStreamingBubble(agentMsg); } } catch {} });
        src.addEventListener("tool", e => { try { const n = JSON.parse(e.data).name; if (n && n !== "clarify") { agentMsg.tools.push(n); updateStreamingBubble(agentMsg); } } catch {} });
        src.addEventListener("done", finish);
        src.addEventListener("error", () => { if (!agentMsg.text) agentMsg.text = "⚠️ stream error — is the agent running?"; finish(); });
      });
    } catch (err) {
      agentMsg.streaming = false;
      agentMsg.text = "⚠️ " + err.message;
      updateStreamingBubble(agentMsg);
    }
  }

  async function sendChat() {
    const global = S.chatScope === "global";
    const input = document.getElementById("ep3-chat-input");
    const msg = input?.value.trim();
    const t = S.threads.find(x => x.id === S.activeThread);
    if (!msg || (!global && !t)) return;
    input.value = "";
    let ctx;
    if (global) {
      const digest = mailboxDigest().map(d => `• ${d.subject} — ${d.from_name} (${d.date}): ${(d.body || "").slice(0, 180)}`).join("\n");
      ctx = `[Email mailbox context — ${mailboxDigest().length} recent threads]\n${digest}\n\nRamzi asks: ${msg}`;
    } else {
      const thread = (t?.emails || []).map(e => `--- ${e.direction === "sent" ? "Ramzi" : (e.from_name || e.from_email)} (${e.date}) ---\n${(e.body || "").slice(0, 1500)}`).join("\n\n");
      ctx = `[Email thread: "${t.name}"]\n${thread}\n\nRamzi asks: ${msg}`;
    }
    await streamSend(msg, ctx);
  }

  async function quickAction(kind) {
    const global = S.chatScope === "global";
    const t = S.threads.find(x => x.id === S.activeThread);
    if (kind === "summarize") {
      if (global) {
        const digest = mailboxDigest().map(d => `• ${d.subject} — ${d.from_name}: ${(d.body || "").slice(0, 150)}`).join("\n");
        await streamSend("Summarize my inbox", `[Mailbox digest]\n${digest}\n\nSummarize the key items, flag anything urgent, and tell me who needs a reply.`);
      } else {
        const thread = (t.emails || []).map(e => `--- ${e.direction === "sent" ? "Ramzi" : (e.from_name || e.from_email)} ---\n${(e.body || "").slice(0, 1500)}`).join("\n\n");
        await streamSend("Summarize this thread", `[Thread: "${t.name}"]\n${thread}\n\nSummarize this thread concisely.`);
      }
    } else if (kind === "draft") {
      if (!t) return;
      pushMsg("user", "Draft a reply");
      pushMsg("typing", "");
      const last = t.emails[t.emails.length - 1];
      try {
        const res = await apiPost("/api/email/draft", { email: last, instruction: "" });
        replaceTyping("draft", res.draft, { id: S.activeThread });
      } catch (err) { replaceTyping("agent", "Error: " + err.message); }
    }
  }

  async function approveDraft(threadId) {
    const t = S.threads.find(x => x.id === threadId);
    if (!t || !S.activeAccount) return alert("Missing thread or account");
    const draftEl = document.querySelector(`[data-draft-id="${threadId}"]`);
    const body = draftEl ? draftEl.innerText : "";
    const last = t.emails[t.emails.length - 1];
    if (!confirm(`Send this reply to ${last.from_email}?`)) return;
    try {
      await apiPost("/api/email/send", {
        account_email: S.activeAccount.email,
        to: last.from_email,
        subject: "Re: " + (last.subject || t.name),
        body,
        reply_to_message_id: last.message_id,
      });
      S.chat[threadId] = (S.chat[threadId] || []).filter(m => m.role !== "draft");
      pushMsg("agent", "✓ Sent to " + last.from_email);
    } catch (err) {
      alert("Send failed: " + err.message);
    }
  }

  // ─── Settings modal ────────────────────────────────────────────────────────
  function openSettings() {
    const html = `
      <div class="ep3-modal-bg" id="ep3-modal-bg">
        <div class="ep3-modal">
          <div class="ep3-modal-head"><span>Email Settings</span><button class="ep3-btn ep3-btn-icon" id="ep3-modal-x">✕</button></div>
          <div class="ep3-modal-body">
            <label class="ep3-lbl">Agent profile handling the mailbox</label>
            <select class="ep3-input" id="ep3-profile-sel"></select>

            <label class="ep3-lbl">Emails to import per folder (INBOX + Sent)</label>
            <input class="ep3-input" id="ep3-import-count" type="number" min="10" max="1000" value="${S.importCount || 60}" />
            <small style="color:var(--muted);font-size:11px;">Higher = more history pulled on each sync. Stored locally.</small>

            <div class="ep3-accounts-list">
              ${S.accounts.map((a, i) => `<div class="ep3-acct-row"><div><strong>${esc(a.name || a.email)}</strong><br><small>${esc(a.email)}</small></div><button class="ep3-btn ep3-btn-danger ep3-btn-sm" data-rm="${i}">Remove</button></div>`).join("")}
            </div>

            <div class="ep3-add-form">
              <h4>Add Account</h4>
              <input class="ep3-input" id="f-name" placeholder="Display Name" />
              <input class="ep3-input" id="f-email" placeholder="Email" type="email" />
              <input class="ep3-input" id="f-pass" placeholder="Password" type="password" />
              <div class="ep3-row"><input class="ep3-input" id="f-imap" placeholder="IMAP host" /><input class="ep3-input ep3-input-sm" id="f-imap-p" value="993" /></div>
              <div class="ep3-row"><input class="ep3-input" id="f-smtp" placeholder="SMTP host" /><input class="ep3-input ep3-input-sm" id="f-smtp-p" value="587" /></div>
              <button class="ep3-btn ep3-btn-primary" id="ep3-save-acct">Save Account</button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML("beforeend", html);
    populateProfiles();
    const close = () => document.getElementById("ep3-modal-bg")?.remove();
    document.getElementById("ep3-modal-x").onclick = close;
    document.getElementById("ep3-modal-bg").onclick = e => { if (e.target.id === "ep3-modal-bg") close(); };
    const saveSettings = async () => {
      S.profile = document.getElementById("ep3-profile-sel")?.value || S.profile;
      S.importCount = parseInt(document.getElementById("ep3-import-count")?.value) || 60;
      await apiPost("/api/email/settings", { save: true, settings: { profile: S.profile, import_count: S.importCount } }).catch(() => {});
    };
    document.getElementById("ep3-profile-sel").onchange = saveSettings;
    document.getElementById("ep3-import-count").onchange = saveSettings;
    document.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => {
      S.accounts.splice(parseInt(b.dataset.rm), 1);
      await apiPost("/api/email/accounts", { accounts: S.accounts });
      close(); render();
    });
    document.getElementById("ep3-save-acct").onclick = async () => {
      const acct = {
        name: document.getElementById("f-name").value.trim(),
        email: document.getElementById("f-email").value.trim(),
        password: document.getElementById("f-pass").value,
        imap_host: document.getElementById("f-imap").value.trim(),
        imap_port: parseInt(document.getElementById("f-imap-p").value) || 993,
        smtp_host: document.getElementById("f-smtp").value.trim(),
        smtp_port: parseInt(document.getElementById("f-smtp-p").value) || 587,
      };
      if (!acct.email || !acct.password || !acct.imap_host || !acct.smtp_host) return alert("Fill all fields");
      S.accounts.push(acct);
      await apiPost("/api/email/accounts", { accounts: S.accounts });
      close(); if (!S.activeAccount) S.activeAccount = acct; loadInbox();
    };
  }

  async function populateProfiles() {
    const sel = document.getElementById("ep3-profile-sel");
    if (!sel) return;
    let profiles = ["collab-manager", "default"];
    try {
      const res = await apiGet("/api/profiles");
      if (Array.isArray(res?.profiles)) profiles = res.profiles.map(p => p.name || p);
      else if (Array.isArray(res)) profiles = res.map(p => p.name || p);
    } catch {}
    if (!profiles.includes(S.profile)) profiles.unshift(S.profile);
    sel.innerHTML = profiles.map(p => `<option value="${esc(p)}" ${p === S.profile ? "selected" : ""}>${esc(p)}</option>`).join("");
  }

  // ─── Load ──────────────────────────────────────────────────────────────────
  // Load server-side threads (AI-controlled order/title/rework/drafts)
  async function loadServerThreads() {
    const res = await apiGet(`/api/email/threads?account=${encodeURIComponent(S.activeAccount.email)}`);
    // normalize to the shape the UI uses
    S.threads = (res.threads || []).map(t => ({
      id: t.thread_id,
      thread_id: t.thread_id,
      name: t.title || "(no subject)",
      position: t.position,
      last_ts: t.last_ts || 0,
      participants: t.participants || [],
      emails: t.emails || [],
      drafts: t.drafts || [],
      preview: (t.emails?.[t.emails.length - 1]?.body || "").slice(0, 140).replace(/\n/g, " "),
      urgency: "normal",
    }));
  }

  async function loadInbox() {
    if (!S.activeAccount) { render(); return; }
    S.loading = true; render();
    try {
      // Ensure emails are threaded server-side, then load threads.
      await apiPost("/api/email/mgmt/preprocess", { account: S.activeAccount.email }).catch(() => {});
      await loadServerThreads();
      S.loading = false; render();
      if (S.threads.length === 0) { await syncInbox(); }  // empty store → first sync
    } catch (err) {
      console.error("inbox load failed", err);
      S.threads = []; S.loading = false; render();
    }
  }

  async function syncInbox() {
    if (!S.activeAccount) return;
    const btn = document.getElementById("ep3-refresh");
    if (btn) btn.classList.add("spinning");
    S.syncing = true;
    try {
      const res = await apiPost("/api/email/sync", { account_email: S.activeAccount.email, limit: 300 });
      await apiPost("/api/email/mgmt/preprocess", { account: S.activeAccount.email }).catch(() => {});
      await loadServerThreads();
      const n = res.sync?.new || 0;
      if (n > 0) toast(`Synced ${n} new email${n > 1 ? "s" : ""}`);
      else if (res.sync?.error) toast("Sync error: " + res.sync.error);
    } catch (err) {
      toast("Sync failed: " + err.message);
    } finally {
      S.syncing = false; render();
    }
  }

  // Open the immutable original of a reworked email in a popup
  async function showOriginal(emailId) {
    try {
      const o = await apiGet(`/api/email/original?id=${encodeURIComponent(emailId)}`);
      const html = o.body_html ? cleanEmailHtml(o.body_html) : "";
      const bodyHtml = html ? `<div class="ep3-html">${html}</div>` : `<div class="ep3-bubble-body">${esc(o.body_text || "").replace(/\n/g, "<br>")}</div>`;
      const modal = document.createElement("div");
      modal.className = "ep3-modal-bg";
      modal.innerHTML = `<div class="ep3-modal" style="max-width:680px;">
        <div class="ep3-modal-head"><span>Original email</span><button class="ep3-btn ep3-btn-icon" id="ep3-orig-x">✕</button></div>
        <div class="ep3-modal-body"><div style="font-size:12px;color:var(--muted);margin-bottom:8px;">${esc(o.from_name || "")} &lt;${esc(o.from_email || "")}&gt; · ${esc(o.date || "")}</div>${bodyHtml}</div>
      </div>`;
      document.body.appendChild(modal);
      const close = () => modal.remove();
      modal.querySelector("#ep3-orig-x").onclick = close;
      modal.onclick = e => { if (e.target === modal) close(); };
    } catch (e) { toast("Could not load original: " + e.message); }
  }

  function toast(msg) {
    const n = document.createElement("div");
    n.className = "ep3-toast";
    n.textContent = msg;
    document.body.appendChild(n);
    setTimeout(() => n.remove(), 4000);
  }

  // ─── SSE for live agent updates ────────────────────────────────────────────
  function connectSSE() {
    if (S.sse) return;
    try {
      S.sse = new EventSource("/api/email/events");
      S.sse.onmessage = ev => {
        try {
          const { type, data } = JSON.parse(ev.data);
          if (type === "notification") {
            // lightweight toast
            const n = document.createElement("div");
            n.className = "ep3-toast";
            n.textContent = data.message;
            document.body.appendChild(n);
            setTimeout(() => n.remove(), 5000);
          }
          // card_shown / queue_updated could refresh queue — keep simple for now
        } catch {}
      };
      S.sse.onerror = () => { S.sse?.close(); S.sse = null; setTimeout(connectSSE, 5000); };
    } catch {}
  }

  // ─── Init ──────────────────────────────────────────────────────────────────
  async function init() {
    try {
      const res = await apiGet("/api/email/accounts");
      S.accounts = res.accounts || [];
      if (S.accounts.length) S.activeAccount = S.accounts[0];
    } catch { S.accounts = []; }
    try {
      const st = await apiGet("/api/email/state").catch(() => null);
    } catch {}
    try {
      const settings = await apiPost("/api/email/settings", {}).catch(() => null);
      if (settings?.profile) S.profile = settings.profile;
      if (settings?.import_count) S.importCount = settings.import_count;
    } catch {}
    render();
    if (S.activeAccount) loadInbox();
    connectSSE();
  }

  window.EmailPanel = { open: init, refresh: loadInbox };
})();

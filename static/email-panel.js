/**
 * AI Mail — Hermes (Triage Stack design)
 * Apple-Mail-inspired agent-operated inbox. Real server data + the real
 * embedded Hermes chat as the dock. Scoped under .aimail.
 */
(function () {
  "use strict";

  // ─── State ─────────────────────────────────────────────────────────────────
  const S = {
    accounts: [], activeAccount: null,
    threads: [], activeThread: null,
    loading: false, view: "A",          // A=Stack B=Board C=Briefing
    profile: "collab-manager", importCount: 60,
    tgToken: "", tgChat: "",
    emailSessionId: null,
    origOpen: {},                        // emailId -> bool (view original inline)
    lastSync: 0,
  };

  // ─── Helpers ───────────────────────────────────────────────────────────────
  const esc = s => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const initials = n => { const p = String(n || "?").replace(/[^a-zA-Z ]/g, "").trim().split(/\s+/); return ((p[0]?.[0] || "?") + (p[1]?.[0] || "")).toUpperCase(); };
  const avatarColor = n => { const c = ["#E5484D", "#E8922B", "#5B7FB4", "#6E56CF", "#2f9e5e", "#9AA0A6"]; let h = 0; for (const ch of String(n || "")) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return c[h % c.length]; };
  const timeShort = ts => { if (!ts) return ""; const d = new Date(ts * 1000), now = Date.now() / 1000; if (now - ts < 86400) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); return d.toLocaleDateString([], { month: "short", day: "numeric" }); };

  // Lane derived from agent-controlled position
  const LANES = [
    { key: "urgent", label: "Urgent", why: "needs you now" },
    { key: "today", label: "Today", why: "before end of day" },
    { key: "later", label: "Later", why: "this week" },
    { key: "fyi", label: "FYI", why: "auto-summarized" },
  ];
  const laneOf = t => { const p = t.position ?? 99; return p <= 1 ? "urgent" : p <= 4 ? "today" : p <= 9 ? "later" : "fyi"; };

  // Minimal icon set (stroke 1.8)
  const ic = (name) => {
    const P = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
    const m = {
      sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z" fill="currentColor" stroke="none"/>',
      search: `<circle cx="11" cy="11" r="7" ${P}/><path d="M21 21l-4-4" ${P}/>`,
      run: `<path d="M3 12a9 9 0 1 0 2.6-6.4" ${P}/><path d="M3 4v4h4" ${P}/>`,
      inbox: `<path d="M3 12h5l2 3h4l2-3h5" ${P}/><path d="M5 5h14l2 7v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6L5 5z" ${P}/>`,
      dock: `<rect x="3" y="5" width="18" height="14" rx="2" ${P}/><path d="M15 5v14" ${P}/>`,
      clip: `<path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.5a1.6 1.6 0 0 1-2.3-2.3l7.8-7.8" ${P}/>`,
      layers: `<path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5" ${P}/>`,
      pencil: `<path d="M4 20l4-1 11-11-3-3L5 16l-1 4z" ${P}/>`,
      chevron: `<path d="M6 9l6 6 6-6" ${P}/>`,
      send: `<path d="M4 12l16-7-7 16-2.5-6.5L4 12z" ${P}/>`,
      plane: `<path d="M21.5 3.5L2.5 11l7 2.5M21.5 3.5L18 20l-8.5-6.5M21.5 3.5L9.5 13.5" ${P}/>`,
      archive: `<rect x="3" y="4" width="18" height="4" rx="1" ${P}/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4" ${P}/>`,
      check: `<path d="M5 12l4.5 4.5L19 7" ${P}/>`,
      trash: `<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0v12a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V7" ${P}/>`,
      edit: `<path d="M5 19h14M14 5l3 3-9 9H5v-3l9-9z" ${P}/>`,
      sliders: `<path d="M4 8h10M18 8h2M4 16h2M10 16h10" ${P}/><circle cx="16" cy="8" r="2.3" ${P}/><circle cx="8" cy="16" r="2.3" ${P}/>`,
    };
    return `<svg viewBox="0 0 24 24" width="1em" height="1em" class="spk">${m[name] || ""}</svg>`;
  };

  // ─── API ───────────────────────────────────────────────────────────────────
  const apiUrl = p => { const r = p.startsWith("/") ? p.slice(1) : p; return new URL(r, document.baseURI || location.href).href; };
  async function apiGet(p) { const r = await fetch(apiUrl(p), { credentials: "include" }); if (!r.ok) throw new Error(await r.text()); return r.json(); }
  async function apiPost(p, b) { const r = await fetch(apiUrl(p), { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(b) }); if (!r.ok) throw new Error(await r.text()); return r.json(); }

  const cleanHtml = h => String(h || "").replace(/<script[\s\S]*?<\/script>/gi, "").replace(/<link[^>]*>/gi, "").replace(/<style[\s\S]*?<\/style>/gi, "").replace(/\son\w+\s*=\s*"[^"]*"/gi, "").replace(/\son\w+\s*=\s*'[^']*'/gi, "");

  // ─── Render ────────────────────────────────────────────────────────────────
  function render() {
    const root = document.getElementById("email-panel");
    if (!root) return;
    const prevScroll = document.querySelector(".aimail .list-scroll")?.scrollTop || 0;
    root.innerHTML = `<div class="aimail">${renderToolbar()}<div class="cols">${renderList()}${renderReading()}${renderDock()}</div></div>`;
    attachEvents();
    const ls = document.querySelector(".aimail .list-scroll"); if (ls) ls.scrollTop = prevScroll;
    initHermesChat();
  }

  function renderToolbar() {
    const VIEWS = [["A", "Stack", "inbox"], ["B", "Board", "dock"], ["C", "Briefing", "sparkle"]];
    const acct = S.activeAccount?.email || "";
    return `
      <div class="toolbar">
        <div class="view-seg">
          ${VIEWS.map(([k, lbl, icn]) => `<button class="${S.view === k ? "on" : ""}" data-view="${k}">${ic(icn)} ${lbl}</button>`).join("")}
        </div>
        <div class="search">${ic("search")}<input placeholder="Search mail, or ask Hermes…" /><kbd>⌘K</kbd></div>
        <div class="tl-right">
          <div class="run-pill" title="Hermes runs autonomously at 10:00 and 22:00">
            <span class="live"></span>
            <div class="rp-txt"><b>Synced ${S.lastSync ? timeShort(S.lastSync) : "—"}</b><span>next run 10:00 PM · Telegram ${S.tgChat ? "on" : "off"}</span></div>
          </div>
          <button class="btn-run" id="aim-run">${ic("run")} Run now</button>
          <button class="icon-btn" id="aim-settings" title="Settings">${ic("sliders")}</button>
          <div class="tl-acct" title="${esc(acct)}">${initials(S.activeAccount?.name || acct || "R")}</div>
        </div>
      </div>`;
  }

  function renderList() {
    if (!S.accounts.length) {
      return `<div class="list"><div class="list-head"><h2>Triage</h2></div><div class="list-scroll"><div style="padding:24px"><button class="btn primary" id="aim-add-acct">+ Add email account</button></div></div></div>`;
    }
    if (S.loading) return `<div class="list"><div class="list-head"><h2>Triage</h2></div><div class="list-scroll"><div style="padding:24px;color:var(--ink-4)">Loading…</div></div></div>`;

    const byLane = {};
    S.threads.forEach(t => { const l = laneOf(t); (byLane[l] = byLane[l] || []).push(t); });

    const lanesHtml = LANES.map(lane => {
      const items = byLane[lane.key] || [];
      if (!items.length) return "";
      return `<div class="lane">
        <div class="lane-h ${lane.key}"><span class="bar"></span><span class="nm">${lane.label}</span><span class="ct">${items.length}</span><span class="why">${lane.why}</span></div>
        ${items.map(renderRow).join("")}
      </div>`;
    }).join("");

    return `<div class="list">
      <div class="list-head"><h2>Triage</h2><span class="list-sub">${ic("sparkle")} ordered by Hermes</span></div>
      <div class="list-scroll">${lanesHtml || '<div style="padding:24px;color:var(--ink-4)">No threads yet — hit Run now or ⟳.</div>'}</div>
    </div>`;
  }

  function renderRow(t) {
    const last = t.emails[t.emails.length - 1] || {};
    const who = (t.participants && t.participants[0]) || last.from_name || last.from_email || "—";
    const reworked = t.emails.some(e => e.is_reworked);
    const hasDraft = (t.drafts || []).length > 0;
    return `<div class="row ${S.activeThread === t.thread_id ? "sel" : ""}" data-thread="${esc(t.thread_id)}">
      <div class="av" style="background:${avatarColor(who)}">${initials(who)}</div>
      <div class="mid">
        <div class="l1"><span class="from">${esc(who)}</span><span class="time">${timeShort(t.last_ts)}</span></div>
        <div class="subj">${esc(t.name)}</div>
        <div class="snip">${esc(t.preview || last.body || "")}</div>
        <div class="tags">
          ${reworked ? `<span class="tag ai">${ic("sparkle")} cleaned</span>` : ""}
          ${t.emails.length > 1 ? `<span class="tag">${ic("layers")} ${t.emails.length}</span>` : ""}
          ${hasDraft ? `<span class="tag draft">${ic("pencil")} draft ready</span>` : ""}
        </div>
      </div>
    </div>`;
  }

  function renderReading() {
    const t = S.threads.find(x => x.thread_id === S.activeThread);
    if (!t) return `<div class="reading"><div class="empty">${ic("inbox")}<div>Select a thread to read</div></div></div>`;
    const last = t.emails[t.emails.length - 1] || {};
    const who = (t.participants && t.participants[0]) || last.from_name || last.from_email || "—";
    const reworked = t.emails.some(e => e.is_reworked);

    const bodies = t.emails.map(e => {
      const mine = e.type === "outgoing" || e.direction === "sent";
      const open = !!S.origOpen[e.id];
      const html = e.body_html ? cleanHtml(e.body_html) : "";
      const bodyBlock = html
        ? `<div class="read-body"><div class="ep3-html">${html}</div></div>`
        : `<div class="read-body"><p>${esc(e.body || "").replace(/\n{3,}/g, "\n\n").replace(/\n/g, "<br>")}</p></div>`;
      return `
        <div class="msg-head">
          <div class="av" style="background:${avatarColor(mine ? "You" : who)}">${initials(mine ? "You" : who)}</div>
          <div class="mh-mid"><div class="mh-from">${esc(mine ? "You" : (e.from_name || e.from_email))}</div><div class="mh-to">${esc(e.date || "")}</div></div>
          <div class="mh-time">${esc(e.date || "")}</div>
        </div>
        ${e.is_reworked ? `
        <div class="clean-strip">
          <div class="cs-txt">${ic("sparkle")} Hermes rewrote this to the essentials</div>
          <div class="spacer"></div>
          <button class="link-btn ${open ? "open" : ""}" data-orig="${esc(e.id)}">${open ? "Hide original" : "View original"} ${ic("chevron")}</button>
        </div>
        <div class="orig ${open ? "show" : ""}" id="orig-${esc(e.id)}">${open ? `<div class="orig-inner"><div class="ol">${ic("layers")} Original — exactly as it arrived</div><div class="ot">${esc(S.origCache?.[e.id] || "loading…")}</div></div>` : ""}</div>
        ` : ""}
        ${bodyBlock}`;
    }).join("");

    const drafts = (t.drafts || []).map(d => `
      <div class="draft">
        <div class="d-head"><div class="d-av">${ic("sparkle")}</div><div class="d-lbl">Hermes drafted a reply <span>· not sent — your approval needed</span></div></div>
        <div class="d-to">To: ${esc(d.to_addr || last.from_email || "")}</div>
        <textarea class="d-body" data-draft="${esc(d.draft_id)}">${esc(d.body || "")}</textarea>
        <div class="d-acts">
          <button class="btn primary" data-send-draft="${esc(d.draft_id)}">${ic("send")} Send</button>
          <button class="btn" data-edit-draft="${esc(d.draft_id)}">${ic("edit")} Edit in chat</button>
          <button class="btn ghost" data-del-draft="${esc(d.draft_id)}">${ic("trash")} Discard</button>
        </div>
      </div>`).join("");

    return `<div class="reading">
      <div class="read-bar">
        <button class="icon-btn" title="Archive">${ic("archive")}</button>
        <div class="spacer"></div>
        <button class="btn" style="height:32px" id="aim-tg-thread">${ic("plane")} Send to Telegram</button>
      </div>
      <div class="read-scroll"><div class="read-inner">
        <h1 class="read-subj">${esc(t.name)}</h1>
        <div class="read-namedby">${ic("sparkle")} Named &amp; grouped by Hermes · ${t.emails.length} ${t.emails.length > 1 ? "messages" : "message"}</div>
        ${bodies}
        ${drafts}
      </div></div>
    </div>`;
  }

  function renderDock() {
    const triaged = S.threads.length;
    const reworked = S.threads.reduce((n, t) => n + t.emails.filter(e => e.is_reworked).length, 0);
    const drafts = S.threads.reduce((n, t) => n + (t.drafts || []).length, 0);
    return `<div class="dock">
      <div class="dock-head">
        <div class="h-av">${ic("sparkle")}</div>
        <div class="h-mid"><b><span class="live"></span> Hermes</b><span>operating your inbox · synced ${S.lastSync ? timeShort(S.lastSync) : "—"}</span></div>
      </div>
      <div class="dock-stats">
        <div class="ds-item"><b>${triaged}</b><span>triaged</span></div>
        <div class="ds-item"><b>${reworked}</b><span>cleaned</span></div>
        <div class="ds-item"><b>${drafts}</b><span>drafts</span></div>
        <div class="ds-tg">${ic("plane")} Telegram ${S.tgChat ? "on" : "off"}</div>
      </div>
      <div class="dock-chat"><iframe id="aim-hermes-frame" title="Hermes chat"></iframe></div>
    </div>`;
  }

  // ─── Events ────────────────────────────────────────────────────────────────
  function attachEvents() {
    document.querySelectorAll(".aimail [data-view]").forEach(b => b.onclick = () => { S.view = b.dataset.view; render(); });
    document.getElementById("aim-settings")?.addEventListener("click", openSettings);
    document.getElementById("aim-add-acct")?.addEventListener("click", openSettings);
    document.getElementById("aim-run")?.addEventListener("click", syncInbox);
    document.getElementById("aim-tg-thread")?.addEventListener("click", async () => {
      try { const r = await apiPost("/api/email/telegram/summary", { account: S.activeAccount?.email || "" }); toast(r.ok ? "Sent to Telegram ✓" : ("Telegram: " + (r.error || "failed"))); } catch (e) { toast("Telegram: " + e.message); }
    });

    const list = document.querySelector(".aimail .list-scroll");
    if (list) list.addEventListener("click", e => { const r = e.target.closest("[data-thread]"); if (r) selectThread(r.dataset.thread); });

    const read = document.querySelector(".aimail .read-scroll");
    if (read) read.addEventListener("click", async e => {
      const orig = e.target.closest("[data-orig]");
      if (orig) return toggleOriginal(orig.dataset.orig);
      const send = e.target.closest("[data-send-draft]");
      if (send) { const d = findDraft(send.dataset.sendDraft); if (d && confirm("Send this reply?")) await sendDraft(d); return; }
      const del = e.target.closest("[data-del-draft]");
      if (del) { await apiPost("/api/email/mgmt/delete-draft", { draft_id: del.dataset.delDraft }); await loadServerThreads(); render(); return; }
      const edit = e.target.closest("[data-edit-draft]");
      if (edit) { discussInChat(); return; }
    });
  }

  function selectThread(id) {
    S.activeThread = id;
    // partial update — keep the iframe alive, refresh list highlight + reading only
    document.querySelectorAll(".aimail .row").forEach(el => el.classList.toggle("sel", el.dataset.thread === id));
    const reading = document.querySelector(".aimail .reading");
    if (reading) { const tmp = document.createElement("div"); tmp.innerHTML = renderReading(); reading.replaceWith(tmp.firstElementChild); }
    // re-wire reading events
    const read = document.querySelector(".aimail .read-scroll");
    if (read) read.addEventListener("click", async e => {
      const orig = e.target.closest("[data-orig]"); if (orig) return toggleOriginal(orig.dataset.orig);
      const send = e.target.closest("[data-send-draft]"); if (send) { const d = findDraft(send.dataset.sendDraft); if (d && confirm("Send this reply?")) await sendDraft(d); return; }
      const del = e.target.closest("[data-del-draft]"); if (del) { await apiPost("/api/email/mgmt/delete-draft", { draft_id: del.dataset.delDraft }); await loadServerThreads(); render(); return; }
      const edit = e.target.closest("[data-edit-draft]"); if (edit) { discussInChat(); return; }
    });
    document.getElementById("aim-tg-thread")?.addEventListener("click", async () => {
      try { const r = await apiPost("/api/email/telegram/summary", { account: S.activeAccount?.email || "" }); toast(r.ok ? "Sent to Telegram ✓" : "Telegram failed"); } catch (e) { toast("Telegram: " + e.message); }
    });
  }

  S.origCache = {};
  async function toggleOriginal(emailId) {
    S.origOpen[emailId] = !S.origOpen[emailId];
    if (S.origOpen[emailId] && !S.origCache[emailId]) {
      try { const o = await apiGet(`/api/email/original?id=${encodeURIComponent(emailId)}`); S.origCache[emailId] = o.body_text || (o.body_html ? o.body_html.replace(/<[^>]+>/g, " ") : "(no content)"); } catch { S.origCache[emailId] = "(could not load original)"; }
    }
    // refresh reading only
    const reading = document.querySelector(".aimail .reading");
    if (reading) { const tmp = document.createElement("div"); tmp.innerHTML = renderReading(); reading.replaceWith(tmp.firstElementChild); attachReadingEvents(); }
  }
  function attachReadingEvents() {
    const read = document.querySelector(".aimail .read-scroll");
    if (read) read.addEventListener("click", async e => {
      const orig = e.target.closest("[data-orig]"); if (orig) return toggleOriginal(orig.dataset.orig);
      const send = e.target.closest("[data-send-draft]"); if (send) { const d = findDraft(send.dataset.sendDraft); if (d && confirm("Send this reply?")) await sendDraft(d); return; }
      const del = e.target.closest("[data-del-draft]"); if (del) { await apiPost("/api/email/mgmt/delete-draft", { draft_id: del.dataset.delDraft }); await loadServerThreads(); render(); return; }
      const edit = e.target.closest("[data-edit-draft]"); if (edit) discussInChat();
    });
  }

  function findDraft(id) { for (const t of S.threads) { const d = (t.drafts || []).find(x => x.draft_id === id); if (d) return d; } return null; }
  async function sendDraft(d) {
    try {
      const ta = document.querySelector(`textarea[data-draft="${d.draft_id}"]`);
      const body = ta ? ta.value : d.body;
      await apiPost("/api/email/send", { account_email: S.activeAccount.email, to: d.to_addr || "", subject: d.subject || "", body });
      await apiPost("/api/email/mgmt/delete-draft", { draft_id: d.draft_id });
      toast("Sent ✓"); await syncInbox();
    } catch (e) { toast("Send failed: " + e.message); }
  }
  function discussInChat() {
    const t = S.threads.find(x => x.thread_id === S.activeThread);
    const frame = document.getElementById("aim-hermes-frame");
    if (!t || !frame) return;
    try {
      const doc = frame.contentDocument;
      const input = doc.getElementById("msg") || doc.querySelector("textarea");
      if (!input) return toast("Chat loading — try again in a moment");
      input.value = `Help me refine the reply for the thread "${t.name}".`;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    } catch { toast("Could not reach the chat"); }
  }

  // ─── Embedded real Hermes chat (dock body) ──────────────────────────────────
  async function ensureEmailSession() {
    if (S.emailSessionId) return S.emailSessionId;
    const stored = localStorage.getItem("hermes_email_session");
    if (stored) { S.emailSessionId = stored; return stored; }
    const r = await apiPost("/api/session/new", { profile: S.profile });
    const sid = r.session_id || r.session?.session_id || r.id;
    S.emailSessionId = sid; if (sid) localStorage.setItem("hermes_email_session", sid);
    return sid;
  }
  async function initHermesChat() {
    const frame = document.getElementById("aim-hermes-frame");
    if (!frame || frame.dataset.loaded === "1") return;
    try {
      const sid = await ensureEmailSession();
      if (!sid) return;
      frame.dataset.loaded = "1";
      frame.src = apiUrl("session/" + encodeURIComponent(sid));
      frame.addEventListener("load", () => {
        try {
          const doc = frame.contentDocument; if (!doc) return;
          const st = doc.createElement("style");
          st.textContent = `nav.rail,aside.sidebar,.app-titlebar,.mobile-nav,#mobileOverlay,.rail,.titlebar{display:none!important;}.layout{grid-template-columns:1fr!important;display:block!important;}main.main,.main{width:100%!important;margin:0!important;}html,body{overflow:hidden!important;}`;
          doc.head.appendChild(st);
        } catch {}
      }, { once: true });
    } catch {}
  }

  // ─── Data loading ───────────────────────────────────────────────────────────
  async function loadServerThreads() {
    const res = await apiGet(`/api/email/threads?account=${encodeURIComponent(S.activeAccount.email)}`);
    S.threads = (res.threads || []).map(t => ({
      thread_id: t.thread_id, name: t.title || "(no subject)", position: t.position,
      last_ts: t.last_ts || 0, participants: t.participants || [], emails: t.emails || [], drafts: t.drafts || [],
      preview: (t.emails?.[t.emails.length - 1]?.body || "").slice(0, 140).replace(/\n/g, " "),
    }));
  }
  async function loadInbox() {
    if (!S.activeAccount) { render(); return; }
    S.loading = true; render();
    try {
      await apiPost("/api/email/mgmt/preprocess", { account: S.activeAccount.email }).catch(() => {});
      await loadServerThreads();
      S.loading = false; render();
      if (S.threads.length === 0) await syncInbox();
    } catch (e) { console.error(e); S.threads = []; S.loading = false; render(); }
  }
  async function syncInbox() {
    if (!S.activeAccount) return;
    S.loading = !S.threads.length; render();
    try {
      const res = await apiPost("/api/email/sync", { account_email: S.activeAccount.email, limit: 300 });
      await apiPost("/api/email/mgmt/preprocess", { account: S.activeAccount.email }).catch(() => {});
      await loadServerThreads();
      S.lastSync = res.last_sync || (Date.now() / 1000);
      const n = res.sync?.new || 0;
      toast(n > 0 ? `Synced ${n} new` : (res.sync?.error ? "Sync error: " + res.sync.error : "Up to date"));
    } catch (e) { toast("Sync failed: " + e.message); }
    finally { S.loading = false; render(); }
  }

  function toast(msg) { const n = document.createElement("div"); n.className = "ep3-toast"; n.textContent = msg; document.body.appendChild(n); setTimeout(() => n.remove(), 3800); }

  // ─── Settings modal (accounts, profile, import, Telegram, autopilot) ─────────
  function openSettings() {
    const html = `
      <div class="ep3-modal-bg" id="aim-modal-bg">
        <div class="ep3-modal">
          <div class="ep3-modal-head"><span>Email Settings</span><button class="ep3-btn ep3-btn-icon" id="aim-modal-x">✕</button></div>
          <div class="ep3-modal-body">
            <label class="ep3-lbl">Agent profile</label>
            <select class="ep3-input" id="aim-profile"></select>
            <label class="ep3-lbl">Emails to import per folder</label>
            <input class="ep3-input" id="aim-import" type="number" min="10" max="1000" value="${S.importCount}" />
            <label class="ep3-lbl">Telegram bot token</label>
            <input class="ep3-input" id="aim-tgtoken" type="password" placeholder="123456:ABC-..." value="${esc(S.tgToken)}" />
            <label class="ep3-lbl">Telegram chat ID</label>
            <div class="ep3-row"><input class="ep3-input" id="aim-tgchat" placeholder="123456789" value="${esc(S.tgChat)}" /><button class="ep3-btn ep3-btn-sm" id="aim-tgtest">Test</button></div>
            <label class="ep3-lbl">Automation</label>
            <button class="ep3-btn ep3-btn-primary" id="aim-cron">⏰ Enable 10am &amp; 10pm autopilot</button>
            <div class="ep3-accounts-list">${S.accounts.map((a, i) => `<div class="ep3-acct-row"><div><strong>${esc(a.name || a.email)}</strong><br><small>${esc(a.email)}</small></div><button class="ep3-btn ep3-btn-danger ep3-btn-sm" data-rm="${i}">Remove</button></div>`).join("")}</div>
            <div class="ep3-add-form"><h4>Add Account</h4>
              <input class="ep3-input" id="f-name" placeholder="Display Name" />
              <input class="ep3-input" id="f-email" placeholder="Email" type="email" />
              <input class="ep3-input" id="f-pass" placeholder="Password" type="password" />
              <div class="ep3-row"><input class="ep3-input" id="f-imap" placeholder="IMAP host" /><input class="ep3-input ep3-input-sm" id="f-imap-p" value="993" /></div>
              <div class="ep3-row"><input class="ep3-input" id="f-smtp" placeholder="SMTP host" /><input class="ep3-input ep3-input-sm" id="f-smtp-p" value="587" /></div>
              <button class="ep3-btn ep3-btn-primary" id="aim-save-acct">Save Account</button>
            </div>
          </div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML("beforeend", html);
    populateProfiles();
    const close = () => document.getElementById("aim-modal-bg")?.remove();
    document.getElementById("aim-modal-x").onclick = close;
    document.getElementById("aim-modal-bg").onclick = e => { if (e.target.id === "aim-modal-bg") close(); };
    const save = async () => {
      S.profile = document.getElementById("aim-profile")?.value || S.profile;
      S.importCount = parseInt(document.getElementById("aim-import")?.value) || 60;
      S.tgToken = document.getElementById("aim-tgtoken")?.value.trim() || "";
      S.tgChat = document.getElementById("aim-tgchat")?.value.trim() || "";
      await apiPost("/api/email/settings", { save: true, settings: { profile: S.profile, import_count: S.importCount, telegram_bot_token: S.tgToken, telegram_chat_id: S.tgChat } }).catch(() => {});
    };
    ["aim-profile", "aim-import", "aim-tgtoken", "aim-tgchat"].forEach(id => { const el = document.getElementById(id); if (el) el.onchange = save; });
    document.getElementById("aim-tgtest").onclick = async () => { await save(); const r = await apiPost("/api/email/telegram/test", {}).catch(e => ({ error: e.message })); toast(r.ok ? "Telegram test sent ✓" : ("Telegram: " + (r.error || "failed"))); };
    document.getElementById("aim-cron").onclick = async () => {
      const acct = S.activeAccount?.email || "contact@ramzi.digital";
      const prompt = `Run your email-manager autonomous workflow for ${acct}: sync, preprocess, triage (reorder threads urgent→fyi), rework noisy newsletters into one-liners, draft replies for important emails (DO NOT send), then email_telegram_summary. Never send without my approval.`;
      try { const r = await apiPost("/api/crons/create", { name: "Email autopilot (10am & 10pm)", schedule: "0 10,22 * * *", prompt, profile: S.profile, deliver: "local", toast_notifications: true }); toast((r?.id || r?.job?.id) ? "Autopilot scheduled ✓" : "Created — see Tasks panel"); } catch (e) { toast("Cron: " + e.message); }
    };
    document.querySelectorAll("#aim-modal-bg [data-rm]").forEach(b => b.onclick = async () => { S.accounts.splice(parseInt(b.dataset.rm), 1); await apiPost("/api/email/accounts", { accounts: S.accounts }); close(); render(); });
    document.getElementById("aim-save-acct").onclick = async () => {
      const a = { name: document.getElementById("f-name").value.trim(), email: document.getElementById("f-email").value.trim(), password: document.getElementById("f-pass").value, imap_host: document.getElementById("f-imap").value.trim(), imap_port: parseInt(document.getElementById("f-imap-p").value) || 993, smtp_host: document.getElementById("f-smtp").value.trim(), smtp_port: parseInt(document.getElementById("f-smtp-p").value) || 587 };
      if (!a.email || !a.password || !a.imap_host || !a.smtp_host) return toast("Fill all fields");
      S.accounts.push(a); await apiPost("/api/email/accounts", { accounts: S.accounts }); close(); if (!S.activeAccount) S.activeAccount = a; loadInbox();
    };
  }
  async function populateProfiles() {
    const sel = document.getElementById("aim-profile"); if (!sel) return;
    let profiles = ["collab-manager", "default"];
    try { const res = await apiGet("/api/profiles"); if (Array.isArray(res?.profiles)) profiles = res.profiles.map(p => p.name || p); else if (Array.isArray(res)) profiles = res.map(p => p.name || p); } catch {}
    if (!profiles.includes(S.profile)) profiles.unshift(S.profile);
    sel.innerHTML = profiles.map(p => `<option value="${esc(p)}" ${p === S.profile ? "selected" : ""}>${esc(p)}</option>`).join("");
  }

  // ─── Init ──────────────────────────────────────────────────────────────────
  async function init() {
    // inject stylesheet once
    if (!document.getElementById("aimail-css")) {
      const l = document.createElement("link"); l.id = "aimail-css"; l.rel = "stylesheet"; l.href = apiUrl("static/aimail.css") + "?v=" + Date.now();
      document.head.appendChild(l);
    }
    try { const res = await apiGet("/api/email/accounts"); S.accounts = res.accounts || []; if (S.accounts.length) S.activeAccount = S.accounts[0]; } catch { S.accounts = []; }
    try { const st = await apiPost("/api/email/settings", {}).catch(() => null); if (st?.profile) S.profile = st.profile; if (st?.import_count) S.importCount = st.import_count; if (st?.telegram_bot_token) S.tgToken = st.telegram_bot_token; if (st?.telegram_chat_id) S.tgChat = st.telegram_chat_id; } catch {}
    render();
    if (S.activeAccount) loadInbox();
  }

  window.EmailPanel = { open: init, refresh: syncInbox };
})();

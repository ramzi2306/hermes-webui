/**
 * Custom Extension Loader for Hermes WebUI
 * Injects UI elements for all custom features WITHOUT modifying base files.
 * Add new features by extending CUSTOM_EXTENSIONS below.
 *
 * Base file changes required:
 *   - index.html: <script src="static/custom-loader.js" defer> (1 line)
 *   - panels.js:  'email' in panel arrays (2 lines)
 */

(function () {
  "use strict";

  // ── Registry of all custom extensions ───────────────────────────────────
  const CUSTOM_EXTENSIONS = [
    {
      id: "email",
      label: "Mail",
      tooltip: "AI Mail Inbox",
      // SVG envelope icon
      icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
      iconSm: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
      panelContent: `<div id="email-panel" style="height:100%;overflow:hidden;"></div>`,
      onActivate: () => {
        if (window.EmailPanel) window.EmailPanel.open();
      },
      scripts: ["static/email-panel.js"],
    },
    // Add more extensions here in future:
    // { id: "crm", label: "CRM", ... }
  ];

  // ── Inject CSS ────────────────────────────────────────────────────────────
  function injectCSS(css) {
    const style = document.createElement("style");
    style.textContent = css;
    style.setAttribute("data-custom-loader", "true");
    document.head.appendChild(style);
  }

  // ── Inject script ─────────────────────────────────────────────────────────
  function injectScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src^="${src.split('?')[0]}"]`)) {
        resolve(); return;
      }
      const s = document.createElement("script");
      s.src = src + "?v=" + Date.now();
      s.defer = true;
      s.onload = resolve;
      s.onerror = reject;
      document.body.appendChild(s);
    });
  }

  // ── Add nav button (rail) ─────────────────────────────────────────────────
  function addRailButton(ext) {
    const rail = document.querySelector("nav.rail");
    if (!rail) return;
    if (rail.querySelector(`[data-panel="${ext.id}"]`)) return;

    // Insert before the rail-spacer
    const spacer = rail.querySelector(".rail-spacer");
    const btn = document.createElement("button");
    btn.className = "rail-btn nav-tab has-tooltip";
    btn.dataset.panel = ext.id;
    btn.setAttribute("data-tooltip", ext.tooltip || ext.label);
    btn.setAttribute("aria-label", ext.label);
    btn.innerHTML = ext.icon;
    btn.addEventListener("click", () => {
      if (typeof switchPanel === "function") switchPanel(ext.id, { fromRailClick: true });
    });

    if (spacer) rail.insertBefore(btn, spacer);
    else rail.appendChild(btn);
  }

  // ── Add nav button (mobile sidebar) ──────────────────────────────────────
  function addSidebarNavButton(ext) {
    const sidebarNav = document.querySelector(".sidebar-nav");
    if (!sidebarNav) return;
    if (sidebarNav.querySelector(`[data-panel="${ext.id}"]`)) return;

    const btn = document.createElement("button");
    btn.className = "nav-tab has-tooltip has-tooltip--bottom";
    btn.dataset.panel = ext.id;
    btn.dataset.label = ext.label;
    btn.setAttribute("data-tooltip", ext.tooltip || ext.label);
    btn.innerHTML = ext.iconSm || ext.icon;
    btn.addEventListener("click", () => {
      if (typeof switchPanel === "function") switchPanel(ext.id, { fromRailClick: true });
    });

    sidebarNav.appendChild(btn);
  }

  // ── Add full-page panel view (injected into <main>, not sidebar) ─────────
  function addPanelView(ext) {
    const panelId = `custom-panel-${ext.id}`;
    if (document.getElementById(panelId)) return;

    const div = document.createElement("div");
    div.id = panelId;
    div.className = "custom-full-panel";
    div.setAttribute("data-custom-panel", ext.id);
    div.style.cssText = "display:none;position:absolute;inset:0;z-index:10;background:var(--bg,#fff);overflow:hidden;";
    div.innerHTML = ext.panelContent || "";

    // Inject into <main class="main"> so it overlays the chat
    const mainEl = document.querySelector("main.main") || document.querySelector("main") || document.body;
    mainEl.style.position = "relative";
    mainEl.appendChild(div);
  }

  // ── Show/hide full-page panels ────────────────────────────────────────────
  function syncFullPanels(activePanelId) {
    document.querySelectorAll(".custom-full-panel").forEach(el => {
      const id = el.getAttribute("data-custom-panel");
      el.style.display = id === activePanelId ? "block" : "none";
    });
  }

  // ── Patch switchPanel to trigger onActivate ───────────────────────────────
  function patchSwitchPanel() {
    const original = window.switchPanel;
    if (!original || window.__customLoaderPatched) return;
    window.__customLoaderPatched = true;

    window.switchPanel = async function (name, opts) {
      const result = await original.call(this, name, opts);
      // Show/hide full-page custom panels
      const isCustom = CUSTOM_EXTENSIONS.find(e => e.id === name);
      syncFullPanels(isCustom ? name : null);
      const ext = CUSTOM_EXTENSIONS.find(e => e.id === name);
      if (ext && ext.onActivate) {
        setTimeout(() => ext.onActivate(), 50);
      }
      return result;
    };
  }

  // ── Main init ─────────────────────────────────────────────────────────────
  async function init() {
    for (const ext of CUSTOM_EXTENSIONS) {
      // Inject nav buttons
      addRailButton(ext);
      addSidebarNavButton(ext);

      // Inject panel view
      addPanelView(ext);

      // Load extension scripts
      if (ext.scripts) {
        for (const src of ext.scripts) {
          try { await injectScript(src); } catch (e) { console.warn("Custom script load failed:", src, e); }
        }
      }
    }

    // Patch switchPanel after scripts loaded
    patchSwitchPanel();
  }

  // Wait for DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    // switchPanel might not exist yet — wait a tick
    setTimeout(init, 100);
  }
})();

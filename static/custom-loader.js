/**
 * Custom Extension Loader — fixed full-screen overlay approach
 * Covers entire viewport (rail + sidebar + main) when active
 */
(function () {
  "use strict";

  const CUSTOM_EXTENSIONS = [
    {
      id: "email",
      label: "Mail",
      tooltip: "AI Mail Inbox",
      icon: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
      iconSm: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>`,
      panelContent: `<div id="email-panel" style="height:100%;overflow:hidden;"></div>`,
      onActivate: () => { if (window.EmailPanel) window.EmailPanel.open(); },
      scripts: ["static/email-panel.js"],
    },
  ];

  function addRailButton(ext) {
    const rail = document.querySelector("nav.rail");
    if (!rail || rail.querySelector(`[data-custom-ext="${ext.id}"]`)) return;
    const spacer = rail.querySelector(".rail-spacer");
    const btn = document.createElement("button");
    btn.className = "rail-btn nav-tab has-tooltip";
    btn.dataset.panel = ext.id;
    btn.dataset.customExt = ext.id;
    btn.setAttribute("data-tooltip", ext.tooltip || ext.label);
    btn.setAttribute("aria-label", ext.label);
    btn.innerHTML = ext.icon;
    btn.addEventListener("click", () => toggleOverlay(ext.id));
    if (spacer) rail.insertBefore(btn, spacer);
    else rail.appendChild(btn);
  }

  function addSidebarNavButton(ext) {
    const nav = document.querySelector(".sidebar-nav");
    if (!nav || nav.querySelector(`[data-custom-ext="${ext.id}"]`)) return;
    const btn = document.createElement("button");
    btn.className = "nav-tab has-tooltip has-tooltip--bottom";
    btn.dataset.panel = ext.id;
    btn.dataset.customExt = ext.id;
    btn.dataset.label = ext.label;
    btn.setAttribute("data-tooltip", ext.tooltip || ext.label);
    btn.innerHTML = ext.iconSm || ext.icon;
    btn.addEventListener("click", () => toggleOverlay(ext.id));
    nav.appendChild(btn);
  }

  function createOverlay(ext) {
    if (document.getElementById(`overlay-${ext.id}`)) return;

    // Overlay covers everything EXCEPT the rail (rail stays visible on the left)
    const overlay = document.createElement("div");
    overlay.id = `overlay-${ext.id}`;
    overlay.setAttribute("data-overlay", ext.id);
    overlay.style.cssText = `
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      z-index: 9000;
      background: var(--bg, #18181b);
      flex-direction: column;
      overflow: hidden;
    `;

    // Topbar
    const topbar = document.createElement("div");
    topbar.style.cssText = `
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 16px;
      height: 46px;
      border-bottom: 1px solid var(--border, #333);
      background: var(--sidebar, #111);
      flex-shrink: 0;
    `;

    const backBtn = document.createElement("button");
    backBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg> Chat`;
    backBtn.style.cssText = `
      display: flex; align-items: center; gap: 6px;
      background: none; border: none; cursor: pointer;
      color: var(--muted, #888); padding: 6px 10px;
      border-radius: 6px; font-size: 13px; font-weight: 500;
    `;
    backBtn.onmouseenter = () => backBtn.style.color = "var(--text, #fff)";
    backBtn.onmouseleave = () => backBtn.style.color = "var(--muted, #888)";
    backBtn.addEventListener("click", () => closeOverlay(ext.id));

    const title = document.createElement("span");
    title.textContent = "✉ " + ext.label;
    title.style.cssText = "font-weight: 700; font-size: 15px; color: var(--text, #fff); flex: 1;";

    topbar.appendChild(backBtn);
    topbar.appendChild(title);

    const body = document.createElement("div");
    body.style.cssText = "flex: 1; overflow: hidden; display: flex; flex-direction: column;";
    body.innerHTML = ext.panelContent || "";

    overlay.appendChild(topbar);
    overlay.appendChild(body);
    document.body.appendChild(overlay);
  }

  function toggleOverlay(id) {
    const overlay = document.getElementById(`overlay-${id}`);
    if (!overlay) return;
    const isOpen = overlay.style.display !== "none";
    isOpen ? closeOverlay(id) : openOverlay(id);
  }

  let _savedActive = [];  // built-in buttons that were active before opening overlay

  function openOverlay(id) {
    document.querySelectorAll("[data-overlay]").forEach(el => el.style.display = "none");
    const overlay = document.getElementById(`overlay-${id}`);
    if (!overlay) return;
    // Keep the rail visible: offset the overlay's left edge by the rail width
    const rail = document.querySelector("nav.rail");
    let railW = 0;
    if (rail) {
      const r = rail.getBoundingClientRect();
      if (r.width > 0 && r.width < 120 && r.left < 10) railW = r.width;
    }
    overlay.style.left = railW ? railW + "px" : "0";
    overlay.style.display = "flex";
    // Remove 'active' from every built-in nav button, remember which were active
    _savedActive = [];
    document.querySelectorAll('.nav-tab.active, .rail-btn.active').forEach(b => {
      if (!b.hasAttribute("data-custom-ext")) { _savedActive.push(b); b.classList.remove("active"); }
    });
    document.querySelectorAll(`[data-custom-ext="${id}"]`).forEach(b => b.classList.add("active"));
    const ext = CUSTOM_EXTENSIONS.find(e => e.id === id);
    if (ext && ext.onActivate) setTimeout(() => ext.onActivate(), 60);
  }

  function closeOverlay(id) {
    const overlay = document.getElementById(`overlay-${id}`);
    if (overlay) overlay.style.display = "none";
    document.querySelectorAll(`[data-custom-ext="${id}"]`).forEach(b => b.classList.remove("active"));
    // Restore the built-in panel's highlight
    _savedActive.forEach(b => b.classList.add("active"));
    _savedActive = [];
  }

  function injectScript(src) {
    return new Promise((resolve, reject) => {
      const base = src.split("?")[0];
      if (document.querySelector(`script[src^="${base}"]`)) { resolve(); return; }
      const s = document.createElement("script");
      s.src = src + "?v=" + Date.now();
      s.onload = resolve;
      s.onerror = reject;
      document.body.appendChild(s);
    });
  }

  async function init() {
    for (const ext of CUSTOM_EXTENSIONS) {
      addRailButton(ext);
      addSidebarNavButton(ext);
      createOverlay(ext);
      if (ext.scripts) {
        for (const src of ext.scripts) {
          try { await injectScript(src); } catch (e) { console.warn("Custom script failed:", src); }
        }
      }
    }
    patchSwitchPanel();
  }

  // When the user clicks any BUILT-IN panel, close all custom overlays so
  // the email view behaves like a real tab (not a stuck overlay).
  function patchSwitchPanel() {
    if (window.__customLoaderPatched) return;
    const original = window.switchPanel;
    if (typeof original !== "function") { setTimeout(patchSwitchPanel, 200); return; }
    window.__customLoaderPatched = true;
    window.switchPanel = function (name, opts) {
      const isCustom = CUSTOM_EXTENSIONS.some(e => e.id === name);
      if (!isCustom) {
        // leaving for a built-in panel → hide every custom overlay
        document.querySelectorAll("[data-overlay]").forEach(el => el.style.display = "none");
        document.querySelectorAll("[data-custom-ext]").forEach(b => b.classList.remove("active"));
        _savedActive = [];  // built-in switchPanel will set its own active
      }
      return original.apply(this, arguments);
    };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else setTimeout(init, 150);
})();

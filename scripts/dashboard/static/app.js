/* Atlas Mission Control — vanilla JS control plane.
 * All data comes from the local Atlas API; all actions execute real Atlas
 * CLIs server-side. No fabricated values anywhere in this file. */
"use strict";

/* ── tiny helpers ─────────────────────────────────────────────── */
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function fmtBytes(n) {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtNum(n) { return n == null ? "—" : Number(n).toLocaleString("en-US"); }

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined,
      { year: "numeric", month: "short", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return String(iso); }
}

function pill(text, cls, pulse) {
  const p = cls && cls.includes("running") || cls === "info" && pulse ? " pill-pulse" : "";
  return `<span class="pill ${cls || "muted"}${p}">${esc(text ?? "—")}</span>`;
}

function statusPill(s) {
  const map = {
    succeeded: "ok", final: "ok", READY_FOR_RELEASE: "ok", RELEASED: "ok",
    approved: "ok", READY: "ok", completed: "ok",
    failed: "err", BLOCKED: "err", RELEASE_REJECTED: "err",
    rejected: "err", timeout: "err", error: "err",
    CANCELLED: "muted", cancelled: "muted", missing: "muted", skipped: "muted",
    interrupted: "warn", needs_attention: "warn", CONDITIONAL: "warn",
    WAITING_HUMAN_APPROVAL: "warn", pending: "warn",
    running: "running info", queued: "info", release_candidate: "info",
    dry_run: "muted", live: "ok",
  };
  const key = String(s ?? "—");
  const cls = map[s] || (s === "running" ? "running info" : "info");
  return pill(key, cls, s === "running");
}

function emptyState(title, hint, glyph) {
  return `<div class="empty"><div class="glyph">${glyph || "◇"}</div>
    <b>${esc(title)}</b><span>${esc(hint)}</span></div>`;
}

function skeletonCards(n = 4) {
  return `<div class="grid cols-4">${Array(n).fill('<div class="skel card"></div>').join("")}</div>
    <div class="skel line"></div><div class="skel line"></div><div class="skel line"></div>`;
}

/* ── API + token ──────────────────────────────────────────────── */
const TOKEN_KEY = "atlas_dashboard_token";
const getToken = () => localStorage.getItem(TOKEN_KEY) || "";
const setToken = t => t ? localStorage.setItem(TOKEN_KEY, t)
                        : localStorage.removeItem(TOKEN_KEY);

function showAuthBar(note) {
  $("#authbar").hidden = false;
  if (note) $("#auth-note").textContent = note;
  $("#auth-input").focus();
}
const hideAuthBar = () => { $("#authbar").hidden = true; };

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const tok = getToken();
  if (tok) headers["Authorization"] = `Bearer ${tok}`;
  let res;
  try { res = await fetch(path, { ...opts, headers }); }
  catch (e) { setConn(false); throw new Error(`network: ${e.message}`); }
  setConn(res.ok);
  if (res.status === 401) {
    setToken("");
    updateTokenChip();
    showAuthBar("previous token rejected — paste a valid ATLAS_DASHBOARD_TOKEN");
    throw new Error("401 unauthorized");
  }
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body.error) detail = `${body.error}: ${body.detail || ""}`;
    } catch { /* non-JSON */ }
    throw new Error(detail);
  }
  const ct = res.headers.get("Content-Type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

function setConn(ok) {
  $("#conn-dot").className = `dot ${ok === false ? "dot-bad" : "dot-ok"}`;
  $("#health-text").textContent = ok === false ? "api error" : "connected";
}

function updateTokenChip() {
  $("#token-chip").style.display = getToken() ? "" : "none";
}

/* ── toasts ───────────────────────────────────────────────────── */
function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = `toast ${cls}`;
  el.innerHTML = msg;
  $("#toast-holder").appendChild(el);
  setTimeout(() => el.remove(), 6500);
}

/* ── action catalog & modal ───────────────────────────────────── */
let CATALOG = {};
let CATALOG_LIST = [];

async function loadCatalog(force = false) {
  if (CATALOG_LIST.length && !force) return;
  const d = await api("/api/catalog");
  CATALOG_LIST = d.actions;
  CATALOG = Object.fromEntries(d.actions.map(a => [a.id, a]));
}

function actionBtn(actionId, label, presets = {}, extraClass = "") {
  const a = CATALOG[actionId];
  if (!a) return `<button class="btn btn-mini" disabled title="unknown action">?</button>`;
  const why = a.disabled_reason ? esc(a.disabled_reason) : "";
  return `<button class="btn btn-mini ${extraClass}" data-action="${esc(actionId)}"
    data-presets='${esc(JSON.stringify(presets))}'
    ${a.enabled ? "" : `disabled title="${why}"`}>${esc(label)}</button>`;
}

/* single delegated listener — survives any re-render */
document.addEventListener("click", ev => {
  const btn = ev.target.closest("button[data-action]");
  if (!btn || btn.disabled) return;
  let presets = {};
  try { presets = JSON.parse(btn.getAttribute("data-presets") || "{}"); }
  catch { presets = {}; }
  openActionModal(btn.getAttribute("data-action"), presets);
});

function fieldHtml(spec, value) {
  const name = esc(spec.name);
  const help = spec.help ? `<span class="muted small">${esc(spec.help)}</span>` : "";
  const v = value != null ? value : (spec.default != null ? spec.default : "");
  const id = `f-${name}`;
  if (spec.type === "bool") {
    return `<div class="field check-row">
      <input type="checkbox" id="${id}" name="${name}" ${v ? "checked" : ""}>
      <label for="${id}">${name}</label> ${help}</div>`;
  }
  if (spec.type === "choice") {
    const opts = (spec.choices || []).map(c =>
      `<option value="${esc(c)}" ${c === v ? "selected" : ""}>${esc(c)}</option>`).join("");
    return `<div class="field"><label for="${id}">${name}</label>
      <select id="${id}" name="${name}">${opts}</select> ${help}</div>`;
  }
  if (spec.type === "multi" || spec.type === "path_list") {
    const ph = spec.type === "multi" ? "repeatable ids, one per line"
      : "repo-relative paths, one per line";
    return `<div class="field"><label for="${id}">${name}</label>
      <textarea id="${id}" name="${name}" placeholder="${ph}">${esc((value || []).join("\n"))}</textarea> ${help}</div>`;
  }
  if (spec.type === "int") {
    const range = spec.minimum != null ? ` (${spec.minimum}–${spec.maximum})` : "";
    return `<div class="field"><label for="${id}">${name}${range}</label>
      <input type="number" id="${id}" name="${name}" value="${esc(v)}"> ${help}</div>`;
  }
  const multiline = ["query", "reason", "comment", "config_json", "changelog"].includes(name);
  if (multiline) {
    return `<div class="field"><label for="${id}">${name}</label>
      <textarea id="${id}" name="${name}">${esc(v)}</textarea> ${help}</div>`;
  }
  return `<div class="field"><label for="${id}">${name}</label>
    <input type="text" id="${id}" name="${name}" value="${esc(v)}"> ${help}</div>`;
}

function openActionModal(actionId, presets = {}) {
  const a = CATALOG[actionId];
  if (!a) return;
  if (!a.enabled) { toast(`Action disabled: ${esc(a.disabled_reason)}`, "err"); return; }

  $("#modal-title").textContent = a.title;
  $("#modal-sub").textContent = a.id;
  const dangerBox = $("#modal-danger");
  if (["destructive", "network", "gpu"].includes(a.danger)) {
    dangerBox.hidden = false;
    dangerBox.innerHTML =
      (a.danger === "destructive" ? "<strong>Destructive operation.</strong> "
        : `<strong>${a.danger.toUpperCase()} operation.</strong> `)
      + `${esc(a.description)}`
      + (a.confirm_phrase
        ? `<br>Type <code>${esc(a.confirm_phrase)}</code> exactly to confirm.` : "");
  } else {
    dangerBox.hidden = true;
    dangerBox.innerHTML = "";
  }
  $("#modal-danger").classList.toggle("danger-note", true);

  const form = $("#modal-form");
  form.innerHTML =
    `<input type="hidden" name="__action" value="${esc(actionId)}"><div class="form-grid">` +
    (a.params || []).map(spec => fieldHtml(spec, presets[spec.name])).join("") +
    (a.danger === "network"
      ? `<div class="field"><label for="f-timeout">timeout_s</label>
         <input type="number" id="f-timeout" name="timeout_s" min="5" max="86400"
           value="${a.timeout_s}"></div>` : "") +
    (a.confirm_phrase
      ? `<div class="field"><label for="f-confirm">confirm (type exactly)</label>
         <input type="text" class="confirm-input" id="f-confirm" name="confirm"
           autocomplete="off" spellcheck="false"></div>` : "") +
    `</div>`;

  $("#modal-error").textContent = "";
  $("#modal-backdrop").hidden = false;
  const first = $(".modal-body input:not([type=hidden]), .modal-body textarea, .modal-body select");
  if (first) first.focus();
}

const closeModal = () => { $("#modal-backdrop").hidden = true; };

function readModalParams() {
  const form = $("#modal-form");
  const actionId = form.elements["__action"].value;
  const a = CATALOG[actionId];
  const params = {};
  for (const spec of a.params || []) {
    const el = form.elements[spec.name];
    if (!el) continue;
    if (spec.type === "bool") { params[spec.name] = el.checked; continue; }
    if (spec.type === "multi" || spec.type === "path_list") {
      params[spec.name] = el.value.split("\n").map(x => x.trim()).filter(Boolean);
      continue;
    }
    if (spec.type === "int") {
      if (el.value !== "") params[spec.name] = Number(el.value);
      continue;
    }
    if (el.value !== "") params[spec.name] = el.value;
  }
  const to = form.elements["timeout_s"];
  if (to && to.value) params.timeout_s = Number(to.value);
  const cf = form.elements["confirm"];
  if (cf && cf.value) params.confirm = cf.value;
  return { actionId, params };
}

async function submitModal(ev) {
  ev.preventDefault();
  const { actionId, params } = readModalParams();
  const btn = $("#modal-submit");
  btn.disabled = true;
  btn.innerHTML = "Running…";
  try {
    const resp = await api(`/api/actions/${encodeURIComponent(actionId)}/run`, {
      method: "POST", body: JSON.stringify(params),
    });
    closeModal();
    toast(`${statusPill("queued")} Job <code>${esc(resp.job.id)}</code> — ${esc(CATALOG[actionId].title)}`, "ok");
    switchTab("jobs");
  } catch (e) {
    $("#modal-error").textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = "Run";
  }
}

/* ── preview drawer ───────────────────────────────────────────── */
let drawerPath = "";

async function previewPath(path, limit = 40) {
  try {
    const d = await api(`/api/preview?path=${encodeURIComponent(path)}&limit=${limit}`);
    drawerPath = path;
    $("#drawer-title").textContent = path;
    let body;
    if (d.is_jsonl && Array.isArray(d.records)) {
      body = d.records.map(r =>
        typeof r === "string" ? r : JSON.stringify(r, null, 1)).join("\n──\n");
    } else {
      body = (d.records || []).join("\n");
    }
    $("#drawer-body").textContent = body || "(empty)";
    $("#drawer-backdrop").hidden = false;
  } catch (e) {
    toast(`Preview failed: ${esc(e.message)}`, "err");
  }
}

async function downloadDrawer() {
  try {
    const text = await api(`/api/preview?path=${encodeURIComponent(drawerPath)}&limit=${500}&offset=0`);
    const payload = typeof text === "string" ? text :
      (text.records || []).map(r => typeof r === "string" ? r : JSON.stringify(r)).join("\n");
    const blob = new Blob([payload], { type: "text/plain" });
    const aEl = document.createElement("a");
    aEl.href = URL.createObjectURL(blob);
    aEl.download = drawerPath.split("/").pop() || "preview.txt";
    aEl.click();
    URL.revokeObjectURL(aEl.href);
  } catch (e) { toast(`Download failed: ${esc(e.message)}`, "err"); }
}

function bindPreviewLinks(rootEl) {
  $$("[data-preview]", rootEl).forEach(el =>
    el.addEventListener("click", () => previewPath(el.getAttribute("data-preview"))));
}

/* ── tabs & shell ─────────────────────────────────────────────── */
const TABS = [
  ["overview",   "Overview",        '<path d="M3 10.5 L10 4 L17 10.5 M5 9 V16 H15 V9"/>'],
  ["guide",      "Guide",           '<path d="M10 3.5 C8 2 5 2 2.5 3 V16 C5 15 8 15 10 16.5 C12 15 15 15 17.5 16 V3 C15 2 12 2 10 3.5 Z M10 3.5 V16.5"/>'],
  ["pipelines",  "Pipelines",       '<circle cx="4.5" cy="10" r="2"/><circle cx="15.5" cy="5" r="2"/><circle cx="15.5" cy="15" r="2"/><path d="M6.3 9 L13.7 5.6 M6.3 11 L13.7 14.4"/>'],
  ["review",     "Review",          '<path d="M3 5 L7 9 L14 2 M3 12 h7 M3 16 h9"/><path d="M13 15 l2 2 l4 -4"/>'],
  ["sources",    "Sources & ETL",   '<ellipse cx="10" cy="4.5" rx="7" ry="2.5"/><path d="M3 4.5 V15.5 C3 17 6 18 10 18 C14 18 17 17 17 15.5 V4.5 M3 10 C3 11.5 6 12.5 10 12.5 C14 12.5 17 11.5 17 10"/>'],
  ["views",      "Training Views",  '<rect x="2.5" y="2.5" width="6" height="6" rx="1.2"/><rect x="11.5" y="2.5" width="6" height="6" rx="1.2"/><rect x="2.5" y="11.5" width="6" height="6" rx="1.2"/><path d="M11.5 14.5 h6 M14.5 11.5 v6"/>'],
  ["releases",   "Releases",        '<path d="M10 2 C13 4.5 14 8 13.5 11 L10 14 L6.5 11 C6 8 7 4.5 10 2 Z"/><circle cx="10" cy="7.5" r="1.4"/><path d="M6.5 11 L4 14.5 L7 13.5 M13.5 11 L16 14.5 L13 13.5 M10 14 V17"/>'],
  ["evaluation", "Evaluation",      '<path d="M3 17 V9 M8 17 V4 M13 17 V7 M18 17 V11"/><path d="M2 17.5 H19"/>'],
  ["readiness",  "Readiness",       '<path d="M10 2 L17 5 V10 C17 14.5 14 17 10 18.5 C6 17 3 14.5 3 10 V5 Z"/><path d="M7 10 L9.2 12.2 L13.5 7.8"/>'],
  ["jobs",       "Jobs",            '<rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M5.5 7.5 L8 10 L5.5 12.5 M9.5 13 H14.5"/>'],
];
const CRUMBS = {
  overview: "system state at a glance · all values from authoritative files",
  guide: "start here · concepts, recipes and safety — written for first-time operators",
  pipelines: "automation FSM · state persisted by StateMachine._persist()",
  review: "dual-mode SFT review · failures never become acceptance",
  sources: "acquisition, download cache and ETL outputs",
  views: "training view packages under metadata/views/",
  releases: "hash-linked release chain · ADR-011 immutability",
  evaluation: "benchmark registry + deterministic QEE runs",
  readiness: "six training gates · fail-closed verdicts",
  jobs: "operator-triggered work · evidence, not truth",
};
let CURRENT_TAB = "overview";
const RENDERERS = {};

const ICONS = {};
for (const [id, , path] of TABS) {
  ICONS[id] = `<svg viewBox="0 0 20 20" width="17" height="17" fill="none"
    stroke="currentColor" stroke-width="1.55" stroke-linecap="round"
    stroke-linejoin="round">${path}</svg>`;
}

function buildSidebar() {
  $("#tabs").innerHTML = TABS.map(([id, label]) =>
    `<button data-tab="${id}" title="${esc(label)}">${ICONS[id]}
       <span class="nav-label">${esc(label)}</span></button>`).join("");
  $$("#tabs button").forEach(b =>
    b.addEventListener("click", () => {
      switchTab(b.dataset.tab);
      closeMobileNav();
    }));
}

function closeMobileNav() {
  $("#sidebar").classList.remove("open");
  $("#sidebar-scrim").hidden = true;
}

function switchTab(tabId) {
  CURRENT_TAB = tabId;
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === tabId));
  $$(".tab-page").forEach(p => { p.hidden = p.id !== `tab-${tabId}`; });
  const label = (TABS.find(t => t[0] === tabId) || [, tabId])[1];
  $("#page-title").textContent = label;
  $("#page-crumb").textContent = CRUMBS[tabId] || "";
  renderTab(tabId).catch(e => {
    $(`#tab-${tabId}`).innerHTML =
      emptyState("Failed to load", e.message, "⚠");
  });
}

async function renderTab(tabId) {
  const root = $(`#tab-${tabId}`);
  root.innerHTML = skeletonCards(4);
  await loadCatalog();
  const fn = RENDERERS[tabId];
  if (!fn) return;
  await fn(root);
}

/* ── Start Here checklist ─────────────────────────────────────── */
const CHECKLIST_KEY = "atlas_start_here_v1";
const checklistState = () => {
  try { return JSON.parse(localStorage.getItem(CHECKLIST_KEY)) || {}; }
  catch { return {}; }
};
function markChecklist(id) {
  const st = checklistState();
  st[id] = true;
  localStorage.setItem(CHECKLIST_KEY, JSON.stringify(st));
}

function startHereCard(hasSuccessfulJob) {
  const st = checklistState();
  const items = [
    { id: "guide",   label: "Read the Guide quick start", run: `switchTab("guide")` },
    { id: "job",     label: "Run your first safe job", run: `openActionModal("cache.stats",{list_entries:false})` },
    { id: "fsm",     label: "Explore the FSM in Pipelines", run: `switchTab("pipelines")` },
    { id: "chain",   label: "Verify release hash chain", run: `openActionModal("release.verify_chain",{})` },
    { id: "palette", label: "Try the ⌘K command palette", run: `openPalette()` },
  ];
  const rows = items.map(it => {
    const done = it.id === "job" ? hasSuccessfulJob : !!st[it.id];
    return `<li class="${done ? "done" : ""}">
      <input type="checkbox" ${done ? "checked disabled" : ""} data-clk="${it.id}"
             aria-label="${esc(it.label)}">
      <button class="linklike" data-clrun="${esc(it.id)}">${esc(it.label)}</button></li>`;
  }).join("");
  const allDone = items.every(it => it.id === "job" ? hasSuccessfulJob : !!st[it.id]);
  return `<div class="card start-here">
    <div class="recipe-head"><span class="recipe-title">🧭 Start here — your first 5 steps</span>
      ${allDone ? pill("completed", "ok") : ""}</div>
    <ul class="checklist">${rows}</ul>
    <div class="muted small">Click any step to jump straight in. This checklist is stored in this browser.</div>
  </div>`;
}

function bindChecklist(root) {
  $$("[data-clrun]", root).forEach(btn =>
    btn.addEventListener("click", () => {
      const id = btn.dataset.clrun;
      markChecklist(id);
      const item = ({
        guide:   () => switchTab("guide"),
        job:     () => openActionModal("cache.stats", { list_entries: false }),
        fsm:     () => switchTab("pipelines"),
        chain:   () => openActionModal("release.verify_chain", {}),
        palette: () => openPalette(),
      })[id];
      if (item) item();
    }));
}

/* ── Overview ─────────────────────────────────────────────────── */
RENDERERS.overview = async (root) => {
  const [ov, jobsD] = await Promise.all([
    api("/api/overview"),
    api("/api/jobs?limit=30").catch(() => ({ jobs: [] })),
  ]);
  const rel = ov.release || {};
  const tr = ov.training_readiness || {};
  const gates = tr.gate_summary || {};
  const stats = (rel.statistics || {}).by_category ||
    (rel.statistics || {}).category_counts || {};
  const statItems = Object.entries(stats)
    .map(([k, v]) => ({ label: k.replace(/^0_?|^category[_ ]?/, "").replace(/_/g, " "),
                        value: Number(v) || 0 }))
    .sort((a, b) => b.value - a.value).slice(0, 8);
  const durations = (jobsD.jobs || [])
    .filter(j => j.duration_ms != null).slice(0, 20)
    .map(j => j.duration_ms / 1000).reverse();
  const reviewQ = ov.review?.queues || {};
  const readyCount = Object.values(gates).filter(v => v === "READY").length;

  root.innerHTML = `
    ${startHereCard((jobsD.jobs || []).some(j => j.status === "succeeded"))}
    <div class="grid cols-4">
      <div class="card kpi-card"><h3>Latest release</h3>
        <div class="kpi">${esc(rel.version || "—")}</div>
        <div>${fmtNum(rel.total_records)} records · ${statusPill(rel.status)}</div>
        <div class="muted small">${esc(fmtTime(rel.created_at))}</div></div>
      <div class="card kpi-card"><h3>Training readiness</h3>
        <div class="kpi">${statusPill(tr.verdict || "unknown")}</div>
        <div class="muted small">${readyCount}/6 gates ready · fail-closed</div></div>
      <div class="card kpi-card"><h3>Pipelines active</h3>
        <div class="kpi">${ov.pipelines?.active ?? 0}<small> / ${ov.pipelines?.total_tracked ?? 0} tracked</small></div>
        <div class="muted small wrap">${esc((ov.pipelines?.active_ids || []).join(", ") || "none active")}</div></div>
      <div class="card kpi-card"><h3>Sources registered</h3>
        <div class="kpi">${fmtNum(ov.sources?.registry_count)}</div>
        <div class="muted small">job durations (s), last 20:</div>
        ${durations.length >= 2 ? svgSparkline(durations) : ""}</div>
    </div>

    <h2 class="section-title">Readiness gates</h2>
    <div class="grid cols-3">
      <div class="card"><h3>Gate mix</h3>${gateRing(gates)}</div>
      <div class="card"><h3>Gates</h3><div class="gate-grid">
        ${Object.entries(gates).map(([g, v]) => `
          <div class="gate-card ${v === "READY" ? "gate-ready" : v === "CONDITIONAL" ? "gate-conditional" : "gate-blocked"}">
            <div class="small muted">${esc(g.replace(/_/g, " "))}</div>
            <div class="verdict">${esc(v)}</div></div>`).join("")}
      </div></div>
      <div class="card"><h3>Review queues</h3>
        <dl class="kv">${Object.entries(reviewQ).map(([k, v]) =>
          `<dt>${esc(k)}</dt><dd>${v.exists ? fmtNum(v.records) : pill("missing", "muted")}</dd>`).join("")}</dl>
      </div>
    </div>

    <h2 class="section-title">Records by category · ${esc(rel.version || "")}</h2>
    <div class="card">
      ${statItems.length ? svgHBars(statItems, { aria: "records by category" })
        : emptyState("No category statistics", "latest manifest carries no statistics block")}
    </div>

    <h2 class="section-title">Common operations</h2>
    <div class="card"><div class="action-row">
      ${actionBtn("integrity.self_test", "CLI self-test")}
      ${actionBtn("integrity.architecture", "Architecture validation")}
      ${actionBtn("integrity.readiness", "Recompute readiness")}
      ${actionBtn("acquire.dry_run", "Acquisition dry-run")}
      ${actionBtn("cache.stats", "Cache stats")}
      ${actionBtn("release.verify_chain", "Verify release chain")}
      <button class="btn btn-mini" id="open-palette-2">More… ⌘K</button>
    </div></div>`;

  $("#open-palette-2").addEventListener("click", openPalette);
  bindChecklist(root);
  animateHBars(root);
};

/* ── Guide ────────────────────────────────────────────────────── */
const WELCOME_KEY = "atlas_seen_welcome_v2";

function guideRecipe(title, steps, actionId, presets, extraClass) {
  return `<div class="recipe">
    <div class="recipe-head"><span class="recipe-title">${esc(title)}</span>
      ${actionId ? actionBtn(actionId, "Open form ▸", presets || {}, extraClass || "") : ""}</div>
    <ol class="recipe-steps">${steps.map(s => `<li>${s}</li>`).join("")}</ol>
  </div>`;
}

RENDERERS.guide = async (root) => {
  root.innerHTML = `
    <div class="card guide-hero">
      <h2>Welcome — start here</h2>
      <p>This dashboard is a <b>remote control for the Atlas pipeline</b>. It contains
      no business logic of its own — every <b>Run</b> button executes the <b>real Atlas
      CLI</b> on the server, and every number you see is read from the real state files.
      If you have ever run <code>python -m scripts.automation_runner …</code> by hand,
      this dashboard does exactly that — just with buttons, logs and guardrails.</p>
    </div>

    <div class="grid cols-3">
      <div class="card"><h3>Quick start (5 minutes)</h3>
        <ol class="guide-ol">
          <li><b>Check where things stand</b> — the cards at the top of
            <i>Overview</i>: latest release, readiness verdict, active pipelines.
            All read-only.</li>
          <li><b>Run your first safe job</b> — click
            <button class="btn btn-mini" data-action="cache.stats"
              data-presets='{"list_entries":false}'>Cache stats</button>
            below. Fill in the modal → click <b>Run</b>. You will land on the
            <i>Jobs</i> tab and can watch the CLI output live.</li>
          <li><b>Read the result</b> — green = exit code 0 (success). Click
            <i>log</i> to see the full command output.</li>
          <li><b>Dry-run anything big first</b> — download, ETL and e2e all have
            dry-run modes. They plan without writing anything.</li>
          <li><b>Read Safety below</b> before touching any red button.</li>
        </ol></div>
      <div class="card"><h3>Key vocabulary</h3>
        <dl class="glossary">
          <dt>Pipeline</dt><dd>one dataset's journey through the FSM until approved/released</dd>
          <dt>FSM / state</dt><dd>11-state machine: INGESTED → … → WAITING_HUMAN_APPROVAL → RELEASED. Skipping gates is impossible</dd>
          <dt>Dry-run</dt><dd>simulation with zero side effects. Always safe</dd>
          <dt>Job</dt><dd>one command you triggered here; persisted as evidence (log + exit code) under metadata/dashboard/</dd>
          <dt>Gate</dt><dd>a mandatory check: review, lineage, provenance, license, quality, evaluation</dd>
          <dt>RC vs Final</dt><dd>Release Candidate → after human approval → Final (bytes unchanged, new manifest)</dd>
          <dt>Staging vs Production view</dt><dd>staging uses ordinary ETL records; production REQUIRES approved curated records</dd>
          <dt>needs_attention</dt><dd>AI reviewer finished with exit 3 — some records need human adjudication. NOT a pass</dd>
        </dl></div>
      <div class="card"><h3>Recommended first recipes</h3>
        ${guideRecipe("Look around with zero risk", [
          `Run <button class="btn btn-mini" data-action="integrity.self_test">CLI self-test</button> — system invariants, read-only`,
          `Open the <b>Jobs</b> tab, click <i>log</i>, read the output`,
          `Try <button class="btn btn-mini" data-action="release.verify_chain">Verify release chain</button> — validates the v1.0 hash chain`,
          `Try <button class="btn btn-mini" data-action="aql.validate" data-presets='{"query":"quality_score &gt;= 8","source":"v0.1"}'>Validate AQL query</button> — play with the query language`],
          null)}
        ${guideRecipe("Download & process one source", [
          `Pick a source in the <i>Sources &amp; ETL</i> tab`,
          `Click <b>download</b> (network) — or <button class="btn btn-mini" data-action="download.dry_run" data-presets='{}'>plan it first</button>`,
          `When done, click <b>etl</b> on the same row`,
          `Check results under <i>ETL outputs</i>`],
          null)}
      </div>
    </div>

    <h2 class="section-title">Full workflow (end-to-end)</h2>
    <div class="grid cols-2">
      <div class="card"><h3>A · Data in → training view</h3>
        ${guideRecipe("Flow A", [
          `<b>download.dry_run</b> → <b>download.execute</b> (needs internet)`,
          `<b>etl.run</b> — extract → normalize → clean`,
          `<b>transform.run</b> — generate the 5 training types`,
          `<b>views.build</b> — pick a version like <code>v0.9-practice1</code>; leave production OFF while learning`,
          `Inspect results in the <i>Training Views</i> tab — real .jsonl files`],
          null)}
      </div>
      <div class="card"><h3>B · Releasing (be careful!)</h3>
        ${guideRecipe("Flow B", [
          `<b>pipeline.run</b> (dry-run first) → watch the FSM advance in Pipelines`,
          `At WAITING_HUMAN_APPROVAL: <b>request approval</b> → <b>approve</b>
           (you are the human approver; type the confirmation phrase)`,
          `<b>pipeline.release</b> — gates enforced by the FSM`,
          `An RC is built → <b>Promote RC → final</b> only when truly certain`,
          `Publishing to HuggingFace needs HF_TOKEN — buttons stay disabled without it`],
          "release.promote", { from_version: "v1.0-RC2", to_version: "", dry_run: true }, "btn-danger")}
      </div>
    </div>

    <h2 class="section-title">Reading the Jobs tab</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Status</th><th>Meaning</th><th>What to do</th></tr></thead>
      <tbody>
        <tr><td>${pill("queued", "info")}</td><td>waiting for a worker slot</td><td>wait a moment</td></tr>
        <tr><td>${pill("running", "running info")}</td><td>the CLI is executing</td><td>click <i>log</i> for live output</td></tr>
        <tr><td>${pill("succeeded", "ok")}</td><td>exit code 0</td><td>safe — inspect the result</td></tr>
        <tr><td>${pill("failed", "err")}</td><td>exit ≠ 0</td><td>read the log; the CLI usually explains why</td></tr>
        <tr><td>${pill("needs_attention", "warn")}</td><td>AI review: records await human adjudication</td><td>open ai_reviews.jsonl and review those records</td></tr>
        <tr><td>${pill("timeout", "err")}</td><td>exceeded its time limit and was killed</td><td>re-run with a larger timeout or split the work</td></tr>
        <tr><td>${pill("interrupted", "warn")}</td><td>server restarted mid-job</td><td>just re-run — operations are idempotent by design</td></tr>
      </tbody></table></div>

    <h2 class="section-title">Safety — read this before red buttons</h2>
    <div class="grid cols-3">
      <div class="card"><h3>Three danger levels</h3>
        <ul class="guide-ul">
          <li>${pill("read", "muted")} &nbsp;read-only — zero risk (self-test, verify, stats)</li>
          <li>${pill("safe_write", "info")} &nbsp;writes new artifacts in approved locations (build views, bundles)</li>
          <li>${pill("destructive", "err")} &nbsp;changes governance state — REQUIRES typing the exact confirmation phrase (approve, deny, cancel, promote, publish…)</li>
        </ul></div>
      <div class="card"><h3>Rules that cannot be broken</h3>
        <ul class="guide-ul">
          <li>raw/, curated/, review_queue/ are NEVER written directly by the dashboard</li>
          <li>VALIDATION → RELEASED is forbidden by the FSM; human approval mandatory</li>
          <li>Frozen release bundles — promotion writes a NEW manifest, same bytes</li>
          <li>A grey disabled button means a credential is missing (e.g. HF_TOKEN) — secret values are never exposed</li>
        </ul></div>
      <div class="card"><h3>Use ⌘K like a pro</h3>
        <ul class="guide-ul">
          <li>Press <kbd>⌘K</kbd>/<kbd>Ctrl+K</kbd> anywhere</li>
          <li>Type an action name e.g. <i>self-test</i>, <i>promote</i>, <i>dry</i></li>
          <li><kbd>↑↓</kbd> select, <kbd>↵</kbd> open form, <kbd>esc</kbd> close</li>
          <li>You can also jump to tabs and pipelines straight from the palette</li>
        </ul>
        <div class="action-row"><button class="btn btn-mini" id="replay-welcome">Replay welcome tour</button></div></div>
    </div>

    <h2 class="section-title">Common problems</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr></thead>
      <tbody>
        <tr><td>Yellow bar asks for a token</td><td>missing/wrong ATLAS_DASHBOARD_TOKEN</td><td><code>cat tmp/dashboard_token.txt</code> on the server, paste, Unlock</td></tr>
        <tr><td>Grey button + tooltip "missing environment"</td><td>credential absent on the server (HF_TOKEN etc.)</td><td>set the env var in the systemd unit and restart the service</td></tr>
        <tr><td>Job failed instantly</td><td>the CLI refused — e.g. pipeline already CANCELLED</td><td>open the log; the JSON "CLI decision" message explains the real verdict</td></tr>
        <tr><td>"action_disabled"</td><td>credential-gated action</td><td>provide the credential first</td></tr>
        <tr><td>A number looks odd?</td><td>everything is read from real state files</td><td>compare directly with files under metadata/ — the dashboard never invents numbers</td></tr>
      </tbody></table></div>`;

  $("#replay-welcome")?.addEventListener("click", () => {
    localStorage.removeItem(WELCOME_KEY);
    maybeShowWelcome();
  });
};

/* ── Welcome tour (first visit) ───────────────────────────────── */
const WELCOME_SLIDES = [
  { t: "Atlas Mission Control", g: "🛰",
    b: `This is the remote control for the <b>Atlas data pipeline</b> — a governed
        data infrastructure platform producing training data for models like atan-v1.
        Every number comes from real state files; every button runs the real Atlas CLI.` },
  { t: "Start with what is safe", g: "🌱",
    b: `The colors tell you: <b>grey/blue</b> = safe (read-only, dry-runs).
        <b>Red</b> = destructive (approve, cancel, promote) — these require typing an
        explicit confirmation phrase. Visit the <b>Guide</b> tab for a 5-minute
        quick start.` },
  { t: "Three tabs to know first", g: "🧭",
    b: `<b>Overview</b> — overall status. <b>Jobs</b> — everything you run, with full
        logs. <b>Readiness</b> — the "can we train a model?" verdict. Everything else
        can wait; nothing breaks by reading.` },
  { t: "You are the human approver", g: "🔐",
    b: `Release approvals flow through the same automation layer as the CLI — when
        you click approve here it is recorded as a valid human decision. The AI
        reviewer NEVER auto-passes: exit code 3 means "needs human eyes".` },
];

let welcomeStep = 0;

function renderWelcomeSlide() {
  const s = WELCOME_SLIDES[welcomeStep];
  $("#welcome-slide").innerHTML = `
    <div class="welcome-glyph">${s.g}</div>
    <h2>${esc(s.t)}</h2>
    <p>${s.b}</p>`;
  $("#welcome-step-ind").textContent = `${welcomeStep + 1} / ${WELCOME_SLIDES.length}`;
  $("#welcome-next").textContent = welcomeStep === WELCOME_SLIDES.length - 1
    ? "Start using the dashboard" : "Next";
}

function maybeShowWelcome() {
  if (localStorage.getItem(WELCOME_KEY)) return;
  welcomeStep = 0;
  renderWelcomeSlide();
  $("#welcome-backdrop").hidden = false;
}
function closeWelcome(done) {
  if (done) localStorage.setItem(WELCOME_KEY, "1");
  $("#welcome-backdrop").hidden = true;
}

/* ── Pipelines ────────────────────────────────────────────────── */
let fsmSelected = null;

RENDERERS.pipelines = async (root) => {
  const d = await api("/api/pipelines");
  window.__pipelinesData = d.pipelines || [];
  fsmSelected = fsmSelected && window.__pipelinesData.some(p => p.pipeline_id === fsmSelected)
    ? fsmSelected : (window.__pipelinesData[0] || {}).pipeline_id;

  const rows = window.__pipelinesData.map(p => `
    <tr class="${p.pipeline_id === fsmSelected ? "sel-row" : ""}">
      <td class="mono wrap"><a href="#" data-fsm="${esc(p.pipeline_id)}">${esc(p.pipeline_id)}</a></td>
      <td>${statusPill(p.current_state)}</td>
      <td class="small muted">${esc(fmtTime(p.last_updated))}</td>
      <td class="num">${p.transition_count}</td>
      <td class="actions-cell">
        ${actionBtn("pipeline.run", "run ▸ dry", { pipeline_id: p.pipeline_id, dry_run: true })}
        ${p.current_state === "FAILED"
          ? actionBtn("pipeline.retry", "retry", { pipeline_id: p.pipeline_id }) +
            actionBtn("pipeline.resume", "resume", { pipeline_id: p.pipeline_id }) : ""}
        ${actionBtn("pipeline.request_approval", "req approval", { pipeline_id: p.pipeline_id })}
        ${actionBtn("pipeline.approve", "approve", { pipeline_id: p.pipeline_id })}
        ${actionBtn("pipeline.deny", "deny", { pipeline_id: p.pipeline_id })}
        ${actionBtn("pipeline.release", "release", { pipeline_id: p.pipeline_id })}
        ${actionBtn("pipeline.cancel", "cancel", { pipeline_id: p.pipeline_id }, "btn-danger")}
      </td>
    </tr>`).join("");

  root.innerHTML = `
    <div class="inline-form">
      <div class="field"><label for="np-id">new pipeline-id</label>
        <input type="text" id="np-id" placeholder="release-v0.4" required></div>
      <label class="check-row"><input type="checkbox" id="np-dry" checked> dry-run first</label>
      <button class="btn btn-primary" id="np-run">Run pipeline</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>Pipeline</th><th>State</th><th>Updated</th><th>Transitions</th><th>Actions</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5">${emptyState("No pipelines recorded", "run one with the form above")}</td></tr>`}</tbody>
    </table></div>
    <div id="fsm-holder">${emptyState("Loading FSM…", "", "")}</div>`;

  $("#np-run").addEventListener("click", async () => {
    const pid = $("#np-id").value.trim();
    if (!pid) return;
    try {
      const resp = await api("/api/actions/pipeline.run/run", {
        method: "POST", body: JSON.stringify(
          { pipeline_id: pid, dry_run: $("#np-dry").checked }),
      });
      toast(`Job <code>${esc(resp.job.id)}</code> queued`, "ok");
      switchTab("jobs");
    } catch (e) { toast(`Run failed: ${esc(e.message)}`, "err"); }
  });

  $$("a[data-fsm]", root).forEach(a =>
    a.addEventListener("click", ev => {
      ev.preventDefault();
      fsmSelected = a.dataset.fsm;
      renderFSMPanel();
      $$("tbody tr", root).forEach(tr =>
        tr.classList.toggle("sel-row", tr.querySelector("a[data-fsm]")?.dataset.fsm === fsmSelected));
    }));

  async function renderFSMPanel() {
    const holder = $("#fsm-holder", root);
    if (!fsmSelected) { holder.innerHTML = emptyState("No pipeline selected", ""); return; }
    holder.innerHTML = skeletonCards(2);
    try {
      const det = await api(`/api/pipelines/${encodeURIComponent(fsmSelected)}`);
      const p = det.pipeline || {};
      const visited = (p.transitions || []).flatMap(t => [t.from_state, t.to_state]);
      const trans = [...(p.transitions || [])].reverse().slice(0, 12).map(t => `
        <li><span class="mono small">${esc(t.from_state)} → <b>${esc(t.to_state)}</b></span>
          <div class="muted small">${esc(fmtTime(t.timestamp))} · by ${esc(t.triggered_by)}
          ${t.reason ? `· ${esc(t.reason)}` : ""}</div></li>`).join("");
      holder.innerHTML = `
        <h2 class="section-title">State machine · ${esc(fsmSelected)}</h2>
        <div class="card">${svgFSM(p.current_state, visited)}
          <div class="small muted">Current: ${statusPill(p.current_state)}
            · ${p.transition_count} transitions · updated ${esc(fmtTime(p.last_updated))}</div></div>
        <div class="grid cols-3">
          <div class="card"><h3>Facts</h3><dl class="kv">
            <dt>state file</dt><dd class="mono small wrap">${esc(p.state_file || "")}</dd>
            <dt>approval</dt><dd>${det.approval_request
              ? statusPill(det.approval_request.decision || det.approval_request.status || "pending")
              : pill("none requested", "muted")}</dd></dl></div>
          <div class="card"><h3>Recent transitions</h3>
            <ul class="timeline">${trans || '<li class="muted">no transitions recorded</li>'}</ul></div>
          <div class="card"><h3>Governance</h3>
            <p class="muted small">VALIDATION → RELEASED is forbidden; release requires
            human approval through the automation layer. The browser user IS the approver.</p>
            <div class="action-row">
              ${actionBtn("pipeline.request_approval", "request approval", { pipeline_id: fsmSelected })}
              ${actionBtn("pipeline.rescind", "rescind", { pipeline_id: fsmSelected })}
            </div></div>
        </div>`;
    } catch (e) {
      holder.innerHTML = emptyState("Pipeline not found", e.message);
    }
  }
  renderFSMPanel();
};

/* ── Review ───────────────────────────────────────────────────── */
RENDERERS.review = async (root) => {
  const [progress, queue, artifacts, sft] = await Promise.all([
    api("/api/review/progress"), api("/api/review/queue"),
    api("/api/review/artifacts"), api("/api/review/sft"),
  ]);
  const stats = progress && !progress._missing ? progress.stats || {} : null;
  const queueRows = Object.entries(queue.queues || {}).map(([name, q]) => `
    <tr><td class="mono">${esc(name)}</td>
      <td>${q.exists ? fmtNum(q.records) : pill("missing", "muted")}</td></tr>`).join("");
  const artRows = (artifacts.artifacts || [])
    .filter(a => /\.(jsonl|json|md)$/.test(a.name)).slice(0, 60).map(a => `
      <tr><td class="mono wrap"><a href="#" data-preview="${esc(a.path)}">${esc(a.name)}</a></td>
        <td class="num small">${fmtBytes(a.bytes)}</td></tr>`).join("");
  const sftRows = (sft.batches || []).map(b => `
    <tr><td class="mono">${esc(b.tag)}</td>
      <td>${b.has_reviews ? fmtBytes(b.reviews_bytes) : pill("no reviews", "muted")}</td>
      <td class="wrap small mono">${b.summary ? esc(JSON.stringify({
        reviewed: b.summary.reviewed, accepted: b.summary.accepted,
        rejected: b.summary.rejected, gated_out: b.summary.gated_out,
        failures: b.summary.failures })) : "—"}</td></tr>`).join("");

  root.innerHTML = `
    <div class="grid cols-3">
      <div class="card"><h3>Cohort progress</h3>
        ${stats ? `<dl class="kv">${Object.entries(stats).slice(0, 10).map(([k, v]) =>
            `<dt>${esc(k)}</dt><dd>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</dd>`).join("")}</dl>`
          : emptyState("No review cycle recorded", "review/operations/review_progress.json absent", "○")}
      </div>
      <div class="card"><h3>Queues</h3>
        <table><tbody>${queueRows}</tbody></table>
        <p class="muted small">${esc(queue.note || "")}</p></div>
      <div class="card"><h3>Dual-mode review</h3>
        <p class="muted small">Deterministic gates run first in every mode.
        AI-reviewer failures are routed back to review — exit code 3 surfaces as
        <b>needs_attention</b>, never acceptance.</p>
        <div class="action-row">
          ${actionBtn("review.sample", "Generate sample")}
          ${actionBtn("review.ai_run", "Run AI review")}
          ${actionBtn("review.calibrate", "Calibrate human↔AI")}
          ${actionBtn("quality.calibrate", "Quality calibration")}
        </div></div>
    </div>

    <h2 class="section-title">SFT review batches</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>tag</th><th>reviews</th><th>summary · real counts from ai_review_summary.json</th></tr></thead>
      <tbody>${sftRows || `<tr><td colspan="3">${emptyState("No batches yet", "trigger AI review above", "◌")}</td></tr>`}</tbody>
    </table></div>

    <h2 class="section-title">Artifacts <span class="muted small normal-case">(click to preview)</span></h2>
    <div class="table-wrap"><table>
      <thead><tr><th>file</th><th>size</th></tr></thead>
      <tbody>${artRows || `<tr><td colspan="2">${emptyState("None", "")}</td></tr>`}</tbody>
    </table></div>

    <div class="card">${emptyState(
      "Interactive human review lives in the terminal",
      "keystroke-level KEEP/REVISE/REJECT runs via: atlas.py sft-review run --review-mode human …",
      "⌨")}</div>`;
  bindPreviewLinks(root);
};

/* ── Sources & ETL ────────────────────────────────────────────── */
RENDERERS.sources = async (root) => {
  const [sources, etl, cache, downloads] = await Promise.all([
    api("/api/sources"), api("/api/sources/etl"),
    api("/api/sources/cache"), api("/api/sources/downloads"),
  ]);
  const srcRows = (sources.sources || []).map(s => {
    const sid = s.source_id || s.id || "?";
    return `<tr><td class="mono">${esc(sid)}</td>
      <td>${esc(s.category || s.domain || "—")}</td>
      <td class="mono wrap small muted">${esc(s.source_url || s.url || "—")}</td>
      <td class="mono small">${esc(s.license || "—")}</td>
      <td class="actions-cell">
        ${actionBtn("download.execute", "download", { source_ids: [sid] })}
        ${actionBtn("etl.run", "etl", { source_ids: [sid] })}</td></tr>`;
  }).join("");
  const etlRows = (etl.outputs || []).map(e => `
    <tr><td class="mono">${esc(e.source_id)}</td>
      <td>${statusPill(e.status || "—")}</td>
      <td class="num">${fmtNum(e.extracted)}</td><td class="num">${fmtNum(e.normalized)}</td>
      <td class="num">${fmtNum(e.cleaned)}</td><td class="num">${fmtNum(e.atlas_records)}</td>
      <td>${e.staging_present ? fmtNum(e.staging_records) : pill("no staging", "muted")}</td></tr>`).join("");
  const dlMissing = downloads && downloads._missing;
  const dlRows = dlMissing ? [] : downloads.slice(0, 50).map(l => `
    <tr><td class="mono small">${esc(l.file)}</td><td class="mono small">${esc(l.source_id || "—")}</td>
      <td>${statusPill(l.status || "—")}</td><td class="num small">${fmtBytes(l.bytes)}</td></tr>`).join("");

  root.innerHTML = `
    <div class="card"><div class="action-row">
      ${actionBtn("acquire.dry_run", "Acquisition dry-run")}
      ${actionBtn("acquire.execute", "Acquisition execute")}
      ${actionBtn("download.dry_run", "Download plan (offline)")}
      ${actionBtn("cache.stats", "Cache statistics")}
    </div></div>

    <h2 class="section-title">Source registry</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>source</th><th>category</th><th>origin</th><th>license</th><th>ops</th></tr></thead>
      <tbody>${srcRows || `<tr><td colspan="5">${emptyState("Registry empty", "metadata/source_registry.json absent")}</td></tr>`}</tbody>
    </table></div>

    <h2 class="section-title">ETL outputs</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>source</th><th>status</th><th>extracted</th><th>normalized</th>
        <th>cleaned</th><th>atlas</th><th>staging</th></tr></thead>
      <tbody>${etlRows || `<tr><td colspan="7">${emptyState("No ETL outputs yet", "run etl on a downloaded source")}</td></tr>`}</tbody>
    </table></div>

    <h2 class="section-title">Download cache & logs</h2>
    <div class="grid cols-3">
      <div class="card"><h3>raw/.cache</h3><dl class="kv">
        <dt>objects</dt><dd>${cache._missing ? "—" : fmtNum(cache.objects)}</dd>
        <dt>partial entries</dt><dd>${cache._missing ? "—" : fmtNum(cache.partial_entries)}</dd>
        <dt>index db</dt><dd>${cache._missing ? "—" : fmtBytes(cache.index_db_bytes)}</dd>
      </dl></div>
      <div class="card"><h3>Recent download logs</h3>
        ${dlMissing ? emptyState("No downloads yet", downloads.reason, "∅")
          : `<table><tbody>${dlRows}</tbody></table>`}</div>
    </div>`;
};

/* ── Views ────────────────────────────────────────────────────── */
RENDERERS.views = async (root) => {
  const inv = await api("/api/views");
  const pkgCards = (inv.view_packages || []).map(p => `
    <div class="card"><h3>${esc(p.package)}</h3>
      <dl class="kv">
        <dt>models</dt><dd class="mono small">${esc(p.models.join(", ") || "—")}</dd>
        <dt>records observed</dt><dd class="num">${fmtNum(p.total_records_observed)}</dd>
      </dl>
      ${(p.jsonl_files || []).slice(0, 6).map(f =>
        `<div class="small"><a href="#" data-preview="${esc(f.path)}">${esc(f.path.split("/").pop())}</a>
         <span class="muted">· ${fmtBytes(f.bytes)} · ${fmtNum(f.records)} rec</span></div>`).join("")}
    </div>`).join("");

  root.innerHTML = `
    <div class="card">
      <p class="muted small">view_builder writes to <code>metadata/views/&lt;version&gt;/</code> — never to
      <code>curated/</code>. Production mode requires approved curated records and blocks on zero eligible.</p>
      <div class="action-row">
        ${actionBtn("views.build", "Build views")}
        ${actionBtn("transform.run", "Transform records")}
        ${actionBtn("e2e.run", "End-to-end run")}
      </div></div>
    <h2 class="section-title">View packages</h2>
    <div class="grid cols-3">${pkgCards ||
      emptyState("No view packages", "build one with the action above", "▦")}</div>
    <h2 class="section-title">Placeholders</h2>
    <div class="card mono small wrap">${(inv.training_views_placeholders || []).map(esc).join("<br>") || "—"}</div>`;
  bindPreviewLinks(root);
};

/* ── Releases ─────────────────────────────────────────────────── */
RENDERERS.releases = async (root) => {
  const idx = await api("/api/releases");
  const rels = idx.releases || [];
  const chronological = [...rels].sort((a, b) =>
    String(a.created_at || "").localeCompare(String(b.created_at || "")));
  const rows = rels.map(r => `
    <tr>
      <td class="mono"><b>${esc(r.version)}</b></td>
      <td>${r.release_type === "final" ? pill("final", "ok")
            : r.release_type ? pill(r.release_type, "info") : "—"}</td>
      <td>${statusPill(r.status)}</td>
      <td class="num">${fmtNum(r.total_records)}</td>
      <td class="small muted">${esc(fmtTime(r.created_at))}</td>
      <td class="actions-cell">
        <button class="btn btn-mini" data-release-detail="${esc(r.version)}">detail</button>
        ${actionBtn("release.verify_bundle", "verify bundle", { release: r.version })}
        ${actionBtn("release.checksums", "checksums", { release: r.version })}
      </td></tr>`).join("");

  root.innerHTML = `
    <h2 class="section-title">Chain</h2>
    <div class="card">${releaseChain(chronological)}</div>
    <h2 class="section-title">Operations</h2>
    <div class="card"><div class="action-row">
      ${actionBtn("release.verify_chain", "Verify hash chain")}
      ${actionBtn("release.audit_duplicates", "Audit duplicates")}
      ${actionBtn("release.promote", "Promote RC → final")}
      ${actionBtn("release.build_bundle", "Build new bundle")}
      ${actionBtn("release.upload_hf", "Publish to HF")}
      ${actionBtn("release.download_hf", "Restore from HF")}
    </div></div>
    <h2 class="section-title">Manifests</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>version</th><th>type</th><th>status</th><th>records</th>
        <th>created</th><th>ops</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div id="release-detail-holder"></div>`;

  $$("button[data-release-detail]", root).forEach(b =>
    b.addEventListener("click", async () => {
      try {
        const d = await api(`/api/releases/${encodeURIComponent(b.dataset.releaseDetail)}`);
        const m = d.manifest || {};
        $("#release-detail-holder", root).innerHTML = `
          <h2 class="section-title">Manifest · ${esc(d.version)}</h2>
          <div class="grid cols-3">
            <div class="card"><h3>Facts</h3><dl class="kv">
              <dt>records</dt><dd class="num">${fmtNum(m.total_records)}</dd>
              <dt>status</dt><dd>${statusPill(m.status)}</dd>
              <dt>created</dt><dd>${esc(fmtTime(m.created_at))}</dd>
              <dt>from_version</dt><dd>${esc(m.from_version || "—")}</dd>
              <dt>signature</dt><dd>${m.release_signature ? pill("present", "ok") : pill("absent", "warn")}</dd>
              <dt>chain_hash</dt><dd>${m.chain_hash ? pill("linked", "ok") : pill("—", "muted")}</dd>
            </dl></div>
            <div class="card"><h3>Bundle files (${d.bundle_file_count})</h3>
              <div class="log-box">${(d.bundle_files || []).slice(0, 80).map(f =>
                `${esc(f.path)}  (${fmtBytes(f.bytes)})`).join("\n")
                || "bundle directory not present locally"}</div></div>
            <div class="card"><h3>Gates passed</h3>
              <div class="wrap mono small">${esc(JSON.stringify(m.gates_passed ?? m.gates ?? "—"))}</div></div>
          </div>`;
        $("#release-detail-holder", root).scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (e) { toast(`Detail failed: ${esc(e.message)}`, "err"); }
    }));
};

/* ── Evaluation ───────────────────────────────────────────────── */
RENDERERS.evaluation = async (root) => {
  const [bench, reports] = await Promise.all([
    api("/api/evaluation/benchmarks"), api("/api/evaluation/reports"),
  ]);
  const groups = bench && !bench._missing ? bench.registry || {} : {};
  const benchRows = [];
  for (const [group, items] of Object.entries(groups)) {
    for (const [id, meta] of Object.entries(items || {})) {
      benchRows.push(`<tr><td class="mono">${esc(id)}</td>
        <td>${pill(group, group === "internal" ? "ok" : "info")}</td>
        <td class="wrap small muted">${esc(meta && typeof meta === "object"
          ? (meta.description || JSON.stringify(meta)).slice(0, 150) : String(meta))}</td>
        <td class="actions-cell">
          ${actionBtn("evaluation.describe", "describe", { benchmark_id: id })}
          ${actionBtn("evaluation.dry_run", "dry-run", { benchmark_id: id })}
          ${actionBtn("evaluation.run", "execute", { benchmark_id: id })}
        </td></tr>`);
    }
  }
  const repRows = (reports.reports || []).slice(0, 80).map(r => `
    <tr><td class="mono wrap small"><a href="#" data-preview="${esc(r.path)}">${esc(r.path)}</a></td>
      <td class="num small">${fmtBytes(r.bytes)}</td></tr>`).join("");

  root.innerHTML = `
    <div class="card"><div class="action-row">
      ${actionBtn("evaluation.list_benchmarks", "List benchmarks (CLI)")}
      ${actionBtn("benchmark.discover", "Discover benchmarks")}
      ${actionBtn("aql.validate", "Validate AQL query")}
      ${actionBtn("aql.execute", "Execute AQL query")}
    </div></div>
    <h2 class="section-title">Benchmark registry</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>id</th><th>kind</th><th>description</th><th>ops</th></tr></thead>
      <tbody>${benchRows || `<tr><td colspan="4">${emptyState("Registry absent", "")}</td></tr>`}</tbody>
    </table></div>
    <h2 class="section-title">Reports</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>file</th><th>size</th></tr></thead>
      <tbody>${repRows || `<tr><td colspan="2">${emptyState("No evaluation reports", "execute a benchmark above")}</td></tr>`}</tbody>
    </table></div>
    <p class="muted small">QEE v2 is frozen; scores are advisory and never auto-approve
    releases (known +2.14 bias vs humans).</p>`;
  bindPreviewLinks(root);
};

/* ── Readiness ────────────────────────────────────────────────── */
RENDERERS.readiness = async (root) => {
  const d = await api("/api/readiness");
  if (d._missing) {
    root.innerHTML = `<div class="card">${emptyState("Report not generated",
      "run integrity.readiness to compute the six-gate verdict")}<br>
      <div class="action-row">${actionBtn("integrity.readiness", "Compute now")}</div></div>`;
    bindActionButtonsFallback(root);
    return;
  }
  const gates = (d.gates || []).map(g => `
    <div class="gate-card ${g.verdict === "READY" ? "gate-ready" : g.verdict === "CONDITIONAL" ? "gate-conditional" : "gate-blocked"}">
      <div class="small muted">${esc(g.gate || g.name || "?")}</div>
      <div class="verdict">${esc(g.verdict || g.state || "?")}</div>
      <div class="gate-detail wrap">${esc(g.detail || g.reason || "")}</div>
    </div>`).join("");
  root.innerHTML = `
    <div class="grid cols-4">
      <div class="card kpi-card"><h3>Overall verdict</h3>
        <div class="kpi">${statusPill(d.verdict)}</div>
        <div class="muted small">${esc(d.dataset_version || "")} · ${esc(fmtTime(d.generated_at))}</div></div>
      <div class="card kpi-card"><h3>Integrity</h3>
        <div class="kpi">${d.report_hash ? "✓" : "!"}</div>
        <div class="muted small">report_hash ${d.report_hash ? "present" : "MISSING"}</div></div>
      <div class="card kpi-card" id="rd-ring"></div>
    </div>
    <h2 class="section-title">Gates</h2>
    <div class="gate-grid">${gates}</div>
    <div class="action-row" data-mount-actions>${actionBtn("integrity.readiness", "Recompute now (read-only)")}</div>`;

  const gs = {};
  for (const g of (d.gates || [])) gs[g.gate || g.name || "?"] = g.verdict || g.state;
  const ringHolder = $("#rd-ring", root);
  if (ringHolder) {
    ringHolder.innerHTML = `<h3>Gate mix</h3>${gateRing(gs)}`;
  }
};

/* fallback binder for handlers rendered without the delegated path */
function bindActionButtonsFallback(rootEl) {
  $$("button[data-action]", rootEl).forEach(() => { /* delegation covers it */ });
}

/* ── Jobs ─────────────────────────────────────────────────────── */
RENDERERS.jobs = async (root) => {
  const d = await api("/api/jobs?limit=150");
  window.__jobsData = d.jobs || [];
  const jobs = window.__jobsData;
  const done = jobs.filter(j => j.finished_at);
  const okRate = done.length
    ? Math.round(done.filter(j => j.status === "succeeded").length / done.length * 100) : null;
  const durations = done.filter(j => j.duration_ms != null).slice(0, 24)
    .map(j => j.duration_ms / 1000);

  const rows = jobs.map(j => `
    <tr data-job-id="${esc(j.id)}">
      <td class="mono small">${esc(j.id)}</td>
      <td class="wrap small">${esc(j.title)}<br><span class="muted mono">${esc(j.action)}</span></td>
      <td>${statusPill(j.status)}</td>
      <td class="num">${j.exit_code != null ? j.exit_code : "—"}
        ${j.needs_attention ? pill("attention", "warn") : ""}</td>
      <td class="num small muted">${j.duration_ms != null ? (j.duration_ms / 1000).toFixed(1) + "s" : "—"}</td>
      <td class="small muted">${esc(fmtTime(j.created_at))}</td>
      <td class="actions-cell">
        <button class="btn btn-mini" data-job-log="${esc(j.id)}">log</button>
        ${["running", "queued"].includes(j.status)
          ? `<button class="btn btn-mini btn-danger" data-job-cancel="${esc(j.id)}">cancel</button>` : ""}
      </td></tr>`).join("");

  root.innerHTML = `
    <div class="grid cols-4">
      <div class="card kpi-card"><h3>Total tracked</h3>
        <div class="kpi">${jobs.length}</div><div class="muted small">last 300 kept on disk</div></div>
      <div class="card kpi-card"><h3>Success rate</h3>
        <div class="kpi">${okRate == null ? "—" : okRate + "%"}</div>
        <div class="muted small">${done.length} finished</div></div>
      <div class="card kpi-card"><h3>Duration trend</h3>
        ${durations.length >= 2 ? svgSparkline(durations, { stroke: VIZ_OK() }) : emptyState("not enough data", "")}</div>
      <div class="card kpi-card"><h3>Active now</h3>
        <div class="kpi">${jobs.filter(j => ["running", "queued"].includes(j.status)).length}</div>
        <div class="muted small">refreshes automatically</div></div>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>job</th><th>action</th><th>status</th><th>exit</th><th>dur</th>
        <th>queued</th><th>ops</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7">${emptyState("No jobs yet", "trigger one from any tab — or press ⌘K", "⌘")}</td></tr>`}</tbody>
    </table></div>
    <h2 class="section-title">Log output</h2>
    <div class="log-tools">
      <input type="text" id="log-search" placeholder="filter log lines…" spellcheck="false">
      <button class="btn btn-mini" id="log-download" disabled>Download</button>
      <label class="check-row small"><input type="checkbox" id="log-autoscroll" checked> auto-scroll</label>
    </div>
    <div id="job-log-box" class="log-box muted">select “log” on a job…</div>`;

  let currentLogText = "";
  const box = $("#job-log-box", root);
  $$("button[data-job-log]", root).forEach(b =>
    b.addEventListener("click", async () => {
      box.classList.remove("muted");
      box.textContent = "loading…";
      try {
        const [text, detail] = await Promise.all([
          api(`/api/jobs/${b.dataset.jobLog}/log?bytes=60000`),
          api(`/api/jobs/${b.dataset.jobLog}`),
        ]);
        currentLogText = text && text.trim() ? text : "(no output captured)";
        $("#log-download", root).disabled = false;
        applyLogFilter($("#log-search", root).value);
        if (detail?.cli_result?.message) {
          box.insertAdjacentHTML("afterbegin",
            `<div class="${detail.cli_result.error ? "error-text" : "muted"}"
               >CLI decision: ${esc(detail.cli_result.message)}</div><hr>`);
        }
        box.scrollTop = box.scrollHeight;
      } catch (e) { box.textContent = `failed: ${e.message}`; }
    }));
  function applyLogFilter(q) {
    const needle = (q || "").toLowerCase();
    box.innerHTML = currentLogText.split("\n").map(line =>
      needle && line.toLowerCase().includes(needle)
        ? `<span class="log-line-hit">${esc(line)}</span>`
        : esc(line)).join("\n");
  }
  $("#log-search", root)?.addEventListener("input", ev => applyLogFilter(ev.target.value));
  $("#log-download", root)?.addEventListener("click", () => {
    const blob = new Blob([currentLogText], { type: "text/plain" });
    const aEl = document.createElement("a");
    aEl.href = URL.createObjectURL(blob);
    aEl.download = "job.log";
    aEl.click();
    URL.revokeObjectURL(aEl.href);
  });
  $$("button[data-job-cancel]", root).forEach(b =>
    b.addEventListener("click", async () => {
      if (!window.confirm(`Cancel job ${b.dataset.jobCancel}?`)) return;
      try {
        await api(`/api/jobs/${b.dataset.jobCancel}/cancel`, { method: "POST" });
        toast("Cancellation requested", "ok");
        renderTab("jobs");
      } catch (e) { toast(`Cancel failed: ${esc(e.message)}`, "err"); }
    }));
};
function VIZ_OK() { return "#34d399"; }

/* background refresh of jobs table */
setInterval(() => {
  if (CURRENT_TAB !== "jobs" || document.hidden) return;
  api("/api/jobs?limit=150").then(d => {
    const prev = window.__jobsData || [];
    const now = d.jobs || [];
    const sigPrev = JSON.stringify(prev.map(j => [j.id, j.status]));
    const sigNow = JSON.stringify(now.map(j => [j.id, j.status]));
    if (sigPrev !== sigNow) {
      const newlyDone = now.filter(j =>
        j.finished_at && !prev.find(p => p.id === j.id && p.finished_at));
      renderTab("jobs");
      for (const j of newlyDone) {
        toast(`Job <code>${esc(j.id)}</code> (${esc(j.action)}) → ${statusPill(j.status)}`
          + (j.needs_attention ? " — REVIEW OUTPUT" : ""),
          j.status === "succeeded" ? "ok" : "err");
      }
    }
  }).catch(() => {});
}, 4000);

/* ── command palette ──────────────────────────────────────────── */
let paletteItems = [];
let paletteSel = 0;

function paletteSources() {
  const items = [];
  for (const [id, label] of TABS) {
    items.push({ kind: "Go", title: label, hint: id,
      run: () => switchTab(id) });
  }
  for (const a of CATALOG_LIST) {
    items.push({ kind: a.danger === "destructive" ? "Danger" : "Action",
      title: a.title, hint: a.id, enabled: a.enabled, reason: a.disabled_reason,
      run: () => openActionModal(a.id, {}) });
  }
  for (const p of (window.__pipelinesData || [])) {
    items.push({ kind: "Pipeline", title: p.pipeline_id,
      hint: `${p.current_state} · ${p.transition_count} transitions`,
      run: () => { switchTab("pipelines"); setTimeout(() => {
        const link = $(`a[data-fsm="${CSS.escape(p.pipeline_id)}"]`);
        if (link) link.click();
      }, 350); } });
  }
  return items;
}

function openPalette() {
  paletteItems = paletteSources();
  paletteSel = 0;
  $("#palette-backdrop").hidden = false;
  const input = $("#palette-input");
  input.value = "";
  renderPaletteList("");
  input.focus();
}
const closePalette = () => { $("#palette-backdrop").hidden = true; };

function renderPaletteList(q) {
  const needle = q.toLowerCase().trim();
  const filtered = paletteItems.filter(it =>
    !needle || it.title.toLowerCase().includes(needle)
    || String(it.hint || "").toLowerCase().includes(needle));
  paletteItems._filtered = filtered;
  paletteSel = Math.min(paletteSel, Math.max(0, filtered.length - 1));
  $("#palette-list").innerHTML = filtered.map((it, i) => `
    <li class="${i === paletteSel ? "sel" : ""}" data-pi="${i}" role="option"
        aria-selected="${i === paletteSel}">
      <span class="pal-tag">${pill(it.kind, it.kind === "Danger" ? "err"
        : it.kind === "Go" ? "muted" : it.kind === "Pipeline" ? "info" : "ok")}</span>
      <span>${esc(it.title)}</span>
      <span class="muted small mono pal-tag">${esc(String(it.hint || "").slice(0, 46))}</span>
    </li>`).join("") || `<li class="muted">no matches</li>`;
  $$("#palette-list li[data-pi]").forEach(li =>
    li.addEventListener("click", () => execPaletteItem(filtered[Number(li.dataset.pi)])));
}

function execPaletteItem(item) {
  if (!item) return;
  closePalette();
  if (item.enabled === false) {
    toast(`Disabled: ${esc(item.reason || "")}`, "err");
    return;
  }
  item.run();
}

/* ── boot ─────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  buildSidebar();

  /* modal */
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal-backdrop").addEventListener("click", e => {
    if (e.target === $("#modal-backdrop")) closeModal();
  });
  $("#modal-form").addEventListener("submit", submitModal);
  $("#modal-submit").addEventListener("click", ev => {
    ev.preventDefault();
    const form = $("#modal-form");
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.dispatchEvent(new Event("submit", { cancelable: true }));
  });

  /* drawer */
  $("#drawer-close").addEventListener("click", () => { $("#drawer-backdrop").hidden = true; });
  $("#drawer-download").addEventListener("click", downloadDrawer);
  $("#drawer-backdrop").addEventListener("click", e => {
    if (e.target === $("#drawer-backdrop")) $("#drawer-backdrop").hidden = true;
  });

  /* auth */
  const saveToken = () => {
    const firstUnlock = !getToken();
    setToken($("#auth-input").value.trim());
    hideAuthBar();
    updateTokenChip();
    renderTab(CURRENT_TAB).catch(() => {});
    if (firstUnlock) setTimeout(maybeShowWelcome, 400);
  };
  $("#auth-save").addEventListener("click", saveToken);
  $("#auth-input").addEventListener("keydown", e => {
    if (e.key === "Enter") saveToken();
  });
  updateTokenChip();
  if (!getToken()) showAuthBar("paste the server's ATLAS_DASHBOARD_TOKEN value");

  /* sidebar collapse / mobile */
  $("#collapse-btn").addEventListener("click", () =>
    $("#sidebar").classList.toggle("collapsed"));
  $$("[data-tab-jump]").forEach(b =>
    b.addEventListener("click", () => { switchTab(b.dataset.tabJump); closeMobileNav(); }));
  $("#mobile-nav-btn").addEventListener("click", () => {
    $("#sidebar").classList.add("open");
    $("#sidebar-scrim").hidden = false;
  });
  $("#sidebar-scrim").addEventListener("click", closeMobileNav);

  /* command palette */
  $("#palette-btn").addEventListener("click", openPalette);
  $("#palette-input").addEventListener("input", ev => {
    paletteSel = 0;
    renderPaletteList(ev.target.value);
  });
  $("#palette-input").addEventListener("keydown", ev => {
    const filtered = paletteItems._filtered || [];
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      paletteSel = Math.min(paletteSel + 1, filtered.length - 1);
      renderPaletteList($("#palette-input").value);
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      paletteSel = Math.max(paletteSel - 1, 0);
      renderPaletteList($("#palette-input").value);
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      execPaletteItem(filtered[paletteSel]);
    }
  });
  $("#palette-backdrop").addEventListener("click", e => {
    if (e.target === $("#palette-backdrop")) closePalette();
  });

  /* welcome tour */
  $("#welcome-skip").addEventListener("click", () => closeWelcome(true));
  $("#welcome-next").addEventListener("click", () => {
    if (welcomeStep >= WELCOME_SLIDES.length - 1) closeWelcome(true);
    else { welcomeStep += 1; renderWelcomeSlide(); }
  });

  /* global keys */
  document.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      $("#palette-backdrop").hidden ? openPalette() : closePalette();
    } else if (e.key === "Escape") {
      closeModal(); closePalette();
      $("#drawer-backdrop").hidden = true;
    }
  });

  switchTab("overview");
  if (getToken()) maybeShowWelcome();
});

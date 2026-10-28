/* Atlas Dashboard — dependency-free SVG visualization primitives.
 * All charts render real server-side data; nothing here fabricates values.
 * Every function returns an SVG string sized via viewBox so it scales. */
"use strict";

/* Shared palette mirrors style.css tokens (kept literal for SVG attrs). */
const VIZ = {
  accent: "#4d9fff",
  accent2: "#22d3ee",
  ok: "#34d399",
  warn: "#fbbf24",
  err: "#f87171",
  muted: "#8b96a5",
  grid: "rgba(148,163,184,.14)",
  surface: "#131a25",
};

function escAttr(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* ── sparkline ─────────────────────────────────────────────────── */
/* values: number[]; renders a smooth-ish line + area fill. */
function svgSparkline(values, opts = {}) {
  const w = opts.width || 160, h = opts.height || 40;
  const vals = (values || []).filter(v => typeof v === "number" && isFinite(v));
  if (vals.length < 2) {
    return `<svg viewBox="0 0 ${w} ${h}" class="spark" role="img" aria-label="no trend data">
      <line x1="0" y1="${h - 4}" x2="${w}" y2="${h - 4}" stroke="${VIZ.grid}" stroke-width="1"/></svg>`;
  }
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = (max - min) || 1;
  const pad = 3;
  const pts = vals.map((v, i) => {
    const x = pad + (i * (w - pad * 2)) / (vals.length - 1);
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return [x, y];
  });
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  const last = pts[pts.length - 1];
  const gid = `sg${Math.random().toString(36).slice(2, 8)}`;
  return `<svg viewBox="0 0 ${w} ${h}" class="spark" role="img" aria-label="trend">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${VIZ.accent}" stop-opacity=".35"/>
      <stop offset="1" stop-color="${VIZ.accent}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${opts.stroke || VIZ.accent}" stroke-width="1.75"
          stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2.6" fill="${opts.stroke || VIZ.accent}"/>
  </svg>`;
}

/* ── donut ─────────────────────────────────────────────────────── */
/* segments: [{value, color, label}] ; centerText/centerSub rendered mid. */
function svgDonut(segments, opts = {}) {
  const size = opts.size || 150, stroke = opts.stroke || 16;
  const r = (size - stroke) / 2, cx = size / 2, cy = size / 2;
  const total = segments.reduce((a, s) => a + (s.value || 0), 0);
  const circ = 2 * Math.PI * r;
  let offset = 0;
  const arcs = segments.map(s => {
    const frac = total > 0 ? (s.value || 0) / total : 0;
    const len = frac * circ;
    const el = len > 0
      ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}"
           stroke-width="${stroke}" stroke-dasharray="${(len - 1.5).toFixed(2)} ${(circ - len + 1.5).toFixed(2)}"
           stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 ${cx} ${cy})"
           stroke-linecap="round"><title>${escAttr(s.label || "")}: ${s.value}</title></circle>`
      : "";
    offset += len;
    return el;
  }).join("");
  return `<svg viewBox="0 0 ${size} ${size}" class="donut" role="img" aria-label="${escAttr(opts.aria || "distribution")}">
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${VIZ.grid}" stroke-width="${stroke}"/>
    ${arcs}
    <text x="${cx}" y="${cy - 2}" text-anchor="middle" class="donut-big">${escAttr(opts.centerText || "")}</text>
    <text x="${cx}" y="${cy + 15}" text-anchor="middle" class="donut-sub">${escAttr(opts.centerSub || "")}</text>
  </svg>`;
}

/* ── horizontal bars ───────────────────────────────────────────── */
/* items: [{label, value, color?, display?}] normalized against max. */
function svgHBars(items, opts = {}) {
  const max = Math.max(...items.map(i => i.value || 0), 1);
  const rows = items.map(it => {
    const pct = Math.max(2, Math.round(((it.value || 0) / max) * 100));
    const val = it.display != null ? escAttr(it.display) : (typeof it.value === "number" ? it.value.toLocaleString("en-US") : escAttr(it.value));
    return `<div class="hbar-row">
      <span class="hbar-label" title="${escAttr(it.label)}">${escAttr(it.label)}</span>
      <span class="hbar-track"><span class="hbar-fill" data-w="${pct}"></span></span>
      <span class="hbar-val mono">${val}</span>
    </div>`;
  }).join("");
  return `<div class="hbars" role="img" aria-label="${escAttr(opts.aria || "bar chart")}">${rows}</div>`;
}

/* animate .hbar-fill widths after insertion (CSS transition on --w) */
function animateHBars(rootEl) {
  $$(".hbar-fill", rootEl || document).forEach(el => {
    requestAnimationFrame(() => { el.style.width = el.dataset.w + "%"; });
  });
}

/* ── FSM state graph ───────────────────────────────────────────── */
/* Renders the 11-state automation FSM. current: state name;
 * visited: set/array of states seen in transition history. */
const FSM_MAIN = ["INGESTED", "QUALITY_CHECK", "PROVENANCE_CHECK", "CONTENT_REVISION",
  "VALIDATION", "WAITING_HUMAN_APPROVAL", "READY_FOR_RELEASE", "RELEASED"];
const FSM_SIDE = ["FAILED", "CANCELLED", "RELEASE_REJECTED"];

function shortState(s) {
  return s.replace(/_/g, " ")
    .replace("WAITING HUMAN APPROVAL", "AWAIT APPROVAL")
    .replace("PROVENANCE CHECK", "PROVENANCE")
    .replace("QUALITY CHECK", "QUALITY")
    .replace("CONTENT REVISION", "REVISION");
}

function svgFSM(current, visited = []) {
  const vis = new Set(visited);
  const nodeW = 118, nodeH = 40, gap = 30;
  const colsPerRow = 4;
  const rows = [FSM_MAIN.slice(0, 4), FSM_MAIN.slice(4)];
  const W = colsPerRow * nodeW + (colsPerRow - 1) * gap + 8;
  const H = rows.length * (nodeH + 46) + 70;
  let out = "";
  const centers = {};

  rows.forEach((row, ri) => {
    row.forEach((st, ci) => {
      const x = 4 + ci * (nodeW + gap);
      const y = 10 + ri * (nodeH + 46);
      centers[st] = [x + nodeW / 2, y + nodeH / 2];
      const isCur = st === current;
      const isVisited = vis.has(st);
      const cls = isCur ? "fsm-cur" : isVisited ? "fsm-visited" : "fsm-idle";
      out += `<g class="fsm-node ${cls}">
        <rect x="${x}" y="${y}" rx="9" width="${nodeW}" height="${nodeH}"/>
        <text x="${x + nodeW / 2}" y="${y + nodeH / 2 + 4}">${escAttr(shortState(st))}</text>
      </g>`;
    });
  });
  // arrows within rows + wrap connector
  rows.forEach((row, ri) => {
    for (let ci = 0; ci < row.length - 1; ci++) {
      const a = centers[row[ci]], b = centers[row[ci + 1]];
      const y = a[1];
      out += `<line x1="${a[0] + nodeW / 2 + 2}" y1="${y}" x2="${b[0] - nodeW / 2 - 7}" y2="${y}"
        class="fsm-edge ${vis.has(row[ci]) && vis.has(row[ci + 1]) ? "edge-hot" : ""}"/>
        <polygon points="${b[0] - nodeW / 2 - 8},${y - 3.5} ${b[0] - nodeW / 2 - 1},${y} ${b[0] - nodeW / 2 - 8},${y + 3.5}"
          class="fsm-arrow"/>`;
    }
  });
  // wrap arrow from last of row0 to first of row1
  if (rows.length === 2) {
    const a = centers[rows[0][rows[0].length - 1]], b = centers[rows[1][0]];
    out += `<path d="M ${a[0]},${a[1] + nodeH / 2 + 2} C ${a[0]},${a[1] + 38} ${b[0]},${b[1] - 38} ${b[0] - 2},${b[1] - nodeH / 2 - 6}"
      class="fsm-edge ${vis.has(rows[0][3]) && vis.has(rows[1][0]) ? "edge-hot" : ""}" fill="none"/>
      <polygon points="${b[0] - 5},${b[1] - nodeH / 2 - 8} ${b[0] + 3},${b[1] - nodeH / 2 - 2} ${b[0] - 6},${b[1] - nodeH / 2 - 1}" class="fsm-arrow"/>`;
  }
  // side (terminal) states row
  const sideY = 10 + 2 * (nodeH + 46);
  FSM_SIDE.forEach((st, i) => {
    const x = 60 + i * (nodeW + gap);
    out += `<g class="fsm-node fsm-side"><rect x="${x}" y="${sideY}" rx="9" width="${nodeW}" height="${nodeH}"/>
      <text x="${x + nodeW / 2}" y="${sideY + nodeH / 2 + 4}">${escAttr(shortState(st))}</text></g>`;
  });

  return `<svg viewBox="0 0 ${W} ${H}" class="fsm" role="img"
    aria-label="pipeline state machine, current state ${escAttr(current || "unknown")}">${out}</svg>`;
}

/* ── release chain ─────────────────────────────────────────────── */
/* releases: [{version, release_type, total_records, created_at}] oldest-first */
function releaseChain(releases) {
  if (!releases.length) return "";
  const blocks = releases.map(r => {
    const cls = r.release_type === "final" ? "chain-final" : "chain-rc";
    return `<div class="chain-block ${cls}">
      <span class="mono chain-v">${escAttr(r.version)}</span>
      <span class="chain-meta">${r.release_type === "final" ? "FINAL" : "RC"} · ${fmtNum(r.total_records)}</span>
    </div>`;
  }).join(`<svg viewBox="0 0 18 10" class="chain-link" aria-hidden="true">
      <line x1="1" y1="5" x2="12" y2="5" stroke="currentColor" stroke-width="1.5"/>
      <polygon points="11,1.5 17,5 11,8.5" fill="currentColor"/>
    </svg>`);
  return `<div class="release-chain">${blocks}</div>`;
}

/* ── gate ring for readiness (6 gates) ─────────────────────────── */
function gateRing(gates) {
  const colors = { READY: VIZ.ok, CONDITIONAL: VIZ.warn, BLOCKED: VIZ.err };
  const segs = Object.entries(gates).map(([g, v]) => ({
    value: 1, color: colors[v] || VIZ.muted, label: `${g}=${v}`,
  }));
  const ready = Object.values(gates).filter(v => v === "READY").length;
  return svgDonut(segs, {
    size: 140, stroke: 14,
    centerText: `${ready}/${Object.keys(gates).length}`,
    centerSub: "ready", aria: "readiness gates",
  });
}

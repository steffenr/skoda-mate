// Dependency-free SVG charts: lineChart (time series, 1-2 y axes, area, step) and barChart (grouped/stacked).
// Both return an element that redraws itself when its width changes, and show a tooltip on hover/touch.
import { h, svg } from './dom.js';
import * as f from './format.js';

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)'];
const M = { top: 14, right: 12, bottom: 26, left: 40 };

export function niceScale(min, max, count = 5) {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1, ticks: [0, 1] };
  if (min === max) { if (min === 0) max = 1; else { min -= Math.abs(min) * 0.1; max += Math.abs(max) * 0.1; } }  // a flat series still needs a range
  const span = max - min;
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return { min: lo, max: hi, ticks };
}

const toMs = (x) => (x instanceof Date ? x.getTime() : typeof x === 'string' ? new Date(x).getTime() : x);

function timeLabel(ms, spanMs) {
  const d = new Date(ms);
  if (spanMs < 1.2 * 864e5) return d.toLocaleTimeString(f.getLang(), { hour: '2-digit', minute: '2-digit' });
  if (spanMs < 5 * 864e5) return `${d.toLocaleDateString(f.getLang(), { weekday: 'short' })} ${d.toLocaleTimeString(f.getLang(), { hour: 'numeric' })}`;
  if (spanMs < 120 * 864e5) return d.toLocaleDateString(f.getLang(), { day: 'numeric', month: 'short' });
  return d.toLocaleDateString(f.getLang(), { month: 'short', year: '2-digit' });
}

function responsive(root, draw) {
  let last = 0;
  const run = () => { const w = Math.floor(root.clientWidth); if (w && w !== last) { last = w; draw(w); } };
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(run).observe(root);
  queueMicrotask(run);
  setTimeout(run, 60);
}

function legend(series) {
  return series.length > 1 || series[0]?.name
    ? h('div', { class: 'legend' }, ...series.map((s, i) => h('span', null, h('i', { style: { background: s.color || COLORS[i % 4] } }), s.name)))
    : null;
}

/**
 * lineChart({series:[{name, data:[{x,y}], color?, axis?:'left'|'right', area?, step?, fmt?}], height?, yLeft?:{min,max,fmt}, yRight?, empty?,
 *   gaps?:[{from, to}]})
 * `gaps` are stretches without data: they are shaded, and no line or area is drawn across them.
 */
export function lineChart({ series, height = 220, yLeft = {}, yRight = {}, xFmt, emptyText = 'No data yet', gaps = [] }) {
  const root = h('div', { class: 'chart' });
  const pts = series.map((s) => ({ ...s, data: (s.data || []).filter((p) => p.y != null && !Number.isNaN(p.y)).map((p) => ({ x: toMs(p.x), y: +p.y })).sort((a, b) => a.x - b.x) }));
  const all = pts.flatMap((s) => s.data);
  if (all.length < 2) { root.append(h('div', { class: 'empty' }, emptyText)); return root; }
  const holes = gaps.map((g) => ({ from: toMs(g.from), to: toMs(g.to) })).filter((g) => g.to > g.from);
  const xs = [...all.map((p) => p.x), ...holes.flatMap((g) => [g.from, g.to])];
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  // runs of points with no gap between neighbours: each run is its own line (and area)
  const runs = (data) => data.reduce((acc, p, j) => {
    const a = data[j - 1];
    if (!a || holes.some((g) => g.from >= a.x && g.to <= p.x)) acc.push([p]); else acc.at(-1).push(p);
    return acc;
  }, []);
  const hasRight = pts.some((s) => s.axis === 'right');
  const scaleFor = (axis, cfg) => {
    const ys = pts.filter((s) => (s.axis || 'left') === axis).flatMap((s) => s.data.map((p) => p.y));
    if (!ys.length) return null;
    const sc = niceScale(cfg.min ?? Math.min(...ys), cfg.max ?? Math.max(...ys));
    if (cfg.min != null) sc.min = cfg.min;  // pinned ends (e.g. 0-100 %) are honoured exactly
    if (cfg.max != null) sc.max = cfg.max;
    sc.ticks = sc.ticks.filter((t) => t >= sc.min - 1e-9 && t <= sc.max + 1e-9);  // never draw an axis label outside the plot
    return sc;
  };
  const SL = scaleFor('left', yLeft), SR = hasRight ? scaleFor('right', yRight) : null;
  const tip = h('div', { class: 'tip', hidden: true });
  root.append(tip);

  function draw(W) {
    root.querySelectorAll('svg').forEach((n) => n.remove());
    const left = M.left, right = hasRight ? M.left : M.right;
    const iw = W - left - right, ih = height - M.top - M.bottom;
    const X = (x) => left + ((x - xMin) / (xMax - xMin || 1)) * iw;
    const Y = (s, y) => { const sc = (s.axis === 'right' && SR) ? SR : SL; return M.top + ih - ((y - sc.min) / (sc.max - sc.min || 1)) * ih; };
    const g = svg('svg', { viewBox: `0 0 ${W} ${height}`, role: 'img', 'aria-label': series.map((s) => s.name).filter(Boolean).join(', ') });
    for (const t of SL.ticks) {
      const y = M.top + ih - ((t - SL.min) / (SL.max - SL.min)) * ih;
      g.append(svg('line', { x1: left, x2: left + iw, y1: y, y2: y, class: 'grid' }), svg('text', { x: left - 6, y: y + 4, 'text-anchor': 'end' }, (yLeft.fmt || f.num)(t)));
    }
    if (SR) for (const t of SR.ticks) {
      const y = M.top + ih - ((t - SR.min) / (SR.max - SR.min)) * ih;
      g.append(svg('text', { x: left + iw + 6, y: y + 4, 'text-anchor': 'start' }, (yRight.fmt || f.num)(t)));
    }
    const span = xMax - xMin;
    const steps = iw < 420 ? 2 : 4;  // fewer labels on a phone so they never overlap
    for (let i = 0; i <= steps; i++) {
      const ms = xMin + (span * i) / steps;
      g.append(svg('text', { x: X(ms), y: height - 6, 'text-anchor': i === 0 ? 'start' : i === steps ? 'end' : 'middle' }, (xFmt || timeLabel)(ms, span)));
    }
    for (const hole of holes) g.append(svg('rect', { class: 'gap', x: X(hole.from), y: M.top, width: Math.max(1, X(hole.to) - X(hole.from)), height: ih }));
    pts.forEach((s, i) => {
      const color = s.color || COLORS[i % 4];
      for (const run of runs(s.data)) {
        if (run.length === 1) {  // a lone reading between two gaps: a dot, since a one-point path draws nothing
          g.append(svg('circle', { cx: X(run[0].x), cy: Y(s, run[0].y), r: 2.5, fill: color }));
          continue;
        }
        let d = '';
        run.forEach((p, j) => {
          const x = X(p.x), y = Y(s, p.y);
          if (j === 0) d += `M${x},${y}`;
          else d += s.step ? `H${x}V${y}` : `L${x},${y}`;
        });
        if (s.area) {
          const base = M.top + ih;
          g.append(svg('path', { d: `${d}L${X(run.at(-1).x)},${base}L${X(run[0].x)},${base}Z`, fill: color, opacity: 0.14 }));
        }
        g.append(svg('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      }
    });
    const cursor = svg('line', { y1: M.top, y2: M.top + ih, stroke: 'var(--muted)', 'stroke-dasharray': '3 3', visibility: 'hidden' });
    g.append(cursor);
    const hit = svg('rect', { x: left, y: M.top, width: iw, height: ih, fill: 'transparent' });
    const move = (ev) => {
      const r = g.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const xv = xMin + ((px - left) / iw) * span;
      const lines = []; let near = null;
      pts.forEach((s, i) => {
        if (!s.data.length) return;
        let best = s.data[0];
        for (const p of s.data) if (Math.abs(p.x - xv) < Math.abs(best.x - xv)) best = p;
        near = near && Math.abs(near.x - xv) < Math.abs(best.x - xv) ? near : best;
        lines.push(`${s.name ? `${s.name}: ` : ''}${(s.fmt || f.num)(best.y)}`);
      });
      cursor.setAttribute('x1', X(near.x)); cursor.setAttribute('x2', X(near.x)); cursor.setAttribute('visibility', 'visible');
      tip.hidden = false;
      tip.replaceChildren(h('div', null, new Date(near.x).toLocaleString(f.getLang(), { dateStyle: 'medium', timeStyle: 'short' })), ...lines.map((l) => h('div', null, l)));
      tip.style.left = `${Math.min(Math.max(X(near.x) / W * root.clientWidth, 60), root.clientWidth - 60)}px`;
      tip.style.top = `${M.top + 24}px`;
    };
    hit.addEventListener('pointermove', move);
    hit.addEventListener('pointerleave', () => { tip.hidden = true; cursor.setAttribute('visibility', 'hidden'); });
    g.append(hit);
    root.prepend(g);
  }
  responsive(root, draw);
  const lg = legend(series);
  if (lg) root.append(lg);
  return root;
}

/**
 * barChart({categories:[{label, values:[..], tip?}], series:[{name,color?}], stacked?, height?, fmt?, unit?})
 */
export function barChart({ categories, series, stacked = false, height = 220, fmt = f.num, emptyText = 'No data yet' }) {
  const root = h('div', { class: 'chart' });
  if (!categories.length || categories.every((c) => c.values.every((v) => !v))) { root.append(h('div', { class: 'empty' }, emptyText)); return root; }
  const tip = h('div', { class: 'tip', hidden: true });
  root.append(tip);
  const tops = categories.map((c) => (stacked ? c.values.reduce((a, b) => a + (b || 0), 0) : Math.max(...c.values.map((v) => v || 0))));
  const S = niceScale(0, Math.max(...tops), 4);

  function draw(W) {
    root.querySelectorAll('svg').forEach((n) => n.remove());
    const iw = W - M.left - M.right, ih = height - M.top - M.bottom;
    const band = iw / categories.length;
    const inner = Math.min(band * 0.7, 56);
    const Y = (v) => M.top + ih - ((v - S.min) / (S.max - S.min || 1)) * ih;
    const g = svg('svg', { viewBox: `0 0 ${W} ${height}`, role: 'img', 'aria-label': series.map((s) => s.name).join(', ') });
    for (const t of S.ticks) {
      g.append(svg('line', { x1: M.left, x2: M.left + iw, y1: Y(t), y2: Y(t), class: 'grid' }), svg('text', { x: M.left - 6, y: Y(t) + 4, 'text-anchor': 'end' }, fmt(t)));
    }
    const every = Math.ceil(categories.length / Math.max(1, Math.floor(iw / 54)));
    categories.forEach((c, i) => {
      const cx = M.left + band * i + band / 2;
      const w = stacked ? inner : inner / series.length;
      let acc = 0;
      c.values.forEach((v, j) => {
        if (!v) return;
        const color = series[j].color || COLORS[j % 4];
        const x = stacked ? cx - inner / 2 : cx - inner / 2 + w * j;
        const y0 = Y(stacked ? acc : 0), y1 = Y(stacked ? acc + v : v);
        g.append(svg('rect', { x, y: y1, width: Math.max(2, w - 2), height: Math.max(1, y0 - y1), rx: 3, fill: color }));
        acc += v;
      });
      if (i % every === 0) g.append(svg('text', { x: cx, y: height - 6, 'text-anchor': 'middle' }, c.label));
      const hit = svg('rect', { x: M.left + band * i, y: M.top, width: band, height: ih, fill: 'transparent' });
      hit.addEventListener('pointerenter', () => {
        tip.hidden = false;
        tip.replaceChildren(h('div', null, c.tip || c.label), ...c.values.map((v, j) => h('div', null, `${series[j].name}: ${fmt(v || 0)}`)));
        tip.style.left = `${(cx / W) * root.clientWidth}px`; tip.style.top = `${M.top + 20}px`;
      });
      hit.addEventListener('pointerleave', () => { tip.hidden = true; });
      g.append(hit);
    });
    root.prepend(g);
  }
  responsive(root, draw);
  const lg = legend(series);
  if (lg) root.append(lg);
  return root;
}

/** Tiny inline trend line. */
export function sparkline(values, { width = 120, height = 32, color = 'var(--chart-1)' } = {}) {
  const v = values.filter((x) => x != null);
  if (v.length < 2) return h('span', { class: 'muted' }, '–');
  const lo = Math.min(...v), hi = Math.max(...v);
  const d = v.map((y, i) => `${i ? 'L' : 'M'}${(i / (v.length - 1)) * width},${height - 3 - ((y - lo) / (hi - lo || 1)) * (height - 6)}`).join('');
  return svg('svg', { viewBox: `0 0 ${width} ${height}`, width, height, 'aria-hidden': 'true' }, svg('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linecap': 'round' }));
}

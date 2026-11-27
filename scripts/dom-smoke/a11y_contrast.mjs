// Text contrast of every visible text element (4.5:1, large text 3:1), composited over its real background, light and dark. Usage: node a11y_contrast.mjs http://localhost:8000
// K=1.35 shows what is within 35% of the limit.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
const B = process.argv[2] || 'http://localhost:8000';
const ROUTES = ['', 'trips', 'trips/3', 'charges', 'charges/3', 'prices', 'battery', 'control', 'stats', 'map', 'events', 'settings', 'system', 'system/capabilities', 'system/calls', 'system/diagnostics'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const b = await puppeteer.launch({ executablePath: process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium', headless: 'new', args: ['--no-sandbox'] });
const found = new Map();
const check = (K) => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p[3] ?? 1]; };
  const over = (top, bot) => { const a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; };
  const lum = ([r, g, bl]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(bl); };
  const ratio = (a, c) => { const x = lum(a), y = lum(c); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bgOf = (el) => {
    const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
    let bg = parse(getComputedStyle(document.documentElement).backgroundColor); if (!bg || bg[3] === 0) bg = [255, 255, 255, 1];
    const bodyBg = parse(getComputedStyle(document.body).backgroundColor); if (bodyBg && bodyBg[3] > 0) bg = over(bodyBg, bg);
    for (const e of chain.reverse()) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c[3] > 0) bg = over(c, bg); }
    return bg;
  };
  const opacityOf = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
    if (el.closest('.leaflet-container, script, style, noscript, [hidden]')) continue;
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.visibility === 'hidden' || cs.display === 'none' || r.width === 0 || r.height === 0) continue;
    if (el.closest('[disabled], [aria-disabled=true]')) continue;
    const isSvg = el instanceof SVGElement;
    let fg = parse(isSvg ? cs.fill : cs.color); if (!fg) continue;
    const bg = bgOf(isSvg ? el.closest('svg').parentElement : el);
    const op = opacityOf(el);
    fg = over([fg[0], fg[1], fg[2], fg[3] * op], bg);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const need = large ? 3 : 4.5, ratioV = ratio(fg, bg);
    if (ratioV < need * K) out.push({ sel: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : ''), text: n.textContent.trim().slice(0, 40), ratio: Math.round(ratioV * 100) / 100, need, fg: fg.slice(0, 3).map(Math.round).join(','), bg: bg.slice(0, 3).map(Math.round).join(',') });
  }
  return out;
};
for (const theme of ['light', 'dark']) {
  const p = await b.newPage(); await p.setViewport({ width: 1280, height: 900 });
  for (const r of ROUTES) {
    await p.goto(`${B}/#/${r}`, { waitUntil: 'networkidle0' }); await sleep(1800);
    await p.evaluate((th) => { document.documentElement.dataset.theme = th; }, theme); await sleep(300);
    for (const x of await p.evaluate(check, Number(process.env.K || 1))) { const k = `${theme}|${x.sel}|${x.fg}|${x.bg}`; const e = found.get(k) || { ...x, theme, where: new Set() }; e.where.add(r || 'overview'); found.set(k, e); }
  }
  await p.close();
}
await b.close();
const list = [...found.values()].sort((a, b) => a.ratio - b.ratio);
if (process.env.A11Y_JSON) fs.writeFileSync(process.env.A11Y_JSON, JSON.stringify(list.map((e) => ({ ...e, where: [...e.where] })), null, 2));
for (const e of list) console.log(`${e.theme.padEnd(5)} ${String(e.ratio).padEnd(5)} (need ${e.need}) fg(${e.fg}) bg(${e.bg}) ${e.sel} "${e.text}" on ${[...e.where].slice(0, 3).join(',')}`);
console.log(`TOTAL ${list.length}`);

// Headless smoke test of the dashboard: loads the REAL modules from disk into jsdom and talks to a running server.
//   cd scripts/dom-smoke && npm install      (once)
//   DEMO=1 DB_PATH=/tmp/demo.db ../../.venv/bin/uvicorn --factory skoda_mate.web:app --port 8765 &
//   node run.mjs [route ...]                  (BASE=http://localhost:8765 by default)
// It renders each route, fails on console errors / error banners / missing pages, and prints the page text so a
// wrong number or an empty section is visible without a browser. Leaflet (CDN) is not loaded here.
import { JSDOM } from 'jsdom';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const BASE = process.env.BASE || 'http://localhost:8765';
const STATIC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../skoda_mate/static');
const WAIT = +(process.env.WAIT || 2200);
const dom = new JSDOM('<!doctype html><html><head></head><body><div id="root"></div></body></html>', { url: BASE + '/', pretendToBeVisual: true });
const w = dom.window;
const errors = [];
const realFetch = globalThis.fetch;
Object.assign(globalThis, {
  window: w, document: w.document, Node: w.Node, HTMLElement: w.HTMLElement, localStorage: w.localStorage,
  location: w.location, matchMedia: () => ({ matches: false, addEventListener() {} }),
  ResizeObserver: class { observe() {} disconnect() {} }, IntersectionObserver: class { observe() {} },
  fetch: (u, o) => realFetch(new URL(u, BASE), o),
});
Object.defineProperty(globalThis, 'navigator', { value: w.navigator, configurable: true });
w.scrollTo = () => {}; w.matchMedia = globalThis.matchMedia;
console.error = (...a) => { errors.push(a.map((x) => (x && x.stack) || String(x)).join(' ')); };
process.on('unhandledRejection', (e) => errors.push('unhandledRejection: ' + ((e && e.stack) || e)));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { start } = await import(`${STATIC}/app.js`);
start(document.getElementById('root'));
await sleep(2500);

const routes = process.argv.slice(2).length ? process.argv.slice(2) : ['', 'trips', 'charges', 'battery', 'control', 'stats', 'map', 'events', 'settings', 'system'];
const full = !!process.env.FULL;
let failed = 0;
for (const r of routes) {
  errors.length = 0;
  w.location.hash = `#/${r}`;
  await sleep(WAIT);
  const text = document.getElementById('main').textContent.replace(/\s+/g, ' ').trim();
  const crashed = /Something went wrong|not available yet|Page not found/.test(text);
  const bad = [...document.querySelectorAll('#main .banner.bad')].map((b) => b.textContent.trim());
  const status = crashed || errors.length ? 'FAIL' : 'ok  ';
  if (status === 'FAIL') failed++;
  console.log(`${status} #/${r.padEnd(12)} ${full ? text : text.slice(0, 200)}`);
  for (const e of errors.slice(0, 4)) console.log('     console.error:', e.split('\n').slice(0, 3).join(' | ').slice(0, 400));
  for (const b of bad) console.log('     banner:', b.slice(0, 200));
}
console.log(failed ? `\n${failed} route(s) failed` : '\nall routes rendered');
process.exit(failed ? 1 : 0);

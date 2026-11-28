// A dashboard tab can stay open for days. This drives the 30-second tick loop of a real browser against a running DEMO
// server, with the clock sped up 30x (a 30 s interval fires every second), and checks what must hold over a long time:
//  1. a quiet car costs one request per tick (the history and parked-loss answers are not fetched again),
//  2. a slow server never gets a second overview request while one is still unanswered,
//  3. a failing server is asked less and less often, the page says so, and it recovers by itself,
//  4. leaving a page lets go of its Leaflet map.
//   BASE=http://localhost:8766 node longrun.mjs        (needs puppeteer-core and Chromium, like browser_e2e.mjs)
import puppeteer from 'puppeteer-core';

const BASE = process.env.BASE || 'http://localhost:8765';
const CHROME = process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium';
const SCALE = 30;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (name, ok, extra = '') => { if (!ok) failed++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${extra ? '  ' + extra : ''}`); };

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
await page.evaluateOnNewDocument((scale) => {
  const setInt = window.setInterval.bind(window);
  window.setInterval = (fn, ms, ...a) => setInt(fn, ms === 30000 ? ms / scale : ms, ...a);
}, SCALE);

const count = {};
let inflight = 0, maxInflight = 0, mode = 'ok';   // ok | slow | down
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.setRequestInterception(true);
page.on('request', (req) => {
  const url = new URL(req.url());
  if (url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') { req.abort(); return; }   // no map tiles, no CDN
  const key = url.pathname.replace(/\d+/g, 'N');
  count[key] = (count[key] || 0) + 1;
  if (key.endsWith('/overview')) {
    inflight++; maxInflight = Math.max(maxInflight, inflight);
    if (mode === 'slow') { setTimeout(() => req.continue().catch(() => {}), 8000); return; }
    if (mode === 'down') { req.respond({ status: 502, contentType: 'text/plain', body: 'bad gateway' }); return; }
  }
  req.continue();
});
const settle = (req) => { if (new URL(req.url()).pathname.endsWith('/overview')) inflight = Math.max(0, inflight - 1); };
page.on('requestfinished', settle); page.on('requestfailed', settle);
const reset = () => { for (const k of Object.keys(count)) delete count[k]; maxInflight = 0; };
const banners = () => page.evaluate(() => [...document.querySelectorAll('.banner')].map((e) => e.textContent).join(' | '));
const overviews = () => count['/api/vehicles/N/overview'] || 0;

await page.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(2500);

// 1. quiet car
reset();
await sleep(12000);
check('quiet: the tick loop runs', overviews() >= 8, `${overviews()} overview requests in 12 s`);
check('quiet: unchanged data is not fetched again', (count['/api/vehicles/N/history'] || 0) <= 1 && (count['/api/vehicles/N/parked-loss'] || 0) <= 1,
  `history=${count['/api/vehicles/N/history'] || 0} parked-loss=${count['/api/vehicles/N/parked-loss'] || 0}`);

// 2. slow server
mode = 'slow'; reset();
await sleep(14000);
check('slow server: never two overview requests at once', maxInflight === 1, `max ${maxInflight} at once`);
mode = 'ok';
await sleep(9000);   // let the slow answers drain

// 3. failing server
mode = 'down'; reset();
await sleep(12000);
const bannerDown = await banners();
check('failing server: the page says it cannot be reached', /cannot be reached/.test(bannerDown), bannerDown.slice(0, 120));
check('failing server: requests back off', overviews() <= 7, `${overviews()} requests in 12 s (a plain loop would send 12)`);
mode = 'ok';
let recovered = false;
for (let i = 0; i < 20 && !recovered; i++) { await sleep(1000); recovered = !/cannot be reached/.test(await banners()); }
check('failing server: the banner goes away when it answers again', recovered);

// 4. maps are let go
await page.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' });
await sleep(1500);
const onMap = await page.evaluate(async () => (await import('/static/lib/mapview.js')).liveMaps());
await page.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1500);
const afterMap = await page.evaluate(async () => (await import('/static/lib/mapview.js')).liveMaps());
check('leaving the map page disposes its map', onMap >= 1 && afterMap === 0, `${onMap} on the page, ${afterMap} after leaving`);

check('no JavaScript errors', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `\n${failed} check(s) FAILED` : '\nlong-run OK');
process.exit(failed ? 1 : 0);

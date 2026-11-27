// Real-browser end-to-end check (puppeteer-core + installed Chromium) against a running DEMO server.
//   npm install puppeteer-core --no-save   (once)   then:   BASE=http://localhost:8765 node browser_e2e.mjs
// 1. phone viewport: every page must fit the screen (no horizontal scroll) and nothing may throw
// 2. click-through: navigation, refresh, a command, a setting, units, language, the mobile "More" menu
import puppeteer from 'puppeteer-core';
import { layoutPass, pseudoPass } from './pseudo_pass.mjs';

const BASE = process.env.BASE || 'http://localhost:8765';
const SHOTS = process.env.SHOTS || '';
const CHROME = process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium';
const ROUTES = ['', 'trips', 'trips/5', 'charges', 'charges/3', 'prices', 'battery', 'control', 'stats', 'map', 'places', 'places/1', 'events', 'settings', 'system'];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
const check = (name, ok, extra = '') => { if (!ok) failed++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${extra ? '  ' + extra : ''}`); };

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
const errors = [];
const watch = (page) => {
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|favicon/.test(m.text())) errors.push(m.text().slice(0, 160)); });
};
const reset = async () => { const p = await browser.newPage(); await p.goto(BASE + '/'); await p.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ units: 'km', language: 'en', theme: 'dark' }) })); await p.close(); };
await reset();

// ---------------------------------------------------------------- 1. phone
const phone = await browser.newPage();
watch(phone);
await phone.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await phone.goto(BASE + '/', { waitUntil: 'networkidle0' });
console.log('--- phone 390x844');
for (const r of ROUTES) {
  await phone.goto(`${BASE}/#/${r}`, { waitUntil: 'networkidle0' });
  await sleep(1800);
  const m = await phone.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    // Content inside a horizontally scrollable box (tables, the system tab row) is reachable, not clipped: the page
    // itself must not scroll sideways, which is what the scrollWidth check below covers.
    const scrolls = (e) => {
      for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if ((ox === 'auto' || ox === 'scroll') && p.scrollWidth > p.clientWidth + 1) return true;
      }
      return false;
    };
    const over = [...document.querySelectorAll('#main *')].filter((e) => e.getBoundingClientRect().right > vw + 1 && getComputedStyle(e).position !== 'fixed'
      && !e.closest('.leaflet-container') && !e.closest('svg') && !scrolls(e))
      .map((e) => `${e.tagName.toLowerCase()}.${(e.className && e.className.baseVal === undefined ? e.className : '').toString().split(' ')[0]} +${Math.round(e.getBoundingClientRect().right - vw)}px`);
    return { scrollW: document.documentElement.scrollWidth, vw, over: [...new Set(over)].slice(0, 4), text: document.getElementById('main').innerText.length };
  });
  check(`phone #/${r || 'overview'} fits`, m.scrollW <= m.vw + 1 && m.over.length === 0 && m.text > 40, `scrollWidth=${m.scrollW}/${m.vw} ${m.over.join(' ')}`);
  if (SHOTS && ['', 'control', 'trips'].includes(r)) await phone.screenshot({ path: `${SHOTS}/phone-${r || 'overview'}.png` });
}
await phone.goto(`${BASE}/#/places/1`, { waitUntil: 'networkidle0' });
await sleep(1800);
const pd = await phone.evaluate(() => {
  const text = document.getElementById('main').innerText;
  const visitsCard = [...document.querySelectorAll('#main .card')].find((c) => /Recent visits/.test(c.querySelector('h2')?.textContent || ''));
  return {
    visits: visitsCard ? visitsCard.querySelectorAll('tbody tr').length : 0,
    stats: ['Visits', 'Days', 'Parked time', 'Charged', 'Cost'].every((s) => text.includes(s)),
    charges: /Recent charges/.test(text),
    chargeLink: !!document.querySelector('#main a[href^="#/charges/"]'),
    back: !!document.querySelector('#main a[href="#/places"]'),
    nav: document.querySelector('.sidebar .nav a[aria-current="page"]')?.textContent?.trim() || '',
  };
});
check('place detail shows stats, visits and charges', pd.stats && pd.visits > 0 && pd.charges && pd.chargeLink, `${pd.visits} visits, stats=${pd.stats}, charges=${pd.charges}, link=${pd.chargeLink}`);
check('place detail links back and keeps Places highlighted', pd.back && pd.nav === 'Places', `back=${pd.back} nav=${pd.nav}`);
await phone.goto(`${BASE}/#/places/999999`, { waitUntil: 'networkidle0' });
await sleep(1400);
const pdMissing = await phone.evaluate(() => ({ text: document.getElementById('main').innerText, tables: document.querySelectorAll('#main table').length }));
check('place detail handles an unknown id', /Place not found\./.test(pdMissing.text) && pdMissing.tables === 0, `${pdMissing.tables} tables, text=${pdMissing.text.slice(0, 60)}`);
const tabs = await phone.$$('.tabbar a, .tabbar button');
check('phone bottom tab bar has 5 entries', tabs.length === 5, String(tabs.length));
await phone.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await phone.evaluate(() => [...document.querySelectorAll('.tabbar button')].find((b) => /More/.test(b.textContent)).click());
await sleep(400);
check('"More" menu opens with the other pages', (await phone.$$('.modal a.btn')).length >= 5);
await phone.keyboard.press('Escape');
await phone.close();

// ---------------------------------------------------------------- 2. desktop click-through
const d = await browser.newPage();
watch(d);
await d.setViewport({ width: 1280, height: 900 });
await d.goto(BASE + '/', { waitUntil: 'networkidle0' });
await sleep(1500);
console.log('--- desktop click-through');
const labels = ['Trips', 'Charges', 'Battery', 'Control', 'Statistics', 'Map', 'Places', 'Activity', 'Settings', 'System'];
for (const l of labels) {
  await d.evaluate((txt) => [...document.querySelectorAll('.sidebar .nav a')].find((a) => a.textContent.trim() === txt).click(), l);
  await sleep(1300);
  const h = await d.evaluate(() => location.hash);
  const ok = await d.evaluate(() => !/Something went wrong|not available yet/.test(document.getElementById('main').innerText) && document.getElementById('main').innerText.length > 30);
  check(`sidebar → ${l}`, ok, h);
}
await d.evaluate(() => document.querySelector('.brand').click());
await sleep(900);
check('clicking "Škoda Mate" opens the Overview', await d.evaluate(() => location.hash === '#/' || location.hash === '' || location.hash === '#'), await d.evaluate(() => location.hash));

// ---------------------------------------------------------------- Activity: timeline and list
await d.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await sleep(1500);
const tl = await d.evaluate(() => {
  const main = document.getElementById('main');
  const bars = main.querySelectorAll('.tl-track .tl-bar').length;
  const det = main.querySelector('details.tl-text');
  if (det) det.open = true;
  const first = main.querySelector('.tl-bar');
  return { bars, items: main.querySelectorAll('details.tl-text li').length, label: first?.getAttribute('aria-label') || '', title: document.title, tabs: [...main.querySelectorAll('.seg button')].map((b) => b.textContent) };
});
check('Activity opens on the Timeline with bars', tl.bars > 0 && tl.tabs[0] === 'Timeline' && /^Activity/.test(tl.title), `${tl.bars} bars, tabs=${tl.tabs}, title=${tl.title}`);
check('Activity bars carry a label and the Text list has items', tl.label.length > 5 && tl.items > 0, `${tl.items} items, "${tl.label}"`);
await d.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'List').click());
await sleep(1200);
const lst = await d.evaluate(() => ({ events: document.querySelectorAll('#main .b-event').length, search: !!document.querySelector('#main input[type=search]'), more: document.getElementById('main').innerText }));
check('Activity List tab keeps the event table and filters', lst.events > 0 && lst.search, `${lst.events} events`);
await d.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Timeline').click());
await sleep(1000);
const back = await d.evaluate(() => document.querySelectorAll('#main .tl-bar').length);
check('Activity returns to the Timeline', back > 0, String(back));
const narrow = await browser.newPage();
watch(narrow);
await narrow.setViewport({ width: 360, height: 800, isMobile: true, hasTouch: true });
await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await sleep(1500);
const nw = await narrow.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, bars: document.querySelectorAll('.tl-bar').length }));
check('Activity timeline fits a 360 px phone', nw.sw <= nw.iw && nw.bars > 0, `scrollWidth=${nw.sw}/${nw.iw}, bars=${nw.bars}`);
// Day lines: energy on the day a charge started, charging time on the morning after, never "0.0 kWh"
const dayLines = await narrow.evaluate(() => [...document.querySelectorAll('.tl-day > .small.muted')].map((x) => x.textContent));
check('Activity day lines never say 0.0 kWh and show charged energy on some day', dayLines.length === 7 && !dayLines.some((l) => /\b0[.,]0 kWh/.test(l))
  && dayLines.some((l) => /Charged \d+[.,]\d kWh/.test(l)), JSON.stringify(dayLines));
// The real demo week: a precision note, a week summary line, every optional day part only when non-zero, and the bars'
// roles: a drive or charge with a record is a button, every other bar a plain labelled element
const tlReal = await narrow.evaluate(() => {
  const scroll = document.querySelector('.tl-scroll');
  const btns = [...document.querySelectorAll('button.tl-bar')], plain = [...document.querySelectorAll('.tl-bar:not(button)')];
  return { note: document.querySelector('.tl-precision')?.textContent || '', week: document.querySelector('.tl-week')?.textContent || '',
    scrolls: scroll ? scroll.scrollWidth > scroll.clientWidth + 1 : false, buttons: btns.length, plain: plain.length,
    buttonKinds: btns.every((b) => /tl-(drive|charge)/.test(b.className)), plainSafe: plain.every((b) => b.tabIndex === -1 && b.getAttribute('role') === 'img' && getComputedStyle(b).cursor !== 'pointer'),
    drive: !!document.querySelector('button.tl-bar.tl-drive') };
});
check('Activity shows the precision note under the legend', tlReal.note === 'Times are accurate to the poll interval.', tlReal.note);
check('Activity week summary line shows driving and parked time, no zero part', /^Week: Driving .*Parked /.test(tlReal.week) && !/\b0[.,]0 kWh|Climate 0 |Not heard from 0 /.test(tlReal.week), tlReal.week);
check('Activity track scrolls sideways at 360 px instead of squeezing the bars', tlReal.scrolls);
check('Only drive and charge bars with a record are buttons; other bars are plain labelled elements without a pointer', tlReal.buttons > 0 && tlReal.plain > 0 && tlReal.buttonKinds && tlReal.plainSafe, `buttons=${tlReal.buttons} plain=${tlReal.plain}`);
if (tlReal.drive) {
  await narrow.evaluate(() => document.querySelector('button.tl-bar.tl-drive').click());
  await sleep(600);
  check('Clicking a drive bar opens that trip', await narrow.evaluate(() => /^#\/trips\/\d+$/.test(location.hash)), await narrow.evaluate(() => location.hash));
  await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
  await sleep(1200);
}
// Timeline answered from a fixture: estimated bars, a partial cost, climate and "not heard from" time, an empty week, and how far back it goes
const tlDays = (from, to, withData) => {
  const out = [], d = new Date(`${from}T12:00:00Z`), end = new Date(`${to}T12:00:00Z`);
  for (; d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    const date = d.toISOString().slice(0, 10), at = (h, m = 0) => `${date}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00+00:00`;
    out.push({ date, intervals: withData ? [
      { kind: 'parked', start: at(0), end: at(8), minutes: 480, place: null },
      { kind: 'drive', start: at(8), end: at(9), minutes: 60, trip_id: 1, estimated: true },
      { kind: 'climate', start: at(9), end: at(10), minutes: 60 },
      { kind: 'unknown', start: at(10), end: at(12), minutes: 120 },
      { kind: 'charge', start: at(12), end: at(14), minutes: 120, charge_id: 1 },
    ] : [], summary: { drive_min: withData ? 60 : 0, charge_min: withData ? 120 : 0, climate_min: withData ? 60 : 0, parked_min: withData ? 480 : 0, unknown_min: withData ? 120 : 0,
      km: withData ? 12.5 : 0, kwh: 0, cost: withData ? tlCost : null, cost_partial: withData && tlCost >= 0.01 } });
  }
  return out;
};
let tlMode = 'data', tlCost = 3.2;
const tlReqs = [];
const tlIntercept = (req) => {
  const m = /\/api\/vehicles\/[^/]+\/timeline\?(.*)$/.exec(req.url());
  if (!m) { req.continue(); return; }
  const q = new URLSearchParams(m[1]);
  tlReqs.push({ from: q.get('from'), to: q.get('to'), tz: q.get('tz_offset') });
  const days = tlDays(q.get('from'), q.get('to'), tlMode !== 'empty');
  const sum = { drive_min: 60 * days.length, charge_min: 120 * days.length, climate_min: 60 * days.length, parked_min: 480 * days.length, unknown_min: 120 * days.length,
    km: 12.5 * days.length, kwh: 0, cost: tlCost == null ? null : tlCost * days.length, cost_partial: tlCost >= 0.01 };
  req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ from: q.get('from'), to: q.get('to'), days, summary: tlMode !== 'empty' ? sum : { ...sum, drive_min: 0, charge_min: 0, climate_min: 0, parked_min: 0, unknown_min: 0, km: 0, cost: null, cost_partial: false } }) });
};
await narrow.setRequestInterception(true);
narrow.on('request', tlIntercept);
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await sleep(1200);
const tlFix = await narrow.evaluate(() => {
  const det = document.querySelector('details.tl-text'); if (det) det.open = true;
  const est = document.querySelector('.tl-bar.tl-estimated');
  const first = document.querySelector('.tl-day');
  return { week: document.querySelector('.tl-week')?.textContent || '', day: first.querySelector('.small.muted').textContent, estimated: !!est, estLabel: est?.getAttribute('aria-label') || '', estTitle: est?.title || '',
    estClass: est ? getComputedStyle(est).opacity : '1', list: [...first.querySelectorAll('details.tl-text li')].map((x) => x.textContent), notEst: document.querySelectorAll('.tl-bar:not(.tl-estimated)').length,
    sw: document.documentElement.scrollWidth, iw: window.innerWidth };
});
check('Activity day line adds climate, not-heard-from time, km and an "at least" cost, and never prints 0.0 kWh',
  /Driving 1 h.*Parked 8 h/.test(tlFix.day) && /Climate 1 h/.test(tlFix.day) && /Not heard from 2 h/.test(tlFix.day) && /12[.,]5 km/.test(tlFix.day) && /at least .*3[.,]20/.test(tlFix.day) && !/0[.,]0 kWh/.test(tlFix.day), tlFix.day);
check('Activity week line carries the same parts from the summary', /^Week: .*Climate .*Not heard from .*km .*at least /.test(tlFix.week), tlFix.week);
check('Activity estimated bars are dimmed and say "estimated" in their label, title and text list', tlFix.estimated && tlFix.estimated && /estimated/.test(tlFix.estLabel) && /estimated/.test(tlFix.estTitle) && +tlFix.estClass < 1
  && tlFix.list.some((l) => /estimated/.test(l)) && tlFix.notEst > 0, `${tlFix.estLabel} | ${tlFix.list.join(' / ')}`);
check('Activity with the full day lines still fits 360 px', tlFix.sw <= tlFix.iw, `scrollWidth=${tlFix.sw}/${tlFix.iw}`);
// Back as far as it goes: the oldest reachable day is today minus 30
tlReqs.length = 0;
const reach = await narrow.evaluate(async () => {
  const prev = document.querySelector('button[aria-label="Previous week"]');
  let n = 0;
  while (!prev.disabled && n < 10) { prev.click(); n++; await new Promise((r) => setTimeout(r, 150)); }
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const oldest = new Date(); oldest.setDate(oldest.getDate() - 30);
  return { clicks: n, oldest: iso(oldest), disabled: prev.disabled };
});
await sleep(500);
check('Activity goes back until the oldest reachable day, today minus 30, and stops there', reach.disabled && tlReqs.at(-1)?.from === reach.oldest && reach.clicks >= 4 && reach.clicks <= 6, `${JSON.stringify(reach)} last=${JSON.stringify(tlReqs.at(-1))}`);
check('Activity sends the same tz_offset it positions bars with', tlReqs.every((r) => /^-?\d+$/.test(r.tz)), JSON.stringify(tlReqs.at(-1)));
// A known cost of exactly 0 says "free" (never 0.00); an unknown cost leaves the part out
const tlLines = () => narrow.evaluate(() => ({ week: document.querySelector('.tl-week')?.textContent || '', day: document.querySelector('.tl-day .small.muted')?.textContent || '' }));
const tlClick = (label) => narrow.evaluate((l) => [...document.querySelectorAll('#main button')].find((b) => b.textContent === l || b.getAttribute('aria-label') === l)?.click(), label);
tlCost = 0;
await tlClick('Today');
await sleep(900);
const tlFree = await tlLines();
check('Activity day and week line say "free" for a known zero cost, never 0.00', /· free$/.test(tlFree.day) && /· free$/.test(tlFree.week) && !/0[.,]00/.test(tlFree.day + tlFree.week), JSON.stringify(tlFree));
tlCost = null;
await tlClick('Previous week');
await sleep(900);
const tlUnknown = await tlLines();
check('Activity day and week line leave an unknown cost out (neither "free" nor an amount)', /Driving/.test(tlUnknown.day) && !/free|€|\$|at least/.test(tlUnknown.day + tlUnknown.week), JSON.stringify(tlUnknown));
// A cost that rounds to 0.00 in the currency reads like a known zero
tlCost = 0.0004;  // a week of it (7 x) is still under half a cent
await tlClick('Previous week');
await sleep(900);
const tlTiny = await tlLines();
check('Activity day and week line say "free" for a cost that rounds to 0.00, never 0.00', /· free$/.test(tlTiny.day) && /· free$/.test(tlTiny.week) && !/0[.,]00/.test(tlTiny.day + tlTiny.week), JSON.stringify(tlTiny));
tlCost = 3.2;
await tlClick('Today');
await sleep(900);
// An empty week shows the empty state, not an empty grid
tlMode = 'empty';
await narrow.evaluate(() => [...document.querySelectorAll('#main button')].find((b) => b.textContent === 'Today').click());
await sleep(900);
const tlEmpty = await narrow.evaluate(() => ({ empty: /Nothing recorded in this week/.test(document.getElementById('main').innerText), bars: document.querySelectorAll('.tl-bar').length }));
check('Activity empty week shows the empty state and no bars', tlEmpty.empty && tlEmpty.bars === 0, JSON.stringify(tlEmpty));
narrow.off('request', tlIntercept);
await narrow.setRequestInterception(false);
// Overview parked card (real demo: hourly parked readings and a standby drain, so sessions with a measured median, or
// the detection floor in a week of short stands; the empty state is covered with a mocked response further down)
const parkedCardProbe = () => {
  const c = [...document.querySelectorAll('#main .card')].find((x) => x.querySelector('header h2')?.textContent === 'Parked, last 7 days');
  const titles = [...document.querySelectorAll('#main .card > header h2')].map((x) => x.textContent);
  return { found: !!c, text: c ? c.innerText.replace(/\s+/g, ' ').trim() : '', stats: c ? c.querySelectorAll('.stat').length : 0, details: c?.querySelector('a.btn')?.getAttribute('href') || null,
    afterCharge: titles.indexOf('Parked, last 7 days') === titles.indexOf('Last charge') + 1, sw: document.documentElement.scrollWidth, iw: window.innerWidth };
};
await narrow.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1500);
const ov0 = await narrow.evaluate(parkedCardProbe);
check('Overview parked card (real demo) shows its sessions and a median loss, after Last charge', ov0.found && ov0.stats > 0 && /Median loss (\d+[.,]\d ?kWh\/day|below the detection floor)/.test(ov0.text) && /Parked sessions [1-9]/.test(ov0.text) && ov0.details === '#/stats' && ov0.afterCharge, ov0.text);
check('Overview parked card (real demo) fits a 360 px phone', ov0.sw <= ov0.iw, `scrollWidth=${ov0.sw}/${ov0.iw}`);
// Statistics: the Overview stays the default tab, the Parked tab renders its table (or the empty state) without page scroll
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1500);
const so = await narrow.evaluate(() => ({ tabs: [...document.querySelectorAll('#main .seg button')].map((b) => b.textContent), cards: document.querySelectorAll('#main .card').length, text: document.getElementById('main').innerText }));
check('Statistics opens on Overview with the Overview/Charging/Driving/Parked tabs', so.tabs.slice(0, 4).join() === 'Overview,Charging,Driving,Parked' && /Monthly overview/.test(so.text), `tabs=${so.tabs}, cards=${so.cards}`);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Parked').click());
await sleep(1500);
const pk = await narrow.evaluate(() => {
  const main = document.getElementById('main');
  const tbl = main.querySelector('table.t');
  const wrap = tbl?.closest('.scroll-x');
  return { sw: document.documentElement.scrollWidth, iw: window.innerWidth, rows: tbl ? tbl.querySelectorAll('tbody tr').length : 0, headers: tbl ? [...tbl.querySelectorAll('th')].map((x) => x.textContent) : [],
    empty: !!main.querySelector('.empty') && /No parked sessions/.test(main.innerText), cards: main.querySelectorAll('.stat').length, inRegion: !!wrap && wrap.getBoundingClientRect().right <= window.innerWidth + 1,
    pressed: [...main.querySelectorAll('.seg')[0].querySelectorAll('button')].map((b) => b.getAttribute('aria-pressed')), note: /detection floor/.test(main.innerText) };
});
check('Parked tab (real demo) is active and renders sessions or the empty state', pk.pressed[3] === 'true' && (pk.rows > 0 || pk.empty), `rows=${pk.rows}, empty=${pk.empty}`);
check('Parked tab (real demo) fits a 360 px phone', pk.sw <= pk.iw, `scrollWidth=${pk.sw}/${pk.iw}`);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Overview').click());
await sleep(800);
const sb = await narrow.evaluate(() => /Monthly overview/.test(document.getElementById('main').innerText));
check('Statistics returns to the Overview from Parked', sb);

// The demo has no parked stand yet, so answer the parked-loss request with a fixture to exercise the table at 360 px:
// a normal stand, one below the detection floor, one flagged as an unrecorded charge, one without capacity (null energy).
const parkedFixture = (() => {
  const base = { start: '2026-11-20T20:00:00+00:00', end: '2026-11-21T20:00:00+00:00', hours: 24, place: 'Home', start_soc: 80, end_soc: 78, soc_delta: 2,
    kwh: 1.5, kwh_per_day: 1.5, cost: 0.4, cost_basis: 'home', warning: null, below_detection_floor: false };
  return { sessions: [
    { ...base },
    { ...base, place: null, end_soc: 80, soc_delta: 0, kwh: 0.0, kwh_per_day: 0.0, cost: null, below_detection_floor: true },
    { ...base, end_soc: 95, soc_delta: -15, kwh: -11.2, kwh_per_day: -11.2, cost: 3.33, warning: 'likely an unrecorded charge' },
    { ...base, place: 'Work', kwh: null, kwh_per_day: null, cost: null },
  ], total: 4, limit: 50, offset: 0,
  aggregates: { count: 1, flagged: 1, median_kwh_per_day: 1.5, mean_kwh_per_day: 1.5, kwh: 1.5, kwh_7d: 1.5, kwh_30d: 1.5, cost: 0.4 }, min_hours: 6, detection_floor_kwh: 0.77 };
})();
let parkedReq = '';
let parkedMode = 'normal';  // normal | fail | empty | zero: which answer the parked-loss request gets
let statsMode = 'real', statsReqs = 0;  // real | fail: the /stats request is answered by the server or refused; counted either way
const json = (req, body, status = 200) => req.respond({ status, contentType: 'application/json', body: JSON.stringify(body) });
// 120 stands, newest first as the server sends them, paged by the request's limit and offset like the server does;
// stand n (1-120) lasted 6 + n hours, so the hours name the row
const manyParked = Array.from({ length: 120 }, (_, i) => ({ ...parkedFixture.sessions[0],
  start: new Date(Date.UTC(2026, 8, 120 - i, 20)).toISOString(), end: new Date(Date.UTC(2026, 8, 121 - i, 20)).toISOString(), hours: 126 - i }));
const manyBody = () => {
  const q = new URL(parkedReq).searchParams, limit = Number(q.get('limit')), offset = Number(q.get('offset'));
  return { ...parkedFixture, sessions: manyParked.slice(offset, offset + limit), total: 120, limit, offset, aggregates: { ...parkedFixture.aggregates, count: 120, flagged: 0 } };
};
const parkedBody = () => (parkedMode === 'many' ? manyBody() : parkedMode === 'zero' ? { ...parkedFixture, aggregates: { ...parkedFixture.aggregates, count: 2, median_kwh_per_day: 0, mean_kwh_per_day: 0, kwh: 0, kwh_7d: 0, kwh_30d: 0, cost: null } }
  : parkedMode === 'empty' ? { ...parkedFixture, sessions: [], total: 0, aggregates: { ...parkedFixture.aggregates, count: 0, flagged: 0, median_kwh_per_day: null } } : parkedFixture);
const intercept = (req) => {
  if (/\/api\/vehicles\/[^/]+\/parked-loss/.test(req.url())) { parkedReq = req.url();
    if (parkedMode === 'fail') json(req, { detail: 'boom' }, 500); else json(req, parkedBody()); }
  else if (/\/api\/vehicles\/[^/]+\/stats(\?|$)/.test(req.url())) { statsReqs++; if (statsMode === 'fail') json(req, { detail: 'boom' }, 500); else req.continue(); }
  else req.continue();
};
await narrow.setRequestInterception(true);
narrow.on('request', intercept);
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1200);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Parked').click());
await sleep(1200);
const pf = await narrow.evaluate(() => {
  const main = document.getElementById('main');
  const tbl = main.querySelector('table.t');
  const wrap = tbl?.closest('.scroll-x');
  const rows = tbl ? [...tbl.querySelectorAll('tbody tr')].map((tr) => [...tr.children].map((td) => td.innerText.replace(/\s+/g, ' ').trim())) : [];
  return { sw: document.documentElement.scrollWidth, iw: window.innerWidth, headers: tbl ? [...tbl.querySelectorAll('th')].map((x) => x.textContent) : [], rows,
    cards: main.querySelectorAll('.stat').length, chips: main.querySelectorAll('table.t .chip.warn').length, note: /detection floor/.test(main.innerText),
    wrap: !!wrap, wrapRight: wrap ? wrap.getBoundingClientRect().right : 0 };
});
const [rNormal, rFloor, rWarn, rNull] = pf.rows;
check('Parked fixture: 4 stat cards, 7 headers, 4 rows, detection-floor note', pf.cards === 4 && pf.headers.length === 7 && pf.rows.length === 4 && pf.note, `cards=${pf.cards}, headers=${pf.headers}, rows=${pf.rows.length}`);
check('Parked request sends period start, today and tz_offset', /from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}&tz_offset=-?\d+/.test(parkedReq), parkedReq);
check('Parked normal row shows its numbers', rNormal && /1\.5 kWh/.test(rNormal[4]) && rNormal[5] === '1.5' && /0[.,]40/.test(rNormal[6]), JSON.stringify(rNormal));
check('Parked below-floor row says so once (energy column), shows a dash for the rate and no decimal loss', rFloor && /below the detection floor/.test(rFloor[4]) && rFloor[5] === '–' && !/0[.,]0/.test(`${rFloor[4]} ${rFloor[5]}`), JSON.stringify(rFloor));
check('Parked warning row has exactly one chip and dashes for kWh, kWh/day and cost', pf.chips === 1 && rWarn && /unrecorded charge/.test(rWarn[0]) && rWarn[4] === '–' && rWarn[5] === '–' && rWarn[6] === '–', `chips=${pf.chips} ${JSON.stringify(rWarn)}`);
check('Parked row without capacity shows dashes, not NaN or null', rNull && rNull[4] === '–' && rNull[5] === '–' && rNull[6] === '–' && !/NaN|null/.test(rNull.join(' ')), JSON.stringify(rNull));
check('Parked table fits a 360 px phone: page does not scroll sideways, table sits in its scroll region', pf.wrap && pf.sw <= pf.iw && pf.wrapRight <= pf.iw + 1, `scrollWidth=${pf.sw}/${pf.iw}, region right=${Math.round(pf.wrapRight)}`);
// A long history: 50 stands a page, newest first, with Newer/Older; the totals always cover the whole period
parkedMode = 'many';
const pageProbe = () => narrow.evaluate(() => {
  const main = document.getElementById('main');
  const hours = [...main.querySelectorAll('table.t tbody tr')].map((tr) => Number(tr.children[2].textContent));
  const buttons = [...main.querySelectorAll('.pager button')];
  const focused = buttons.find((b) => b === document.activeElement)?.textContent || '';
  return { rows: hours.length, first: hours[0], last: hours.at(-1), label: main.querySelector('.pager > span')?.textContent || null,
    disabled: buttons.map((b) => b.disabled).join(), focused, totals: /Parked sessions\s*120\b/.test(main.innerText), sw: document.documentElement.scrollWidth, iw: window.innerWidth };
});
const parkedClick = async (re) => {
  await narrow.evaluate((s) => [...document.querySelectorAll('#main button')].find((b) => new RegExp(s).test(b.textContent))?.click(), re);
  await sleep(500);
};
await parkedClick('^6 months$');
const pg1 = await pageProbe();
check('Parked shows the newest 50 of 120 stands with totals over all of them', pg1.rows === 50 && pg1.first === 126 && pg1.last === 77 && pg1.label === '1–50 of 120' && pg1.disabled === 'true,false' && pg1.totals && pg1.sw <= pg1.iw, JSON.stringify(pg1));
check('Parked asks the server for one page only', /limit=50&offset=0\b/.test(parkedReq), parkedReq);
await parkedClick('^Older');
const pg2 = await pageProbe();
check('Parked "Older" asks for the next page, keeps the totals and the keyboard on the button', /offset=50\b/.test(parkedReq) && pg2.rows === 50 && pg2.first === 76 && pg2.label === '51–100 of 120' && pg2.disabled === 'false,false' && /Older/.test(pg2.focused) && pg2.totals, JSON.stringify(pg2));
await parkedClick('^Older');
const pg3 = await pageProbe();
check('Parked last page shows the rest and moves the keyboard to "Newer"', pg3.rows === 20 && pg3.last === 7 && pg3.label === '101–120 of 120' && pg3.disabled === 'false,true' && /Newer/.test(pg3.focused), JSON.stringify(pg3));
await parkedClick('Newer$');
const pg4 = await pageProbe();
check('Parked "Newer" goes back a page', pg4.first === 76 && pg4.label === '51–100 of 120', JSON.stringify(pg4));
await parkedClick('^12 months$');
const pg5 = await pageProbe();
check('Parked starts on the first page again after the period changes', /offset=0\b/.test(parkedReq) && pg5.label === '1–50 of 120' && pg5.first === 126, JSON.stringify(pg5));
parkedMode = 'normal';
// Overview parked card with the same fixture: median, count, energy, floor subtitle, warning count and the Details link
await narrow.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1500);
const ov1 = await narrow.evaluate(parkedCardProbe);
check('Overview parked card requests the last seven days with a six-hour minimum', /from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}&min_hours=6&tz_offset=-?\d+/.test(parkedReq), parkedReq);
check('Overview parked card shows median, count, energy, floor subtitle and warning count', ov1.found && ov1.stats === 1 && /Median loss 1[.,]5 ?kWh\/day/.test(ov1.text) && /Parked sessions 1\b/.test(ov1.text) && /Energy 1[.,]5 kWh/.test(ov1.text)
  && /One percent of the battery is about 0[.,]77 kWh, so smaller losses are not measurable\./.test(ov1.text) && /1 left out as likely unrecorded charge(?!s)/.test(ov1.text) && !/NaN|null|undefined/.test(ov1.text), ov1.text);
check('Overview parked card links Details to #/stats, sits after Last charge and fits 360 px', ov1.details === '#/stats' && ov1.afterCharge && ov1.sw <= ov1.iw, `${ov1.details} after=${ov1.afterCharge} scrollWidth=${ov1.sw}/${ov1.iw}`);
// A failing request must not break the rest of the Overview: no card, the other cards stay
parkedMode = 'fail';
await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await narrow.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1500);
const ovFail = await narrow.evaluate(() => ({ titles: [...document.querySelectorAll('#main .card > header h2')].map((x) => x.textContent) }));
check('Overview survives a failing parked-loss request without the card', !ovFail.titles.includes('Parked, last 7 days') && ovFail.titles.includes('Last charge') && ovFail.titles.includes('Last trip'), ovFail.titles.join(', '));
parkedMode = 'normal';
// Fixture without sessions: the quiet line
parkedMode = 'empty';
await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await narrow.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1500);
const ov2 = await narrow.evaluate(parkedCardProbe);
check('Overview parked card with no sessions shows the quiet line only', ov2.found && /No parked stand long enough yet\./.test(ov2.text) && ov2.stats === 0 && !ov2.details, ov2.text);
parkedMode = 'normal';
// A median of exactly zero (at least half the counted stands below the floor) reads "below the detection floor", never "0.0"
parkedMode = 'zero';
await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await narrow.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1500);
const ov3 = await narrow.evaluate(() => {
  const s = [...document.querySelectorAll('#main .card .stat')].find((x) => x.querySelector('.label')?.textContent === 'Median loss');
  return { text: s ? s.innerText.replace(/\s+/g, ' ').trim() : null, sw: document.documentElement.scrollWidth, iw: window.innerWidth };
});
check('Overview parked card with a zero median says below the detection floor, no decimal', ov3.text && /below the detection floor/.test(ov3.text) && !/0[.,]0/.test(ov3.text) && ov3.sw <= ov3.iw, JSON.stringify(ov3));
const ov4 = await narrow.evaluate(parkedCardProbe);
check('Overview parked card with a zero energy total says below the detection floor, nowhere 0.0', ov4.found && /Energy below the detection floor/.test(ov4.text) && !/0[.,]0 kWh/.test(ov4.text), ov4.text);
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1200);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Parked').click());
await sleep(1200);
const pz = await narrow.evaluate(() => {
  const s = [...document.querySelectorAll('#main .stat')].find((x) => x.querySelector('.label')?.textContent === 'Median loss');
  return { text: s ? s.innerText.replace(/\s+/g, ' ').trim() : null, sw: document.documentElement.scrollWidth, iw: window.innerWidth };
});
check('Parked tab with a zero median says below the detection floor, no decimal', pz.text && /below the detection floor/.test(pz.text) && !/0[.,]0/.test(pz.text) && !/kWh\/day/.test(pz.text) && pz.sw <= pz.iw, JSON.stringify(pz));
const pe = await narrow.evaluate(() => {
  const s = [...document.querySelectorAll('#main .stat')].find((x) => x.querySelector('.label')?.textContent === 'Energy');
  return s ? s.innerText.replace(/\s+/g, ' ').trim() : null;
});
check('Parked tab with zero energy totals says below the detection floor in the tile and both windows, nowhere 0.0', pe && /^Energy below the detection floor Last 7 days below the detection floor · Last 30 days below the detection floor$/.test(pe) && !/0[.,]0/.test(pe), pe);
parkedMode = 'normal';
// The tab is remembered per viewer; the Parked tab never asks for /stats and survives it failing; Overview failing keeps the tab bar
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1000);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Parked').click());
await sleep(900);
await narrow.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
statsMode = 'fail'; statsReqs = 0;
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1200);
const rem = await narrow.evaluate(() => ({ pressed: [...document.querySelectorAll('#main .seg')[0].querySelectorAll('button')].map((b) => b.getAttribute('aria-pressed')), rows: document.querySelectorAll('#main table.t tbody tr').length,
  banner: document.querySelectorAll('#main .banner.bad').length }));
check('Statistics reopens on the remembered Parked tab', rem.pressed[3] === 'true' && rem.rows > 0, JSON.stringify(rem));
check('The Parked tab does not ask for /stats and shows no error when /stats fails', statsReqs === 0 && rem.banner === 0, `statsReqs=${statsReqs} banners=${rem.banner}`);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Overview').click());
await sleep(900);
const sf = await narrow.evaluate(() => ({ tabs: [...document.querySelectorAll('#main .seg')[0]?.querySelectorAll('button') || []].map((b) => b.textContent), banner: /Could not load statistics/.test(document.getElementById('main').innerText) }));
check('A failing Overview keeps the tab bar so the viewer can still switch', sf.banner && sf.tabs.join() === 'Overview,Charging,Driving,Parked', JSON.stringify(sf));
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Parked').click());
await sleep(900);
check('...and Parked still works from that error state', await narrow.evaluate(() => document.querySelectorAll('#main table.t tbody tr').length > 0));
statsMode = 'real';
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Overview').click());
await sleep(1200);
narrow.off('request', intercept);
await narrow.setRequestInterception(false);
// ---------------------------------------------------------------- Insight: Charging and Driving tabs, projected range
const clickTab = async (label) => {
  await narrow.evaluate((l) => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === l).click(), label);
  await sleep(1300);
};
const insightProbe = () => {
  const main = document.getElementById('main');
  const titles = [...main.querySelectorAll('.card > header h2')].map((x) => x.textContent);
  const cardOf = (title) => [...main.querySelectorAll('.card')].find((c) => (c.querySelector('header h2')?.textContent || '').includes(title));
  return { text: main.innerText.replace(/\s+/g, ' '), titles, sw: document.documentElement.scrollWidth, iw: window.innerWidth,
    heatCells: main.querySelectorAll('.heat-cell').length, heatTableRows: main.querySelectorAll('.heat details tbody tr').length,
    curveBars: ['Charge curve (AC)', 'Charge curve (DC)'].map((n) => cardOf(n)?.querySelectorAll('svg rect[rx]').length || 0),
    placeLinks: main.querySelectorAll('a[href^="#/places/"]').length, tripLinks: main.querySelectorAll('a[href^="#/trips/"]').length,
    banner: main.querySelectorAll('.banner.bad').length,
    // a number or a unit broken across lines fits the screen but cannot be read
    broken: [...main.querySelectorAll('table.t td.num, .stat .value small')].filter((el) => {
      const r = document.createRange(); r.selectNodeContents(el);
      return new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size > 1;
    }).map((el) => el.textContent) };
};
await narrow.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' });
await sleep(1200);
await clickTab('Charging');
const ic = await narrow.evaluate(insightProbe);
check('Charging tab shows totals, both power types, split, places and heatmap', ['Energy charged', 'Cost per kWh', 'Measured share', 'Average power', 'Home, public and other', 'Top charging places', 'When charging starts'].every((s) => ic.text.includes(s)) && ic.banner === 0 && !/NaN|undefined|\bnull\b/.test(ic.text), ic.titles.join(', '));
check('Charging tab draws separate AC and DC curves', ic.curveBars[0] >= 3 && ic.curveBars[1] >= 3, JSON.stringify(ic.curveBars));
check('Charging heatmap has 168 cells and a table fallback', ic.heatCells === 168 && ic.heatTableRows === 7, `${ic.heatCells} cells, ${ic.heatTableRows} rows`);
check('Charging tab fits a 360 px phone', ic.sw <= ic.iw, `scrollWidth=${ic.sw}/${ic.iw}`);
check('Charging numbers and units stay on one line on a phone', ic.broken.length === 0, ic.broken.join(' | '));
await clickTab('Driving');
const id = await narrow.evaluate(insightProbe);
check('Driving tab shows destinations, buckets, longest trips, consumption and the projection', ['Top destinations', 'Trip lengths', 'Longest trips', 'Consumption trend', 'When you drive', 'Projected distance per year'].every((s) => id.text.includes(s)) && /projection/i.test(id.text) && id.banner === 0 && !/NaN|undefined|\bnull\b/.test(id.text), id.titles.join(', '));
check('Driving numbers and units stay on one line on a phone', id.broken.length === 0, id.broken.join(' | '));
check('Driving destinations link to places and longest trips to trips', id.placeLinks >= 2 && id.tripLinks >= 3, `places=${id.placeLinks} trips=${id.tripLinks}`);
check('Driving tab shows no speed figures and fits a 360 px phone', !/km\/h|mph|speed/i.test(id.text) && id.sw <= id.iw, `scrollWidth=${id.sw}/${id.iw}`);
// A failing or empty answer keeps the tab bar; an inferred-only period shows energy and no curve; a late answer never draws over another tab
let insightMode = 'fail';
const inferredOnly = { currency: 'EUR', totals: { sessions: 2, energy_kwh: 20, cost: null, cost_partial: true, cost_per_kwh: null, measured_sessions: 0, measured_kwh: 0, inferred_sessions: 2, inferred_kwh: 20, inferred_share: 1, unknown_energy_sessions: 0, session_fees: 0 },
  types: Object.fromEntries(['ac', 'dc', 'unknown'].map((k) => [k, { sessions: 0, energy_kwh: 0, avg_power_kw: null, peak_power_kw: null, power_sessions: 0 }])),
  split: Object.fromEntries(['home', 'public', 'other'].map((k) => [k, { sessions: 0, energy_kwh: 0, cost: null, cost_partial: false }])),
  heatmap: Array.from({ length: 7 }, () => Array(24).fill(0)), heatmap_excluded: 2, top_places: [{ place_id: null, name: null, sessions: 2, energy_kwh: 20, cost: null, cost_partial: true }], curve: { ac: [], dc: [] } };
const insightIntercept = async (req) => {
  if (!/\/insights\/(charging|driving)/.test(req.url())) { req.continue(); return; }
  if (insightMode === 'fail') json(req, { detail: 'boom' }, 500);
  else if (insightMode === 'inferred') json(req, inferredOnly);
  else { await sleep(1500); req.continue(); }
};
await narrow.setRequestInterception(true);
narrow.on('request', insightIntercept);
await clickTab('Charging');
const ifail = await narrow.evaluate(() => ({ text: document.getElementById('main').innerText, tabs: document.querySelectorAll('#main .seg button').length }));
check('A failing insight request shows the error, a retry and keeps the tab bar', /Could not load charging insight/.test(ifail.text) && /Try again/.test(ifail.text) && ifail.tabs >= 4, ifail.text.slice(0, 120));
insightMode = 'inferred';
await clickTab('Driving'); await clickTab('Overview'); await clickTab('Charging');
const iinf = await narrow.evaluate(insightProbe);
check('Inferred-only charging shows energy and says why there is no power or curve', /20[.,]0 kWh/.test(iinf.text) && /inferred/i.test(iinf.text) && /Not enough readings for a charge curve/.test(iinf.text) && iinf.curveBars.join() === '0,0' && /Unknown place/.test(iinf.text) && !/NaN|undefined|\bnull\b/.test(iinf.text), iinf.text.slice(0, 200));
insightMode = 'slow';
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Driving').click());
await sleep(200);
await narrow.evaluate(() => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === 'Overview').click());
await sleep(2500);
const ilate = await narrow.evaluate(insightProbe);
check('A late insight answer does not draw over the tab chosen meanwhile', ilate.titles.includes('Monthly overview') && !ilate.titles.includes('Top destinations'), ilate.titles.join(', '));
narrow.off('request', insightIntercept);
await narrow.setRequestInterception(false);
await narrow.goto(`${BASE}/#/battery`, { waitUntil: 'networkidle0' });
await sleep(1500);
const br = await narrow.evaluate(() => {
  const c = [...document.querySelectorAll('#main .card')].find((x) => x.querySelector('header h2')?.textContent === 'Projected range');
  return { text: c ? c.innerText.replace(/\s+/g, ' ') : '', chart: !!c?.querySelector('svg path'), est: [...document.querySelectorAll('#main .card > header h2')].some((x) => x.textContent === 'Battery capacity estimate'),
    sw: document.documentElement.scrollWidth, iw: window.innerWidth };
});
check('Battery shows the projected range with a trend chart and sample count, separate from the capacity estimate', /Projected range from reported range/.test(br.text) && /At 100 % charge \d{3} ?km/.test(br.text) && /Readings used [\d.,]+/.test(br.text) && br.chart && br.est, br.text.slice(0, 200));
check('The projected range card never says health and fits 360 px', br.text !== '' && !/health/i.test(br.text) && br.sw <= br.iw, `scrollWidth=${br.sw}/${br.iw}`);
await narrow.evaluate(() => { try { sessionStorage.removeItem('b-stats-tab'); } catch { /* optional */ } });
await narrow.close();

// ---------------------------------------------------------------- 2b. data-quality card on System
// The real demo has no important finding, so the card is first checked as is (renders, fits 360 px), then with fixtures.
const qp = await browser.newPage();
watch(qp);
await qp.setViewport({ width: 360, height: 800, isMobile: true, hasTouch: true });
await qp.goto(`${BASE}/#/system`, { waitUntil: 'networkidle0' });
await sleep(1500);
const qReal = await qp.evaluate(() => {
  const c = [...document.querySelectorAll('#main .card')].find((x) => x.querySelector('h2')?.textContent === 'Data quality');
  return { found: !!c, sw: document.documentElement.scrollWidth, iw: window.innerWidth, first: document.querySelector('#main .card h2')?.textContent };
});
check('System shows the Data quality card first and fits 360 px', qReal.found && qReal.first === 'Data quality' && qReal.sw <= qReal.iw, JSON.stringify(qReal));

// Backend `summary` and `label` texts carry RAW markers: the card must show its own translated words, never these.
const qItem = (id, severity, count, samples = [], fix = null, visible = true) => ({ id, severity, count, summary: `RAW_SUMMARY ${count} ${id}`, samples, fix, visible });
const qState = { open: 3, rich: false, failReview: false, failQuality: false }, qFixCalls = [], qRevCalls = [];
const qRev = {}, qNew = {}, qRevAt = '2026-11-20T10:00:00+00:00';
let qFixMode = '400';
const qReviewed = (it) => {
  const n = qNew[it.id], at = qRev[it.id] || null;
  if (n) return { ...it, count: n.count, total: n.total, reviewed_at: qRevAt, summary: it.summary };
  return { ...it, total: it.count || 2, count: at ? 0 : it.count, reviewed_at: at };
};
const qAt = '2026-11-01T10:00:00+00:00';
const qRich = [
  { kind: 'odometer', from_km: 12500, to_km: 12400, at: qAt, label: 'RAW odometer label', href: null },
  { kind: 'silence', from: qAt, to: '2026-11-01T20:00:00+00:00', hours: 10, label: 'RAW silence label', href: null },
  { kind: 'api_error', endpoint: 'get_vehicle', at: '2026-11-01T10:30:00+00:00', label: 'RAW api label', href: null },
  { kind: 'section', name: 'climate', label: 'RAW section label', href: null },
  { kind: 'gap', from: qAt, to: '2026-11-01T19:00:00+00:00', hours: 9, label: 'RAW gap label', href: null },
];
const qBody = () => JSON.stringify({ checked_at: '2026-11-26T10:00:00+00:00', checks: [
  qItem('open_trips', 'important', qState.open, qState.open ? [{ kind: 'trip', id: 7, at: qAt, label: 'RAW trip label', href: '#/trips/7' },
    { kind: 'gap', from: qAt, to: '2026-11-01T18:00:00+00:00', hours: 8, label: 'RAW gap label', href: null }, { kind: 'weird', label: 'Some plain label', href: null }] : [], 'close_open_trips'),
  qItem('open_charges', 'important', 0, [], 'close_open_charges'),
  qItem('estimated_charges', 'info', 2, [{ kind: 'charge', id: 4, at: '2026-11-02T10:00:00+00:00', label: 'RAW charge label', href: '#/charges/4' }]),
  qItem('reading_gaps', 'important', qState.rich ? 6 : 0, qState.rich ? qRich : []),
  qItem('stuck_operations', 'important', 2, [{ label: 'RAW stuck label', href: null }], null, false),
].map(qReviewed) });
const qIntercept = (req) => {
  const u = req.url();
  if (/\/api\/vehicles\/[^/]+\/quality\/review/.test(u)) {
    if (qState.failReview) { req.respond({ status: 500, contentType: 'application/json', body: '{"detail":"Review failed."}' }); return; }
    const b = JSON.parse(req.postData()); qRevCalls.push(req.postData());
    qRev[b.check] = b.reviewed ? qRevAt : null;
    if (!b.reviewed) delete qNew[b.check];
    req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ check: b.check, reviewed_at: qRev[b.check] }) });
  } else if (/\/api\/vehicles\/[^/]+\/quality\/fix/.test(u)) {
    qFixCalls.push(req.postData());
    if (qFixMode === '400') req.respond({ status: 400, contentType: 'application/json', body: '{"detail":"Unknown action."}' });
    else { qState.open = 0; req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ action: 'close_open_trips', changed: 3, message: 'ok' }) }); }
  } else if (/\/api\/vehicles\/[^/]+\/quality(\?|$)/.test(u)) {
    if (qState.failQuality) req.respond({ status: 500, contentType: 'application/json', body: '{"detail":"Quality unavailable."}' });
    else req.respond({ status: 200, contentType: 'application/json', body: qBody() });
  }
  else req.continue();
};
await qp.setRequestInterception(true);
qp.on('request', qIntercept);
await qp.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' });
await qp.goto(`${BASE}/#/system`, { waitUntil: 'networkidle0' });
await sleep(1500);
const qCard = () => qp.evaluate(() => {
  const c = [...document.querySelectorAll('#main .card')].find((x) => x.querySelector('h2')?.textContent === 'Data quality');
  return { text: c ? c.innerText.replace(/\s+/g, ' ') : '', rows: c ? [...c.querySelectorAll('.quality-row')].map((r) => r.dataset.check) : [],
    bad: c?.querySelectorAll('.chip.bad').length, warn: c?.querySelectorAll('.chip.warn').length, sw: document.documentElement.scrollWidth, iw: window.innerWidth,
    zero: c ? [...c.querySelectorAll('.quality-all .quality-row')].map((r) => ({ id: r.dataset.check, chips: r.querySelectorAll('.chip').length, none: /No findings/.test(r.textContent) })) : [],
    neutral: c ? [...c.querySelectorAll('.row.tight .chip')].filter((x) => !/\b(bad|warn|good|info)\b/.test(x.className)).map((x) => x.textContent.trim()) : [] };
});
const q1 = await qCard();
check('Quality card lists the two findings, severity chips, quiet line, zero checks hidden', q1.rows.slice(0, 2).join() === 'open_trips,estimated_charges' && q1.bad >= 1 && q1.warn >= 1
  && /Everything else looks consistent\./.test(q1.text) && /Show all checks/.test(q1.text) && q1.sw <= q1.iw, JSON.stringify(q1));
check('Quality card shows its own translated label, never the backend summary text or a raw id', /Trips that never ended/.test(q1.text) && !/RAW_SUMMARY|open_trips|estimated_charges/.test(q1.text), q1.text);
check('A check marked visible:false is nowhere on the card: no row, not under Show all checks, not in the header counts', !q1.rows.includes('stuck_operations') && !/stuck|Operations/i.test(q1.text)
  && q1.text.includes('1 Important') && q1.text.includes('1 Info') && q1.neutral.length === 0, JSON.stringify(q1));
check('Zero-count rows under Show all checks carry no severity chip, only "No findings"', q1.zero.length === 2 && q1.zero.every((z) => z.chips === 0 && z.none), JSON.stringify(q1.zero));
const reviewBtn = (id) => qp.evaluate((cid) => document.querySelector(`.quality-row[data-check="${cid}"] button`).click(), id);
const modalProbe = () => qp.evaluate(() => {
  const ms = [...document.querySelectorAll('.modal')], m = ms[ms.length - 1];
  return m ? { n: ms.length, title: m.querySelector('h2').textContent, text: m.innerText.replace(/\s+/g, ' '), links: [...m.querySelectorAll('a')].map((a) => `${a.textContent}>${a.getAttribute('href')}`),
    buttons: [...m.querySelectorAll('.actions button')].map((b) => b.textContent.trim()), banner: m.querySelector('.banner')?.textContent || '' } : null;
});
const modalBtn = (label) => qp.evaluate((txt) => { const ms = [...document.querySelectorAll('.modal')]; [...ms[ms.length - 1].querySelectorAll('button')].find((b) => b.textContent.trim() === txt).click(); }, label);
await reviewBtn('estimated_charges');
await sleep(300);
const m0 = await modalProbe();
check('Review of a check without fix shows the sample link with its date, "and 1 more" and no Fix button', m0 && m0.links.includes('Charge #4>#/charges/4') && /Charge #4, \w{3}, Nov 2/.test(m0.text)
  && /and 1 more/.test(m0.text) && !/RAW/.test(m0.text) && !m0.buttons.includes('Fix') && m0.buttons.includes('Close'), JSON.stringify(m0));
await modalBtn('Close');
await reviewBtn('open_trips');
await sleep(300);
const m1 = await modalProbe();
check('Review shows count, trip link, plain label and a Fix button', m1 && /Findings: 3/.test(m1.text) && m1.links.includes('Trip #7>#/trips/7') && /Gap: 8 h, .* → /.test(m1.text) && /Some plain label/.test(m1.text) && !/RAW/.test(m1.text) && !/and \d+ more/.test(m1.text)
  && m1.buttons.includes('Fix'), JSON.stringify(m1));
check('Review explains what Fix does before anyone clicks it', m1 && /What Fix does/.test(m1.text)
  && /first reading after its start that shows the car parked/.test(m1.text) && /approximate/.test(m1.text), JSON.stringify(m1));
await modalBtn('Fix');
await sleep(300);
const m2 = await modalProbe();
check('Fix asks for confirmation with the count', m2 && m2.n === 2 && m2.title === 'Apply this fix?' && /Findings this fix changes: 3\./.test(m2.text) && /Nothing is lost\./.test(m2.text), JSON.stringify(m2));
check('The confirmation says what the fix does and names the trips it changes', m2 && /first reading after its start that shows the car parked/.test(m2.text)
  && /Trip #7/.test(m2.text) && /Gap: 8 h/.test(m2.text) && !/RAW/.test(m2.text), JSON.stringify(m2));
// every way out of the confirmation resolves it: Escape and a scrim click close only the confirmation (the review stays),
// and the Fix button works again afterwards
await qp.keyboard.press('Escape');
await sleep(300);
const e1 = await modalProbe();
const fixBusy = () => qp.evaluate(() => { const ms = [...document.querySelectorAll('.modal')]; return [...(ms[ms.length - 1]?.querySelectorAll('.actions button') || [])].find((b) => b.textContent.trim() === 'Fix')?.classList.contains('busy'); });
const e1Busy = await fixBusy();
await modalBtn('Fix');
await sleep(300);
const e2 = await modalProbe();
await qp.evaluate(() => { const s = [...document.querySelectorAll('.scrim')].pop(); s.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
await sleep(300);
const e3 = await modalProbe();
await modalBtn('Fix');
await sleep(300);
const e4 = await modalProbe();
check('Escape closes only the confirmation and releases the Fix button', e1 && e1.n === 1 && e1.title !== 'Apply this fix?' && e1Busy === false, JSON.stringify({ e1, e1Busy }));
check('Fix asks again after Escape, a scrim click closes the confirmation too, and Fix asks once more, with no POST', e2 && e2.n === 2 && e3 && e3.n === 1 && e4 && e4.n === 2 && qFixCalls.length === 0,
  JSON.stringify({ e2, e3, e4, calls: qFixCalls.length }));
await modalBtn('Confirm');
await sleep(600);
const m3 = await modalProbe();
check('A 400 shows the message in a banner inside the modal, which stays open, nothing refreshed', m3 && m3.n === 1 && /Unknown action\./.test(m3.banner) && qFixCalls.length === 1 && JSON.parse(qFixCalls[0]).action === 'close_open_trips' && (await qCard()).rows[0] === 'open_trips', JSON.stringify(m3));
qFixMode = 'ok';
await modalBtn('Fix'); await sleep(300); await modalBtn('Confirm'); await sleep(1200);
const q2 = await qCard();
const toastText = await qp.evaluate(() => document.querySelector('.toasts')?.textContent || '');
check('A successful fix toasts the changed count, closes the modal and refreshes the card', /Fixed: 3/.test(toastText) && !(await modalProbe()) && q2.rows.join() === 'estimated_charges,open_trips,open_charges,reading_gaps' && q2.bad === 0, `${toastText} ${JSON.stringify(q2)}`);
// review and undo
await reviewBtn('estimated_charges');
await sleep(300);
const r0 = await modalProbe();
check('Review modal offers Mark as reviewed', r0 && r0.buttons.includes('Mark as reviewed'), JSON.stringify(r0));
// a failing review POST: banner inside the modal, modal stays, button released, no toast, nothing posted or refreshed
const clearToasts = () => qp.evaluate(() => document.querySelector('.toasts')?.replaceChildren());
await clearToasts();
qState.failReview = true;
await modalBtn('Mark as reviewed');
await sleep(600);
const rf = await modalProbe();
const rfBusy = await qp.evaluate(() => [...document.querySelectorAll('.modal .actions button')].some((b) => b.classList.contains('busy')));
const rfToast = await qp.evaluate(() => document.querySelector('.toasts')?.textContent || '');
check('A failed review POST shows the message in the modal, keeps it open, releases the button and toasts no success',
  rf && rf.n === 1 && /Review failed\./.test(rf.banner) && !rfBusy && !/Reviewed/.test(rfToast) && qRevCalls.length === 0, JSON.stringify({ rf, rfBusy, rfToast }));
qState.failReview = false;
// a double click on Mark as reviewed posts once
await qp.evaluate(() => { const b = [...document.querySelectorAll('.modal .actions button')].find((x) => x.textContent.trim() === 'Mark as reviewed'); b.click(); b.click(); });
await sleep(1200);
const r1 = await qCard();
const rToast = await qp.evaluate(() => document.querySelector('.toasts')?.textContent || '');
check('Review modal posts {check, reviewed:true} once (double click), toasts, closes and refreshes', qRevCalls.length === 1 && qRevCalls[0] === JSON.stringify({ check: 'estimated_charges', reviewed: true })
  && /Reviewed/.test(rToast) && !(await modalProbe()) && r1.rows.join() === 'open_trips,open_charges,estimated_charges,reading_gaps', `${qRevCalls[0]} ${rToast} ${JSON.stringify(r1)}`);
check('The header counts reviewed checks in a neutral chip, so an all-clear card is not ambiguous', r1.neutral.join() === '1 reviewed' && /Everything else looks consistent or was reviewed\./.test(r1.text), JSON.stringify(r1));
const rAll = () => qp.evaluate(() => {
  const a = document.querySelector('.quality-all');
  const row = a?.querySelector('.quality-row[data-check="estimated_charges"]');
  const c = [...document.querySelectorAll('#main .card')].find((x) => x.querySelector('h2')?.textContent === 'Data quality');
  const vis = [...(c?.querySelectorAll('.quality-row') || [])].filter((r) => !r.closest('.quality-all')).map((r) => r.dataset.check);
  return { inAll: !!row, text: row ? row.textContent.replace(/\s+/g, ' ') : '', undo: !![...(row?.querySelectorAll('button') || [])].find((b) => b.textContent.trim() === 'Undo'),
    vis, bad: c?.querySelectorAll('.chip.bad').length, warn: c?.querySelectorAll('.chip.warn').length, sw: document.documentElement.scrollWidth, iw: window.innerWidth,
    quiet: c ? c.innerText.replace(/\s+/g, ' ') : '' };
});
const r2 = await rAll();
check('A reviewed check with no new findings sits under Show all checks with Reviewed <date> and Undo', r2.inAll && /Reviewed \w{3}, Nov 20/.test(r2.text) && r2.undo && !r2.vis.includes('estimated_charges')
  && r2.warn === 0 && r2.bad === 0 && /Everything else looks consistent or was reviewed\./.test(r2.quiet) && r2.sw <= r2.iw, JSON.stringify(r2));
await qp.evaluate(() => [...document.querySelectorAll('.quality-all .quality-row[data-check="estimated_charges"] button')].find((b) => b.textContent.trim() === 'Undo').click());
await sleep(1200);
const r3 = await qCard();
check('Undo posts {check, reviewed:false} and refreshes with the full count', qRevCalls.length === 2 && qRevCalls[1] === JSON.stringify({ check: 'estimated_charges', reviewed: false })
  && r3.rows.join() === 'estimated_charges,open_trips,open_charges,reading_gaps' && r3.warn >= 1 && r3.neutral.length === 0, `${qRevCalls[1]} ${JSON.stringify(r3)}`);
qNew.open_charges = { count: 1, total: 3 };
qp.evaluate(() => [...document.querySelectorAll('#main .card button')].find((b) => b.textContent.trim() === 'Check again').click());
await sleep(1200);
const r4 = await qp.evaluate(() => {
  const row = document.querySelector('.quality-row[data-check="open_charges"]');
  return { vis: !!row && !row.closest('.quality-all'), text: row ? row.textContent.replace(/\s+/g, ' ') : '', sw: document.documentElement.scrollWidth, iw: window.innerWidth };
});
check('A reviewed check with new findings shows them marked new since <date>, and fits 360 px', r4.vis && /new since/.test(r4.text) && r4.sw <= r4.iw, JSON.stringify(r4));
// Review panel of a reviewed check with new findings and a fix: four footer buttons at 360 px, Undo from inside
await reviewBtn('open_charges');
await sleep(300);
const u0 = await qp.evaluate(() => {
  const ms = [...document.querySelectorAll('.modal')], m = ms[ms.length - 1];
  return m ? { buttons: [...m.querySelectorAll('.actions button')].map((b) => b.textContent.trim()),
    out: [...m.querySelectorAll('.actions button')].filter((b) => { const r = b.getBoundingClientRect(); return r.left < 0 || r.right > window.innerWidth; }).map((b) => b.textContent.trim()),
    icons: [...m.querySelectorAll('.actions button')].filter((b) => b.querySelector('svg')).map((b) => b.textContent.trim()),
    sw: document.documentElement.scrollWidth, iw: window.innerWidth } : null;
});
check('Review panel with Fix, Mark as reviewed and Undo fits 360 px: all four buttons inside the viewport, no sideways scroll',
  u0 && ['Close', 'Fix', 'Mark as reviewed', 'Undo'].every((x) => u0.buttons.includes(x)) && u0.out.length === 0 && u0.sw <= u0.iw, JSON.stringify(u0));
check('The Undo button in the review panel has an icon like Fix and Mark as reviewed', u0 && ['Fix', 'Mark as reviewed', 'Undo'].every((x) => u0.icons.includes(x)), JSON.stringify(u0));
await modalBtn('Undo');
await sleep(1200);
const u1 = await qCard();
const uToast = await qp.evaluate(() => document.querySelector('.toasts')?.textContent || '');
check('Undo in the review panel posts {check, reviewed:false}, toasts, closes and refreshes the card', qRevCalls[qRevCalls.length - 1] === JSON.stringify({ check: 'open_charges', reviewed: false })
  && /Review undone/.test(uToast) && !(await modalProbe()) && !/new since/.test(u1.text), `${qRevCalls[qRevCalls.length - 1]} ${uToast} ${JSON.stringify(u1)}`);
// every sample kind is rendered from its structured fields, translated words and formatted numbers and dates, never the English label
qState.rich = true;
const checkAgain = () => qp.evaluate(() => [...document.querySelectorAll('#main .card button')].find((b) => b.textContent.trim() === 'Check again').click());
await checkAgain();
await sleep(1200);
await reviewBtn('reading_gaps');
await sleep(300);
const k0 = await modalProbe();
check('Every sample kind (odometer, silence, API error, section, gap) is built from its fields with formatted numbers and dates, and "and 1 more" follows', k0
  && /Odometer 12,500 → 12,400 km, \w{3}, Nov 1/.test(k0.text) && /Silent since \w{3}, Nov 1 \(10 h\)/.test(k0.text) && /get_vehicle failed, \w{3}, Nov 1 .*\d/.test(k0.text)
  && /Section Climate data missing/.test(k0.text) && /Gap: 9 h, \w{3}, Nov 1 → \w{3}, Nov 1/.test(k0.text) && /and 1 more/.test(k0.text) && !/RAW/.test(k0.text), JSON.stringify(k0));
await modalBtn('Close');
qState.rich = false;
// the POST succeeds but the refresh after it fails: no success toast, the card shows its error
await checkAgain();
await sleep(1200);
await reviewBtn('estimated_charges');
await sleep(300);
const callsBefore = qRevCalls.length;
await clearToasts();
qState.failQuality = true;
await modalBtn('Mark as reviewed');
await sleep(1200);
const fr = await qCard();
const frToast = await qp.evaluate(() => document.querySelector('.toasts')?.textContent || '');
check('A failed refresh after a successful review POST shows the card error and no success toast', qRevCalls.length === callsBefore + 1 && /Could not load/.test(fr.text) && /Quality unavailable\./.test(fr.text)
  && !/Reviewed/.test(frToast) && !(await modalProbe()), JSON.stringify({ fr, frToast }));
qState.failQuality = false;
await checkAgain();
await sleep(1200);
qp.off('request', qIntercept);
await qp.setRequestInterception(false);
await qp.close();

// ---------------------------------------------------------------- 3. map clustering and its fallback
await d.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' });
await sleep(2500);
const clusters = await d.evaluate(() => document.querySelectorAll('.marker-cluster').length);
check('map clusters crowded pins', clusters > 0, `${clusters} cluster(s)`);
if (SHOTS) await d.screenshot({ path: `${SHOTS}/map-clusters.png` });
// The map names places: the home place is listed with a link to its detail page, the marker titles carry the place
// names, and every place has a filled, interactive circle. A circle click opens the place it stands for.
const mapPlaceInfo = await d.evaluate(async () => {
  const list = await fetch('/api/places').then((r) => r.json());
  const home = list.items.find((p) => p.kind === 'home');
  const text = document.getElementById('main').innerText;
  const el = document.querySelector('#main .map');
  const titles = [];
  el?.map?.eachLayer((layer) => {
    for (const l of (layer.getLayers ? layer.getLayers() : [layer])) if (l.options?.title) titles.push(l.options.title);
  });
  const circles = [...document.querySelectorAll('#main .leaflet-overlay-pane path.leaflet-interactive')]
    .filter((p) => p.getAttribute('fill') && p.getAttribute('fill') !== 'none');
  return { home: home?.name || '', count: list.items.length, inText: !!home && text.includes(home.name),
    link: !!home && !!document.querySelector(`#main a[href="#/places/${home.id}"]`), titles, circles: circles.length };
});
check('map list names the home place and links it', mapPlaceInfo.inText && mapPlaceInfo.link,
  `${mapPlaceInfo.home}: text=${mapPlaceInfo.inText} link=${mapPlaceInfo.link}`);
check('map markers carry place names', mapPlaceInfo.titles.some((t) => t.includes(mapPlaceInfo.home)),
  `${mapPlaceInfo.titles.length} title(s)`);
check('map draws an interactive circle for every place', mapPlaceInfo.circles >= mapPlaceInfo.count && mapPlaceInfo.count > 0,
  `${mapPlaceInfo.circles}/${mapPlaceInfo.count}`);
const circleHash = await d.evaluate(async () => {
  const circle = [...document.querySelectorAll('#main .leaflet-overlay-pane path.leaflet-interactive')]
    .find((p) => p.getAttribute('fill') && p.getAttribute('fill') !== 'none');
  if (!circle) return '';
  circle.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: 120, clientY: 120 }));
  await new Promise((r) => setTimeout(r, 600));
  return location.hash;
});
check('a map circle opens its place detail', /^#\/places\/\d+$/.test(circleHash), circleHash);
// R12: focusing one item fits that item, not every place. The focused paint used to pass every place circle, so "Show
// on map" for a charge or trip zoomed back out to the whole set. Focus a linked charge, then a trip, and check that
// only the focused place's circle remains and the charge view is centred on the charge and closer than all places.
await d.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' });
await sleep(2500);
const focusViews = await d.evaluate(async () => {
  const map = document.querySelector('#main .map')?.map;
  if (!map) return { error: 'no map' };
  const filled = () => [...document.querySelectorAll('#main .leaflet-overlay-pane path.leaflet-interactive')]
    .filter((p) => p.getAttribute('fill') && p.getAttribute('fill') !== 'none');
  const all = { zoom: map.getZoom(), circles: filled().length };
  const data = await fetch('/api/vehicles/1/map?limit=1000').then((r) => r.json());
  const placeIds = new Set((data.places || []).map((p) => p.id));
  const charges = (data.charges || []).filter((c) => c.lat != null && c.lon != null);
  const linked = charges.findIndex((c) => placeIds.has(c.geofence_id));
  const section = (re) => [...document.querySelectorAll('#main section')].find((s) => re.test(s.querySelector('h3')?.textContent || ''));
  const clickRow = (sec, i = 0) => {
    const row = [...(sec?.querySelectorAll('button.a-item') || [])][i];
    if (!row) return false;
    row.click();
    return true;
  };
  if (linked < 0 || !clickRow(section(/Charge locations/), linked)) return { error: 'no linked charge row' };
  await new Promise((r) => setTimeout(r, 700));
  const charge = { zoom: map.getZoom(), circles: filled().length, center: map.getCenter() };
  const tripBefore = map.getZoom();
  if (!clickRow(section(/Trip start and end/))) return { error: 'no trip row' };
  await new Promise((r) => setTimeout(r, 700));
  const trip = { zoom: map.getZoom(), before: tripBefore, circles: filled().length };
  return { all, charge, trip, target: charges[linked] };
});
check('map focus fits the chosen item, not every place', !!focusViews && !focusViews.error
  && focusViews.all.circles > 1 && focusViews.charge.circles === 1
  && Math.abs(focusViews.charge.center.lat - focusViews.target.lat) < 0.02
  && Math.abs(focusViews.charge.center.lng - focusViews.target.lon) < 0.02
  && focusViews.charge.zoom > focusViews.all.zoom && focusViews.trip.circles <= 1,
  focusViews ? (focusViews.error || `all z${focusViews.all.zoom}/${focusViews.all.circles}c charge z${focusViews.charge.zoom}/${focusViews.charge.circles}c trip z${focusViews.trip.before}→${focusViews.trip.zoom}/${focusViews.trip.circles}c`) : 'no result');
// The plugin is optional: with its files blocked the map must still show plain pins, without an error page or banner.
const fb = await browser.newPage();
watch(fb);
await fb.setRequestInterception(true);
fb.on('request', (req) => (req.url().includes('markercluster') ? req.abort() : req.continue()));
await fb.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' });
await sleep(2500);
const fallback = await fb.evaluate(() => ({ pins: document.querySelectorAll('#main .pin').length, text: document.getElementById('main').innerText }));
check('map falls back to plain pins without the cluster plugin', fallback.pins > 0 && !/Something went wrong/.test(fallback.text), `${fallback.pins} pin(s)`);
if (SHOTS) await fb.screenshot({ path: `${SHOTS}/map-fallback.png` });
await fb.close();

// ---------------------------------------------------------------- 4. a place's own rate explains a charge's cost
// Give the place of a charge a price for the duration of the check, then read the real charge page and put the price back.
const pricedCharge = await d.evaluate(async () => {
  const list = await fetch('/api/vehicles/1/charges?limit=20').then((r) => r.json());
  const charge = (list.items || []).find((x) => x.place?.id && x.cost_basis === 'tariff');
  if (!charge) return null;
  const previous = await fetch(`/api/places/${charge.place.id}`).then((r) => r.json());
  await fetch(`/api/places/${charge.place.id}`, { method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ...previous, price_kwh: 0.42 }) });
  return { charge: charge.id, place: charge.place.id, name: charge.place.name, before: previous };
});
if (pricedCharge) {
  await d.goto(`${BASE}/#/charges/${pricedCharge.charge}`, { waitUntil: 'networkidle0' });
  await sleep(1500);
  const placeCost = await d.evaluate((id, name) => ({
    text: document.getElementById('main').innerText,
    link: [...document.querySelectorAll('#main a[href^="#/places/"]')]
      .some((a) => a.getAttribute('href') === `#/places/${id}` && a.textContent.includes(name)),
  }), pricedCharge.place, pricedCharge.name);
  check('a place rate explains the charge cost and links the place',
    /Cost uses the price of this place\./.test(placeCost.text) && placeCost.link, `place ${pricedCharge.name}`);
  await d.evaluate(async (id, before) => {
    await fetch(`/api/places/${id}`, { method: 'PUT', headers: { 'content-type': 'application/json' },
      body: JSON.stringify(before) });
  }, pricedCharge.place, pricedCharge.before);
} else {
  check('a place rate explains the charge cost and links the place', false, 'no place-linked charge found');
}

// ---------------------------------------------------------------- 5. the home place card links to its place
// The prices page no longer carries a home map or coordinate fields: the home place lives on the Places page, and this
// card summarizes it (radius, visits) with a link to its detail page plus "Use current parking position".
await d.goto(`${BASE}/#/prices`, { waitUntil: 'networkidle0' });
await sleep(1500);
const homeCard = await d.evaluate(async () => {
  const list = await fetch('/api/places').then((r) => r.json());
  const home = (list.items || []).find((p) => p.kind === 'home');
  const card = [...document.querySelectorAll('#main .card')]
    .find((c) => /Home place/.test(c.querySelector('h2')?.textContent || ''));
  const link = card?.querySelector('a[href^="#/places/"]');
  return {
    id: home?.id ?? null,
    href: link?.getAttribute('href') || '',
    text: card?.innerText || '',
    button: [...(card?.querySelectorAll('button') || [])].some((b) => /Use current parking position/.test(b.textContent)),
    map: !!document.querySelector('#main .leaflet-container'),
    coords: document.querySelectorAll('#main .grid.g3 input[type=number]').length,
  };
});
check('the prices home card links to the home place',
  homeCard.id != null && homeCard.href === `#/places/${homeCard.id}` && /Edit home place/.test(homeCard.text)
  && homeCard.button && !homeCard.map && homeCard.coords === 0,
  `place=${homeCard.id} link=${homeCard.href} button=${homeCard.button} map=${homeCard.map} coords=${homeCard.coords}`);

// ---------------------------------------------------------------- 6. the places form keeps its draft across a map pick
// R9: the form is modal, so "Pick on the map" closes it and keeps the draft; the next map click reopens the same form at
// the new point with the name and colour still filled in. This drives the real page, then reads the saved place back.
const draftName = `Pick test ${Date.now()}`;
const DRAFT_COLOUR = '#0e7a7a';
const readForm = (colour) => {
  const modal = document.querySelector('.modal');
  if (!modal) return null;
  return {
    name: modal.querySelector('input[type=text]')?.value || '',
    colour: [...modal.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === colour))?.value || '',
    point: modal.querySelector('.pl-coords div div')?.textContent.trim() || '',
    pick: [...modal.querySelectorAll('button')].some((b) => /Pick on the map/.test(b.textContent)),
  };
};
await d.goto(`${BASE}/#/places`, { waitUntil: 'networkidle0' });
await sleep(1800);
const formBefore = await d.evaluate((name, colour) => {
  [...document.querySelectorAll('#main button')].find((b) => /Add place/.test(b.textContent))?.click();
  const modal = document.querySelector('.modal');
  if (!modal) return null;
  const text = modal.querySelector('input[type=text]');
  text.value = name; text.dispatchEvent(new Event('input', { bubbles: true }));
  const select = [...modal.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === colour));
  select.value = colour; select.dispatchEvent(new Event('change', { bubbles: true }));
  const hint = () => [...modal.querySelectorAll('p.tiny.muted')].find((p) => /free place cannot have a price/i.test(p.textContent));
  const freeBox = modal.querySelector('input[type=checkbox]');
  const freeHintOff = hint()?.hidden === true;  // no price warning while the place is not free
  freeBox.click();
  const freeHintOn = hint()?.hidden === false;
  freeBox.click();
  const kind = [...modal.querySelectorAll('select')].find((s) => [...s.options].some((o) => o.value === 'home'));
  return {
    name: text.value, colour: select.value,
    point: modal.querySelector('.pl-coords div div')?.textContent.trim() || '',
    pick: [...modal.querySelectorAll('button')].some((b) => /Pick on the map/.test(b.textContent)),
    homeOff: [...(kind?.options || [])].find((o) => o.value === 'home')?.disabled === true,
    freeHint: freeHintOff && freeHintOn,
  };
}, draftName, DRAFT_COLOUR);
check('places form offers "Pick on the map"', !!formBefore?.pick, formBefore?.point);
check('a second home cannot be chosen from the kind selector', !!formBefore?.homeOff);
check('the free-price warning shows only while Free is checked', !!formBefore?.freeHint);
let picked = null;
let picking = null;
if (formBefore?.pick) {
  await d.evaluate(() => [...document.querySelectorAll('.modal button')].find((b) => /Pick on the map/.test(b.textContent)).click());
  await sleep(400);
  picking = await d.evaluate(() => ({
    modal: !!document.querySelector('.modal'),
    hint: document.querySelector('#main .banner.info')?.textContent.trim() || '',
    map: !!document.querySelector('#main .map.leaflet-container'),
  }));
  check('"Pick on the map" closes the form and waits for a map click', !picking.modal && /map/i.test(picking.hint) && picking.map, picking.hint);
  // Any click on the map is a point; the corners are the emptiest spots, and a retry keeps a stray pin from failing it.
  for (const [fx, fy] of [[0.12, 0.85], [0.88, 0.15], [0.5, 0.8]]) {
    const box = await d.evaluate((x, y) => {
      const map = document.querySelector('#main .map.leaflet-container');
      if (!map) return null;
      map.scrollIntoView({ block: 'center' });
      const b = map.getBoundingClientRect();
      return { x: b.left + b.width * x, y: b.top + b.height * y };
    }, fx, fy);
    if (!box) break;
    await d.mouse.click(box.x, box.y);
    await sleep(600);
    picked = await d.evaluate(readForm, DRAFT_COLOUR);
    if (picked) break;
  }
  check('the next map click reopens the same form with the draft intact',
    !!picked && picked.name === draftName && picked.colour === DRAFT_COLOUR && picked.point !== formBefore.point,
    picked ? `${picked.name} / ${picked.colour} / ${formBefore.point} → ${picked.point}` : 'form did not reopen');
}
let savedDraft = null;
if (picked) {
  await d.evaluate(() => [...document.querySelectorAll('.modal button')].find((b) => b.textContent.trim() === 'Save').click());
  await sleep(1600);
  savedDraft = await d.evaluate(async (name) => {
    const list = await fetch('/api/places').then((r) => r.json());
    const place = list.items.find((p) => p.name === name);
    if (!place) return null;
    const out = { lat: place.lat, lon: place.lon, color: place.color };
    await fetch(`/api/places/${place.id}`, { method: 'DELETE' });  // keep the demo database as it was
    return out;
  }, draftName);
}
const pickedLatLon = (picked?.point || '').split(', ').map(Number);
check('the picked point is saved with the chosen colour',
  !!savedDraft && Math.abs(savedDraft.lat - pickedLatLon[0]) < 0.001 && Math.abs(savedDraft.lon - pickedLatLon[1]) < 0.001
    && savedDraft.color === DRAFT_COLOUR,
  savedDraft ? `${savedDraft.lat},${savedDraft.lon} ${savedDraft.color}` : 'place was not saved');

const before = await d.evaluate(() => fetch('/health').then((r) => r.json()));
await d.evaluate(() => [...document.querySelectorAll('.topbar button')].find((b) => /Refresh now/.test(b.textContent)).click());
await sleep(1800);
check('"Refresh now" works and shows a confirmation', await d.evaluate(() => /Updated from Škoda/.test(document.querySelector('.toasts')?.textContent || '')));

// a command through the Control page: charge limit 90
await d.goto(`${BASE}/#/control`, { waitUntil: 'networkidle0' });
await sleep(1200);
await d.evaluate(() => { const r = document.querySelector('input[type=range]'); r.value = 90; r.dispatchEvent(new Event('input', { bubbles: true })); r.dispatchEvent(new Event('change', { bubbles: true })); });
await d.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Set limit').click());
await sleep(1500);
const cmds = await d.evaluate(() => fetch('/api/vehicles/1/commands').then((r) => r.json()));
check('Control → "Set limit" sends the command (logged, accepted)', cmds.log[0]?.name === 'set_charge_limit' && cmds.log[0]?.ok === 1 && cmds.log[0]?.params?.percent === 90, JSON.stringify(cmds.log[0]?.params));

// ---------------------------------------------------------------- Settings → Automation (webhooks), on a 360 px phone
const au = await browser.newPage();
watch(au);
await au.setViewport({ width: 360, height: 780, isMobile: true, hasTouch: true });
await au.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle0' });
await sleep(1500);
const auProbe = () => au.evaluate(() => {
  const card = document.querySelector('#main .au-card'), dialog = [...document.querySelectorAll('.modal')].pop();
  const outside = [...(dialog || card).querySelectorAll('button, input')].filter((el) => el.getClientRects().length && el.getBoundingClientRect().right > window.innerWidth + 1).length;
  return { card: card?.innerText.replace(/\s+/g, ' ') || '', dialog: dialog?.innerText.replace(/\s+/g, ' ') || '', title: dialog?.querySelector('h2')?.textContent || '',
    secret: dialog?.querySelector('input.au-secret')?.value || '', hooks: card?.querySelectorAll('.au-hook').length || 0, outside,
    sw: document.documentElement.scrollWidth, iw: window.innerWidth, dialogScrolls: dialog ? dialog.scrollWidth > dialog.clientWidth + 1 : false };
});
const auClick = async (label, scope = '.au-card') => {
  await au.evaluate((l, s) => [...([...document.querySelectorAll(s)].pop()).querySelectorAll('button')].find((b) => b.textContent.trim() === l).click(), label, scope);
  await sleep(900);
};
const au0 = await auProbe();
check('Automation card lists the disabled demo webhook and fits 360 px', au0.hooks >= 1 && /Home Assistant \(example\)/.test(au0.card) && /Disabled/.test(au0.card) && au0.sw <= au0.iw && au0.outside === 0, JSON.stringify({ hooks: au0.hooks, sw: au0.sw, outside: au0.outside }));
await auClick('Add webhook');
await auClick('Save', '.modal');
const auBad = await auProbe();
check('Automation: an incomplete webhook is refused with a plain message and the form stays', auBad.title === 'Add webhook' && /Enter a name of 1 to 60 characters\./.test(auBad.dialog) && auBad.sw <= auBad.iw && !auBad.dialogScrolls && auBad.outside === 0, `${auBad.title} outside=${auBad.outside}`);
await au.type('.modal input[maxlength="60"]', 'Browser check');
await au.type('.modal input[type="url"]', 'http://127.0.0.1:9/closed-port');  // nothing listens there: the test must fail visibly
await au.evaluate(() => [...document.querySelectorAll('.modal .au-group input')].slice(0, 3).forEach((i) => i.click()));
await auClick('Save', '.modal');
const auSecret = await auProbe();
check('Automation: the new secret is shown once', auSecret.title === 'Signing secret' && auSecret.secret.length >= 32 && /will not show it again/.test(auSecret.dialog) && !auSecret.dialogScrolls, `${auSecret.title}, ${auSecret.secret.length} characters`);
await auClick('Done', '.modal');
const leaked = await au.evaluate((s) => fetch('/api/webhooks').then((r) => r.text()).then((x) => x.includes(s) || document.body.innerHTML.includes(s)), auSecret.secret);
const au1 = await auProbe();
check('Automation: the webhook is listed and its secret is nowhere any more', au1.hooks === au0.hooks + 1 && /Browser check/.test(au1.card) && !leaked && au1.sw <= au1.iw, `hooks=${au1.hooks} leaked=${leaked}`);
const lastHook = (label) => au.evaluate((l) => [...[...document.querySelectorAll('#main .au-hook')].pop().querySelectorAll('button')].find((b) => b.textContent.trim() === l).click(), label);
await lastHook('Send test');
await sleep(1500);
await lastHook('Deliveries');
await sleep(900);
const auLog = await auProbe();
check('Automation: a failed test is in the delivery log with its reason and a retry', /Test/.test(auLog.dialog) && /Failed/.test(auLog.dialog) && /Could not connect to the receiver\./.test(auLog.dialog) && /Retry/.test(auLog.dialog) && !auLog.dialogScrolls && auLog.outside === 0, auLog.dialog.slice(0, 160));
await auClick('Close', '.modal');
await lastHook('Edit');
await sleep(500);
await auClick('Delete', '.modal');
await auClick('Delete', '.modal');
const au2 = await auProbe();
check('Automation: deleting asks first and removes the webhook', au2.hooks === au0.hooks && !/Browser check/.test(au2.card), `hooks=${au2.hooks}`);
await au.close();

// settings: miles + German
await d.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle0' });
await sleep(1200);
const press = (label) => d.evaluate((txt) => [...document.querySelectorAll('.seg button')].find((b) => b.textContent.trim() === txt).click(), label);
await press('Miles'); await d.select('#set-lang', 'de');
await d.evaluate(() => { window.__stillTheSamePage = true; });
await d.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Save').click());
await sleep(1500);
const inGerman = await d.evaluate(() => document.documentElement.lang);
// the header changes language with the rest, not only at the next 30-second tick
const bar = await d.evaluate(() => document.querySelector('.topbar').textContent);
check('the header changes language at once', /Jetzt aktualisieren/.test(bar) && !/Refresh now|next check in/.test(bar), bar.slice(0, 120));
await d.select('#set-lang', 'en');
await d.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Speichern').click());
await sleep(1500);
const inEnglishAgain = await d.evaluate(() => ({ lang: document.documentElement.lang, same: window.__stillTheSamePage === true,
  nav: [...document.querySelectorAll('.sidebar .nav a')].map((a) => a.textContent.trim()).join(',') }));
check('switching to German and back updates <html lang> and the navigation without a reload',
  inGerman === 'de' && inEnglishAgain.lang === 'en' && inEnglishAgain.same && /Overview/.test(inEnglishAgain.nav) && !/Übersicht/.test(inEnglishAgain.nav),
  `${inGerman} -> ${inEnglishAgain.lang} ${inEnglishAgain.nav}`);
await d.select('#set-lang', 'de');
await d.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Save').click());
await sleep(1500);
const nav = await d.evaluate(() => [...document.querySelectorAll('.sidebar .nav a')].map((a) => a.textContent.trim()).join(','));
check('German applies immediately (navigation translated)', /Übersicht/.test(nav) && /Fahrten/.test(nav) && /Einstellungen/.test(nav), nav);
await d.goto(`${BASE}/#/`, { waitUntil: 'networkidle0' });
await sleep(1800);
const ov = await d.evaluate(() => document.getElementById('main').innerText);
check('miles are used on the Overview (odometer in mi)', /\bmi\b/.test(ov) && !/ km\b/.test(ov.replace(/km\/h/g, '')), ov.match(/[\d,.]+\s*(mi|km)/g)?.slice(0, 3).join(' | '));
const untranslated = ['Last trip', 'Quick controls', 'Battery, last 48 hours', 'Last charge'].filter((s) => ov.includes(s));  // ("Position" is the same word in German)
check('Overview text is German (no English headings left)', untranslated.length === 0, untranslated.join(', '));
for (const r of ['trips', 'charges', 'control', 'stats', 'settings', 'system']) {
  await d.goto(`${BASE}/#/${r}`, { waitUntil: 'networkidle0' }); await sleep(1300);
  const t = await d.evaluate(() => document.getElementById('main').innerText);
  const eng = ['Export CSV', 'Total distance', 'Start charging', 'Request budget', 'Home position', 'How these numbers are made'].filter((s) => t.includes(s));
  check(`German #/${r}`, eng.length === 0, eng.join(', '));
}
await d.goto(`${BASE}/#/stats`, { waitUntil: 'networkidle0' }); await sleep(1300);
for (const [tab, eng] of [['Laden', ['Energy charged', 'Average power', 'Top charging places', 'When charging starts', 'Charge curve']], ['Fahren', ['Top destinations', 'Trip lengths', 'Longest trips', 'Consumption trend', 'Projected distance']]]) {
  await d.evaluate((l) => [...document.querySelectorAll('#main .seg button')].find((b) => b.textContent === l)?.click(), tab);
  await sleep(1300);
  const t = await d.evaluate(() => document.getElementById('main').innerText);
  const left = eng.filter((s) => t.includes(s));
  check(`German Statistics ${tab}`, left.length === 0 && t.length > 200, left.join(', '));
}
await d.goto(`${BASE}/#/battery`, { waitUntil: 'networkidle0' }); await sleep(1500);
const bde = await d.evaluate(() => document.getElementById('main').innerText);
check('German projected range', /Hochgerechnete Reichweite/.test(bde) && !/Projected range|Readings used/.test(bde), bde.slice(0, 80));
await d.evaluate(() => { try { sessionStorage.removeItem('b-stats-tab'); } catch { /* optional */ } });
await d.goto(`${BASE}/#/places/1`, { waitUntil: 'networkidle0' }); await sleep(1500);
const pde = await d.evaluate(() => document.getElementById('main').innerText);
const pEng = ['Recent visits', 'Recent charges', 'Parked time', 'Back to places', 'Arrival', 'Departure', 'Edit place', 'Date', 'Charged', 'Visits', 'Days'].filter((s) => pde.includes(s));
check('German #/places/1', pEng.length === 0, pEng.join(', '));
await d.goto(`${BASE}/#/map`, { waitUntil: 'networkidle0' }); await sleep(1600);
const mde = await d.evaluate(() => document.getElementById('main').innerText);
const mEng = ['Parked places', 'Charge locations', 'Trip start and end', 'Show on map', 'last seen', 'Visits', 'Days', 'Car now', 'Click a circle'].filter((s) => mde.includes(s));
check('German #/map', mEng.length === 0, mEng.join(', '));
await d.goto(`${BASE}/#/places/999999`, { waitUntil: 'networkidle0' }); await sleep(1200);
const pdeMissing = await d.evaluate(() => document.getElementById('main').innerText);
check('German place not found', /Ort nicht gefunden\./.test(pdeMissing) && !/Place not found/.test(pdeMissing), pdeMissing.slice(0, 80));
// Activity List tab: a data-quality repair and review read as words in the user's language, never the raw kind/detail
const qev = await browser.newPage();
watch(qev);
await qev.setRequestInterception(true);
qev.on('request', (req) => {
  if (!/\/api\/vehicles\/[^/]+\/events(\?|$)/.test(req.url())) { req.continue(); return; }
  req.respond({ status: 200, contentType: 'application/json', body: JSON.stringify({ total: 2, kinds: ['quality_fix', 'quality_review'], items: [
    { id: 2, vehicle_id: 1, at: '2026-11-26T10:05:00+00:00', kind: 'quality_fix', detail: 'close_open_trips:3' },
    { id: 1, vehicle_id: 1, at: '2026-11-26T10:00:00+00:00', kind: 'quality_review', detail: 'open_trips:on' }] }) });
});
await qev.goto(`${BASE}/#/events`, { waitUntil: 'networkidle0' }); await sleep(1200);
await qev.evaluate(() => document.querySelectorAll('#main .seg button')[1].click());
await sleep(1200);
const qevText = await qev.evaluate(() => [...document.querySelectorAll('#main .b-event')].map((e) => e.innerText.replace(/\s+/g, ' ')).join(' | '));
check('German Activity List shows quality events translated, not raw',
  /Daten korrigiert/.test(qevText) && /Offene Fahrten abschließen: 3 geändert/.test(qevText) && /Daten geprüft/.test(qevText)
    && /Fahrten ohne Ende: als geprüft markiert/.test(qevText) && !/quality|close open|open trips|_/i.test(qevText), qevText);
await qev.close();
await d.goto(`${BASE}/#/trips`, { waitUntil: 'networkidle0' }); await sleep(1500);
if (SHOTS) await d.screenshot({ path: `${SHOTS}/german-trips.png` });
// restore and finish
await d.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ units: 'km', language: 'en' }) }));
// a fake, longer language: text that bypasses t() shows up, and every page must still fit a narrow phone
await pseudoPass(browser, BASE, check, errors);
// and every real language that is offered must fit it too
for (const language of (await (await fetch(`${BASE}/api/settings`)).json()).languages.filter((l) => l.code !== 'en')) {
  await layoutPass(browser, BASE, language, check, errors);
}
check('no JavaScript errors during the whole session', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `\n${failed} check(s) FAILED` : '\nend-to-end OK');
process.exit(failed ? 1 : 0);

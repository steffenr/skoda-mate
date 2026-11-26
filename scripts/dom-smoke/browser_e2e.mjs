// Real-browser end-to-end check (puppeteer-core + installed Chromium) against a running DEMO server.
//   npm install puppeteer-core --no-save   (once)   then:   BASE=http://localhost:8765 node browser_e2e.mjs
// 1. phone viewport: every page must fit the screen (no horizontal scroll) and nothing may throw
// 2. click-through: navigation, refresh, a command, a setting, units, language, the mobile "More" menu
import puppeteer from 'puppeteer-core';

const BASE = process.env.BASE || 'http://localhost:8765';
const SHOTS = process.env.SHOTS || '';
const CHROME = process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium';
const ROUTES = ['', 'trips', 'trips/5', 'charges', 'charges/3', 'battery', 'control', 'stats', 'map', 'places', 'places/1', 'events', 'settings', 'system'];
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
const labels = ['Trips', 'Charges', 'Battery', 'Control', 'Statistics', 'Map', 'Places', 'Events', 'Settings', 'System'];
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

// ---------------------------------------------------------------- 5. the legacy ownerless circle must not swallow map clicks
// The prices page draws a bare `circle` (a radius hint, no id) and asks the user to click the map to place the home pin.
// Under R8 only a circle that identifies a place (id) is interactive, so this one has to stay click-through.
await d.goto(`${BASE}/#/prices`, { waitUntil: 'networkidle0' });
await d.waitForSelector('#main .map.leaflet-container', { timeout: 10000 }).catch(() => {});
await sleep(1200);
const clickPlace = await d.evaluate(() => {
  const coords = () => [...document.querySelectorAll('#main .grid.g3 input[type=number]')];
  const radius = coords()[2];
  if (!radius) return null;
  radius.value = '5000';  // cover the whole viewport, so the click below is certainly inside the circle
  radius.dispatchEvent(new Event('input', { bubbles: true }));
  const map = document.querySelector('#main .map.leaflet-container');
  if (!map) return null;
  map.scrollIntoView({ block: 'center' });
  const b = map.getBoundingClientRect();
  return { x: b.left + b.width * 0.7, y: b.top + b.height * 0.7, before: coords().slice(0, 2).map((i) => i.value) };
});
await sleep(600);
if (clickPlace) await d.mouse.click(clickPlace.x, clickPlace.y);
await sleep(400);
const placed = await d.evaluate(() => ({
  latlon: [...document.querySelectorAll('#main .grid.g3 input[type=number]')].slice(0, 2).map((i) => i.value),
  circles: document.querySelectorAll('#main .leaflet-overlay-pane path').length,
  interactive: document.querySelectorAll('#main .leaflet-overlay-pane path.leaflet-interactive').length,
}));
check('ownerless circle keeps click-to-place on the prices map',
  !!clickPlace && placed.circles > 0 && placed.interactive === 0 && placed.latlon[0] !== clickPlace.before[0] && placed.latlon[1] !== clickPlace.before[1],
  `circle=${placed.circles} interactive=${placed.interactive} ${clickPlace?.before.join(',')} → ${placed.latlon.join(',')}`);

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

// settings: miles + German
await d.goto(`${BASE}/#/settings`, { waitUntil: 'networkidle0' });
await sleep(1200);
const press = (label) => d.evaluate((txt) => [...document.querySelectorAll('.seg button')].find((b) => b.textContent.trim() === txt).click(), label);
await press('Miles'); await press('Deutsch');
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
await d.goto(`${BASE}/#/trips`, { waitUntil: 'networkidle0' }); await sleep(1500);
if (SHOTS) await d.screenshot({ path: `${SHOTS}/german-trips.png` });
// restore and finish
await d.evaluate(() => fetch('/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ units: 'km', language: 'en' }) }));
check('no JavaScript errors during the whole session', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();
console.log(failed ? `\n${failed} check(s) FAILED` : '\nend-to-end OK');
process.exit(failed ? 1 : 0);

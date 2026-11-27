// Every text the dashboard shows, per language and view, so a change to the translation system can be compared with the
// interface before it. Needs a DEMO server; it changes the demo's language, units and theme.
//   BASE=http://localhost:8766 node text_snapshot.mjs out.json        (LANGS=de captures one language; out.json is merged)
//   node text_snapshot.mjs --diff before.json after.json              (exit 1 on any difference)
// Compare two servers started on the same day: the demo data moves with the date.
import fs from 'node:fs';

const KNOWN_LANGS = ['en', 'de'];

function diff(a, b) {
  let changed = 0;
  for (const view of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort()) {
    const before = new Set(a[view] || []);
    const after = new Set(b[view] || []);
    const removed = [...before].filter((x) => !after.has(x));
    const added = [...after].filter((x) => !before.has(x));
    if (!removed.length && !added.length && !!a[view] === !!b[view]) continue;
    changed++;
    console.log(`== ${view}${a[view] ? '' : ' (new view)'}${b[view] ? '' : ' (view gone)'}`);
    for (const x of removed) console.log(`  - ${x}`);
    for (const x of added) console.log(`  + ${x}`);
  }
  console.log(changed ? `${changed} view(s) differ` : `no difference in ${Object.keys(a).length} views`);
  return changed ? 1 : 0;
}

const read = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));
if (process.argv[2] === '--diff') process.exit(diff(read(process.argv[3]), read(process.argv[4])));

const out = process.argv[2];
if (!out) { console.error('usage: node text_snapshot.mjs <out.json> | --diff <a.json> <b.json>'); process.exit(2); }

const { default: puppeteer } = await import('puppeteer-core');
const BASE = process.env.BASE || 'http://localhost:8766';
const CHROME = process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium';
const LANGS = (process.env.LANGS || KNOWN_LANGS.join(',')).split(',');
const WAIT = +(process.env.WAIT || 1200);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ROUTES = ['', 'trips', 'trips/5', 'trips/999999', 'charges', 'charges/3', 'charges/999999', 'prices', 'battery', 'control', 'stats', 'map',
  'places', 'places/1', 'places/999999', 'events', 'settings', 'system', 'system/capabilities', 'system/calls', 'system/diagnostics',
  'import', 'no-such-page'];
// Views with tabs: the buttons are pressed by position, which does not depend on the language.
const TABBED = ['trips', 'stats', 'events'];

/** Digits and calendar names change from run to run and day to day; the wording around them is what is compared. */
function normaliser(lang) {
  const names = new Set();
  for (const style of ['long', 'short']) {
    for (let i = 0; i < 12; i++) {
      for (const day of ['numeric', undefined]) {
        const parts = new Intl.DateTimeFormat(lang, { month: style, day, timeZone: 'UTC' }).formatToParts(new Date(Date.UTC(2024, i, 15)));
        names.add(parts.find((p) => p.type === 'month').value);
      }
    }
    for (let i = 0; i < 7; i++) names.add(new Intl.DateTimeFormat(lang, { weekday: style, timeZone: 'UTC' }).format(new Date(Date.UTC(2024, 0, 1 + i))));
  }
  const words = [...names].map((n) => n.replace(/\.$/, '')).sort((x, y) => y.length - x.length);
  const calendar = new RegExp(`(?<![\\p{L}])(?:${words.join('|')})(?![\\p{L}])\\.?`, 'gu');
  const digits = (s) => s.replace(/\d+/g, '0').replace(/0(?:[.,:]0)+/g, '0');
  // "just now" or "5 minutes ago" depends on the second the page was read. Only this language's own wording is folded,
  // so an English phrase left on a German page still shows up.
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
  const ago = new Set([{ en: 'just now', de: 'gerade eben' }[lang]]);
  for (const unit of ['minute', 'hour', 'day']) for (const n of unit === 'day' ? [5] : [0, 1, 5]) ago.add(digits(rtf.format(-n, unit)));
  const relative = new RegExp([...ago].filter(Boolean).sort((x, y) => y.length - x.length).join('|'), 'gi');
  return (line) => digits(line.replace(/\s+/g, ' ').trim().replace(calendar, '<date>')).replace(relative, '<ago>');
}

/** Visible lines, plus the texts only a tooltip, a screen reader or an empty field shows. */
const collect = (page, selector) => page.evaluate((sel) => {
  const root = document.querySelector(sel);
  if (!root) return [];
  for (const d of root.querySelectorAll('details')) d.open = true;
  const lines = root.innerText.split(/\n|\t/);
  for (const e of [root, ...root.querySelectorAll('*')]) {
    for (const a of ['title', 'aria-label', 'placeholder']) if (e.getAttribute(a)) lines.push(`[${a}] ${e.getAttribute(a)}`);
    if (e.tagName === 'OPTION' || e.tagName.toLowerCase() === 'title') lines.push(e.textContent);
  }
  return lines;
}, selector);

// A server that was just started answers a moment later.
for (let i = 0; ; i++) {
  if (await fetch(`${BASE}/health`).then((r) => r.ok, () => false)) break;
  if (i === 60) throw new Error(`no server at ${BASE}`);
  await sleep(500);
}

const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
const result = fs.existsSync(out) ? read(out) : {};
try {
  for (const lang of LANGS) {
    const clean = normaliser(lang);
    const page = await browser.newPage();
    await page.setViewport({ width: 1200, height: 900 });
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle0' });
    const status = await page.evaluate((language) => fetch('/api/settings', {
      method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ language, units: 'km', theme: 'dark' }),
    }).then((r) => r.status), lang);
    if (status !== 200) throw new Error(`could not set the language to ${lang}: HTTP ${status}`);
    const keep = (view, lines) => { result[`${lang} ${view}`] = [...new Set(lines.map(clean).filter(Boolean))].sort(); };
    const open = async (route) => {
      // A full load per view: no toast, remembered tab or draft from the view before.
      await page.goto('about:blank');
      await page.goto(`${BASE}/#/${route}`, { waitUntil: 'networkidle0' });
      await page.evaluate(() => sessionStorage.clear());
      await sleep(WAIT);
    };
    for (const route of ROUTES) {
      await open(route);
      await collect(page, 'body');      // opening <details> can load more
      await sleep(250);
      keep(`#/${route}`, await collect(page, 'body'));
      if (!TABBED.includes(route)) continue;
      const tabs = await page.evaluate(() => document.querySelector('#main .seg')?.querySelectorAll('button').length || 0);
      for (let i = 1; i < tabs; i++) {
        await page.evaluate((n) => document.querySelector('#main .seg').querySelectorAll('button')[n].click(), i);
        await sleep(WAIT);
        await collect(page, '#main');
        await sleep(250);
        keep(`#/${route} tab ${i}`, await collect(page, '#main'));
      }
      await page.evaluate(() => { document.querySelector('#main .seg')?.querySelector('button')?.click(); });
      await sleep(300);
    }
    await page.setViewport({ width: 360, height: 780, isMobile: true, hasTouch: true });
    await open('');
    await page.evaluate(() => document.querySelector('.tabbar button').click());
    await sleep(300);
    keep('More menu (360 px)', await collect(page, '.scrim'));
    await page.close();
    console.log(`${lang}: ${Object.keys(result).filter((k) => k.startsWith(`${lang} `) || k === `${lang} More menu (360 px)`).length} views`);
  }
} finally {
  await browser.close();
}
fs.writeFileSync(out, `${JSON.stringify(Object.fromEntries(Object.entries(result).sort()), null, 1)}\n`);

// A fake language to catch what English and German cannot show. The request for de.json is answered with a catalog made
// from keys.json: accented, wrapped in ⟦…⟧ and about 40 % longer. At 360 px every page must still fit; text that shows
// outside the brackets was missed by t() or pieced together, and is reported (car data and names are expected there).
//   BASE=http://localhost:8766 node pseudo_pass.mjs        (also part of browser_e2e.mjs; leaves the demo in English)
import { fileURLToPath } from 'node:url';
import { readKeys } from './i18n_lib.mjs';

const ROUTES = ['', 'trips', 'trips/5', 'charges', 'charges/3', 'prices', 'battery', 'control', 'stats', 'map', 'places', 'places/1', 'events',
  'settings', 'system', 'system/capabilities', 'system/calls', 'system/diagnostics', 'import', 'no-such-page'];
const ACCENTS = { a: 'á', e: 'é', i: 'í', o: 'ó', u: 'ú', y: 'ý', A: 'Á', E: 'É', I: 'Í', O: 'Ó', U: 'Ú', c: 'ç', n: 'ñ', s: 'š', C: 'Ç', N: 'Ñ', S: 'Š' };

function disguise(english) {
  const body = english.split(/(\{\w+\})/).map((part, i) => (i % 2 ? part : part.replace(/[aeiouycnsAEIOUCNS]/g, (c) => ACCENTS[c]))).join('');
  const extra = Math.ceil(english.replace(/\{\w+\}/g, '').length * 0.4);
  // Padding comes in words, so that it wraps the way a longer sentence would.
  return `⟦${body}${' óóóó'.repeat(Math.floor(extra / 5))}${'ó'.repeat(extra % 5)}⟧`;
}

export function pseudoCatalog() {
  const { backend, frontend } = readKeys();
  return Object.fromEntries(Object.entries({ ...backend, ...frontend }).map(([key, entry]) => {
    const english = key.replace(/##.*$/s, '');
    return [key, entry.one === undefined ? disguise(english) : { one: disguise(entry.one.replace(/##.*$/s, '')), other: disguise(english) }];
  }));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Opens every route at 360 px in one language, runs `look` on each and leaves the demo in English. With `catalog`, the
 *  request for that language's file is answered with it. */
async function eachRoute(browser, base, { code, label, errors, catalog }, look) {
  const page = await browser.newPage();
  await page.setViewport({ width: 360, height: 780, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  page.on('pageerror', (e) => errors.push(`pageerror (${label}): ${e.message}`));
  if (catalog) {
    await page.setRequestInterception(true);
    const body = JSON.stringify(catalog);
    page.on('request', (req) => (new URL(req.url()).pathname === `/static/i18n/${code}.json`
      ? req.respond({ status: 200, contentType: 'application/json', body }) : req.continue()));
  }
  const setLanguage = (language) => page.evaluate((l) => fetch('/api/settings', {
    method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ language: l }) }).then((r) => r.status), language);
  await page.goto(`${base}/`, { waitUntil: 'networkidle0' });
  const status = await setLanguage(code);
  try {
    if (status !== 200) throw new Error(`could not set the language to ${code}: HTTP ${status}`);
    for (const route of ROUTES) {
      await page.goto('about:blank');
      await page.goto(`${base}/#/${route}`, { waitUntil: 'networkidle0' });
      await sleep(1300);
      await look(route || 'overview', await measure(page));
    }
  } finally {
    await setLanguage('en');
    await page.close();
  }
}

/** The texts of a page and what sticks out of a 360 px screen. */
function measure(page) {
  return page.evaluate(() => {
        for (const d of document.querySelectorAll('#main details')) d.open = true;
        const texts = [];
        const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let node = walk.nextNode(); node; node = walk.nextNode()) {
          const e = node.parentElement;
          // code and <pre> hold API paths and raw data, the map its own attribution, the language picker native names
          if (e.closest('code, pre, script, style, .leaflet-container, [lang]:not(html)') || !e.checkVisibility()) continue;
          texts.push(node.textContent);
        }
        for (const e of document.body.querySelectorAll('[title], [aria-label], [placeholder]')) {
          if (!e.closest('.leaflet-container')) for (const a of ['title', 'aria-label', 'placeholder']) if (e.getAttribute(a)) texts.push(e.getAttribute(a));
        }
        const vw = document.documentElement.clientWidth;
        const scrolls = (e) => {
          for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
            if (/auto|scroll|hidden/.test(getComputedStyle(p).overflowX)) return true;
          }
          return false;
        };
        // the elements that stick out, innermost first: that is where the fix belongs
        const over = [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > vw + 1 && !scrolls(e) && !e.closest('svg'));
        const culprits = over.filter((e) => !over.some((o) => o !== e && e.contains(o))).slice(0, 5)
          .map((e) => `${e.tagName.toLowerCase()}.${String(e.getAttribute('class') || '').split(' ').join('.')} in .${String(e.parentElement.getAttribute('class') || '').split(' ')[0]} +${Math.round(e.getBoundingClientRect().right - vw)}px`);
        return { texts, lang: document.documentElement.lang, scrollW: document.documentElement.scrollWidth, vw, culprits };
  });
}

const fits = (seen) => seen.scrollW <= seen.vw + 1;
const width = (seen) => `scrollWidth=${seen.scrollW}/${seen.vw} ${[...new Set(seen.culprits)].join(' | ')}`;

/** check(name, ok, extra) records a result, as in browser_e2e.mjs. Returns the texts seen outside the brackets. */
export async function pseudoPass(browser, base, check, errors = []) {
  const outside = new Map();
  await eachRoute(browser, base, { code: 'de', label: 'pseudo', errors, catalog: pseudoCatalog() }, (route, seen) => {
    check(`pseudo-language #/${route} is translated and fits 360 px`, seen.texts.some((x) => x.includes('⟦')) && fits(seen), width(seen));
    for (let text of seen.texts) {
      let before;
      do { before = text; text = text.replace(/⟦[^⟦⟧]*⟧/g, ' '); } while (text !== before);
      const rest = text.replace(/\s+/g, ' ').trim();
      if (/\p{L}{3,}/u.test(rest)) (outside.get(rest) || outside.set(rest, new Set()).get(rest)).add(route);
    }
  });
  return outside;
}

/** A real language: every page must carry its locale and fit 360 px (long compounds in tabs, chips and table heads). */
export async function layoutPass(browser, base, { code, locale }, check, errors = []) {
  await eachRoute(browser, base, { code, label: code, errors }, (route, seen) => {
    check(`${code} #/${route} fits 360 px`, seen.lang === locale && fits(seen), `lang=${seen.lang} ${width(seen)}`);
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { default: puppeteer } = await import('puppeteer-core');
  const browser = await puppeteer.launch({ executablePath: process.env.CHROME || '/Applications/Chromium.app/Contents/MacOS/Chromium', headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  let failed = 0;
  const errors = [];
  const outside = await pseudoPass(browser, process.env.BASE || 'http://localhost:8766', (name, ok, extra) => { if (!ok) { failed++; console.log(`FAIL ${name} ${extra}`); } }, errors);
  await browser.close();
  console.log(`${outside.size} distinct texts outside the brackets:`);
  for (const [text, routes] of [...outside].sort()) console.log(`  ${text.slice(0, 110)}   [${[...routes].slice(0, 3).join(' ')}]`);
  console.log(failed || errors.length ? `${failed} page(s) failed; ${errors.join(' | ')}` : 'every page translated and fits');
  process.exit(failed || errors.length ? 1 : 0);
}

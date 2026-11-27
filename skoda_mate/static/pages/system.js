// System: transparency page. What Mate asked Škoda, what the car can and cannot do, and the raw data behind every number.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { asyncButton, banner, button, card, chip, confirmDialog, empty, kv, loading, modal, table, toast } from '../lib/ui.js';
import capabilitiesPage from './capabilities.js';
import * as f from '../lib/format.js';
import { checkLabel, fixExplanation, sampleNode } from '../lib/quality.js';
import { t, tx } from '../i18n.js';

const PART_STATE = { present: 'good', unsupported: '', disabled: 'warn', unavailable: 'warn', missing: 'bad', unknown: '' };
const OP_LABEL = {
  startCharging: 'Start charging', stopCharging: 'Stop charging', setChargingLimit: 'Set charge limit', setChargeMode: 'Set charge mode', updateChargingProfile: 'Update charging profile',
  startAirConditioning: 'Start climate', stopAirConditioning: 'Stop climate', startAuxiliaryHeating: 'Start auxiliary heating', stopAuxiliaryHeating: 'Stop auxiliary heating',
  startActiveVentilation: 'Start ventilation', stopActiveVentilation: 'Stop ventilation',
};
const qualityLabel = (c) => checkLabel(c.id);
// api_calls.at is epoch seconds (the other timestamps are ISO strings)
const isoOf = (at) => (typeof at === 'number' ? new Date(at * 1000).toISOString() : at);

export default async function system(root, ctx) {
  ctx.setTitle(t('System'));
  const base = `/api/vehicles/${ctx.vid}`;
  const TABS = [['status', 'Status'], ['capabilities', 'Capabilities'], ['calls', 'API calls'], ['diagnostics', 'Diagnostics']];
  const tab = TABS.some(([k]) => k === ctx.params[0]) ? ctx.params[0] : 'status';
  const PAGE = 25;
  let quality = null, qualityError = null;
  let calls = null, callsError = null, health = null, healthError = null, offset = 0, failedOnly = false;

  const fetchCalls = () => ctx.api.get(`${base}/calls?limit=${PAGE}&offset=${offset}${failedOnly ? '&failed=true' : ''}`)
    .then((r) => { calls = r; callsError = null; }).catch((e) => { callsError = e.message; });

  const fetchQuality = () => ctx.api.get(`${base}/quality`).then((r) => { quality = r; qualityError = null; }).catch((e) => { qualityError = e.message; });
  const recheck = async () => { await fetchQuality(); draw(); };

  const fetchAll = async () => {
    await Promise.all([
      tab === 'calls' ? fetchCalls() : null,
      fetch('/health').then((r) => r.json()).then((r) => { health = r; healthError = null; }).catch((e) => { healthError = e.message; }),
    ]);
  };

  // ---- data quality
  /** POST, close the dialog, refresh the card, then toast. A failed POST shows its message in `err` (or throws, for the
   *  asyncButton toast, when there is no dialog); a failed refresh shows no success toast, the card shows its own error. */
  async function act(post, message, { close, err } = {}) {
    let r;
    try { r = await post(); } catch (e) { if (!err) throw e; mount(err, banner('bad', e.message)); return; }
    if (close) close();
    await recheck();
    if (!qualityError) toast(message(r), 'good');
  }
  const review = (c, reviewed, opts) => act(() => ctx.api.post(`${base}/quality/review`, { check: c.id, reviewed }), () => t(reviewed ? 'Reviewed' : 'Review undone'), opts);

  function reviewModal(c) {
    const err = h('div');
    const samples = c.samples || [];
    const more = c.count - samples.length;
    const sampleList = () => (samples.length ? h('ul', { class: 'quality-samples small' }, ...samples.map((sm) => h('li', null, sampleNode(sm)))) : null);
    const moreLine = () => (samples.length && more > 0 ? h('div', { class: 'tiny muted' }, `${t('and')} ${f.num(more)} ${t('more')}`) : null);
    const list = sampleList();
    // what the repair does, shown before anyone clicks Fix and repeated in the confirmation
    const explain = c.fix ? fixExplanation(c.fix, { reviewed: !!c.reviewed_at }) : null;
    const body = h('div', { class: 'stack' }, err,
      h('div', null, h('strong', null, `${t('Findings')}: ${f.num(c.count)}`)),
      list ? h('div', { class: 'tiny muted' }, t('Examples')) : null, list, moreLine(),
      explain ? h('div', { class: 'quality-explain' }, h('div', { class: 'tiny muted' }, t('What Fix does')), h('p', { class: 'small' }, explain)) : null);
    modal(qualityLabel(c), body, (close) => [
      button(t('Close'), { onClick: close }),
      c.fix ? asyncButton(t('Fix'), async () => {
        const confirmBody = h('div', { class: 'stack' },
          explain ? h('p', null, explain) : null,
          samples.length ? h('div', { class: 'tiny muted' }, t('It changes these findings:')) : null, sampleList(), moreLine(),
          h('p', null, `${t('Findings this fix changes:')} ${f.num(c.count)}. ${t('Nothing is lost.')}`));
        const ok = await confirmDialog(t('Apply this fix?'), confirmBody);
        if (!ok) return;
        await act(() => ctx.api.post(`${base}/quality/fix`, { action: c.fix }), (r) => `${t('Fixed')}: ${f.num(r.changed)}`, { close, err });
      }, { kind: 'primary', ic: 'check' }) : null,
      c.reviewed_at ? asyncButton(t('Undo'), () => review(c, false, { close, err }), { ic: 'left' }) : null,
      c.count > 0 ? asyncButton(t('Mark as reviewed'), () => review(c, true, { close, err }), { ic: 'check' }) : null,
    ]);
  }

  function qualityCard() {
    let body;
    if (qualityError) body = h('div', { class: 'stack' }, banner('bad', `${t('Could not load')}: ${qualityError}`));
    else if (!quality) body = loading();
    else {
      const checks = (quality.checks || []).filter((c) => c.visible !== false);  // a check that cannot fire stays off the card
      const found = checks.filter((c) => c.count > 0), clear = checks.filter((c) => !c.count);
      const nReviewed = checks.filter((c) => c.reviewed_at).length;
      const nImp = found.filter((c) => c.severity === 'important').length, nInfo = found.length - nImp;
      const row = (c) => {
        const done = c.reviewed_at && !c.count;
        return h('div', { class: 'quality-row', 'data-check': c.id },
          c.count ? chip(t(c.severity === 'important' ? 'Important' : 'Info'), c.severity === 'important' ? 'bad' : 'warn') : h('span', { class: 'tiny muted quality-none' }, t('No findings')),
          h('span', { class: 'quality-label' }, qualityLabel(c), ' ', h('strong', null, f.num(c.count)),
            c.reviewed_at ? h('span', { class: 'tiny muted' }, ' ', done ? `${t('Reviewed')} ${f.dayLabel(c.reviewed_at)}` : `${t('new since')} ${f.dayLabel(c.reviewed_at)}`) : null),
          done ? asyncButton(t('Undo'), () => review(c, false), { size: 'sm', ic: 'left' }) : button(t('Review'), { size: 'sm', onClick: () => reviewModal(c) }));
      };
      body = h('div', { class: 'stack' },
        h('div', { class: 'row tight' },
          nImp ? chip(`${f.num(nImp)} ${t('Important')}`, 'bad', 'alert') : null, nInfo ? chip(`${f.num(nInfo)} ${t('Info')}`, 'warn', 'info') : null,
          nReviewed ? chip(`${f.num(nReviewed)} ${t('reviewed')}`) : null,
          h('span', { class: 'tiny muted' }, `${t('Checked')}: ${f.dateTime(quality.checked_at)}`)),
        ...found.map(row),
        h('div', { class: 'small muted' }, nReviewed ? t('Everything else looks consistent or was reviewed.') : found.length ? t('Everything else looks consistent.') : t('Everything looks consistent.')),
        clear.length && (found.length || nReviewed) ? h('details', { class: 'quality-all' }, h('summary', null, t('Show all checks')), h('div', { class: 'stack' }, ...clear.map(row))) : null);
    }
    return card(t('Data quality'), body, { ic: 'shield', actions: asyncButton(t('Check again'), recheck, { ic: 'refresh', size: 'sm' }) });
  }

  // ---- budget + poller
  function budgetCard(o) {
    const p = o.poller, b = p?.budget;
    if (!b) return card(t('Request budget'), empty(t('Not connected'), null, 'wifioff'), { ic: 'signal' });
    return card(t('Request budget'), h('div', { class: 'stack' },
      h('div', { class: 'row' }, chip(`${b.used}/${b.limit}`, b.limited || b.remaining <= 0 ? 'warn' : 'good', 'signal'), h('span', { class: 'small' }, t('Requests used in the last hour')),
        b.limited ? chip(t('Limit reached'), 'warn', 'alert') : chip(t('Within the limit'), 'good', 'check')),
      h('div', { class: 'bar', role: 'img', 'aria-label': `${b.used} / ${b.limit}` }, h('i', { style: { width: `${Math.min(100, (b.used / b.limit) * 100)}%` } })),
      kv([[t('Request limit'), `${b.limit} / h`], [t('Reserved for commands'), `${b.reserve} / h`], [t('Left for reading'), b.remaining], [t('Left for commands'), b.remaining_for_commands],
        [t('Škoda reports remaining'), b.header_remaining ?? '–'], [t('Next free slot in'), b.next_free_s ? f.inSeconds(b.next_free_s) : '–']]),
      h('div', { class: 'tiny muted' }, t('Škoda allows about 20 requests per hour per car. Every reading and every command costs one request.'))), { ic: 'signal' });
  }

  function pollerCard(o) {
    const p = o.poller;
    if (!p || !p.known) return card(t('Polling status'), empty(t('Not connected'), null, 'wifioff'), { ic: 'refresh' });
    return card(t('Polling status'), h('div', { class: 'stack' },
      p.blocked ? banner('bad', t('Blocked'), ': ', t('Reading is blocked until the key is replaced.'), ' ', h('a', { href: '#/settings' }, t('Settings'))) : null,
      kv([
        [t('Last successful reading'), p.last_ok ? `${f.dateTime(p.last_ok)} (${f.ago(p.last_ok)})` : '–'],
        [t('Car reported'), p.captured_at ? f.ago(p.captured_at) : '–'],
        [t('Next reading in'), p.next_poll_in != null && !p.blocked ? f.inSeconds(p.next_poll_in) : '–'],
        [t('Mode'), p.active ? t('Active (car is busy)') : t('Idle')],
        [t('Intervals'), p.interval ? `${f.inSeconds(p.interval.idle)} ${t('idle')} · ${f.inSeconds(p.interval.active)} ${t('active')}` : '–'],
        [t('Readings so far'), p.polls ?? '–'],
        [t('API key expires'), p.key_expires_at ? f.date(p.key_expires_at) : '–'],
        [t('Last error'), p.error ? `${tx(p)}${p.error_kind ? ` (${p.error_kind})` : ''}` : t('none')],
      ])), { ic: 'refresh' });
  }

  // ---- calls
  function callsCard() {
    const go = async (o, failed = failedOnly) => { offset = o; failedOnly = failed; calls = null; draw(); await fetchCalls(); draw(); };
    let body;
    if (callsError) body = h('div', { class: 'stack' }, banner('bad', `${t('Could not load')}: ${callsError}`), button(t('Try again'), { ic: 'refresh', onClick: () => go(offset) }));
    else if (!calls) body = loading();
    else {
      const from = calls.total ? offset + 1 : 0, to = Math.min(offset + PAGE, calls.total);
      const pager = calls.total > PAGE ? h('div', { class: 'pager', role: 'navigation', 'aria-label': t('Pages') },
        button(t('Newer'), { ic: 'left', size: 'sm', disabled: offset <= 0, onClick: () => go(Math.max(0, offset - PAGE)) }),
        h('span', { class: 'small muted' }, `${from}–${to} ${t('of')} ${calls.total}`),
        button(`${t('Older')} →`, { size: 'sm', disabled: to >= calls.total, onClick: () => go(offset + PAGE) })) : null;
      body = h('div', { class: 'stack' }, table([
        { label: t('When'), render: (c) => f.dateTime(isoOf(c.at)), cls: 'nowrap' },
        { label: t('Endpoint'), render: (c) => h('code', null, c.endpoint) },
        { label: t('Result'), render: (c) => (c.ok ? chip(t('OK'), 'good', 'check') : h('div', null, chip(t('Failed'), 'bad', 'alert'), c.error ? h('div', { class: 'tiny' }, c.error) : null)) },
      ], calls.items, { label: t('Recent API calls'), emptyNode: empty(failedOnly ? t('No failed calls.') : t('No calls yet.'), null, 'list') }), pager);
    }
    const filter = h('label', { class: 'b-check' }, h('input', { type: 'checkbox', checked: failedOnly, onchange: (e) => go(0, e.target.checked) }), t('Only failed'));
    return card(t('Recent API calls'), h('div', { class: 'stack' }, filter, body), { ic: 'list' });
  }

  // ---- parts, errors, operations
  function partsCard(o) {
    const parts = Object.entries(o.parts || {});
    const errs = o.api_errors || [];
    const matrix = table([
      { label: t('Part'), render: ([, p]) => t(p.label) },
      { label: t('State'), render: ([, p]) => chip(t(p.state), PART_STATE[p.state] ?? '', p.state === 'present' ? 'check' : p.state === 'missing' ? 'alert' : 'info') },
      { label: t('Reason'), render: ([, p]) => h('span', { class: 'small muted' }, p.reason ? t(p.reason) : '–') },
    ], parts, { label: t('Data parts') });
    return card(t('Data parts'), h('div', { class: 'stack' }, h('div', { class: 'small muted' }, t('What the car reports, part by part.')), matrix,
      h('h3', null, t('Errors reported by Škoda')),
      errs.length ? h('ul', { class: 'b-notes small' }, ...errs.map((e) => h('li', null, h('code', null, e.type), e.description ? ` — ${t(e.description)}` : ''))) : h('div', { class: 'small muted' }, t('No errors reported.'))), { ic: 'shield' });
  }

  function opsCard(o) {
    const ops = o.operations;
    return card(t('Supported operations'), h('div', { class: 'stack' }, h('div', { class: 'small muted' }, t('Remote operations this car accepts. Controls for anything else are shown disabled.')),
      ops == null ? h('div', { class: 'small' }, t('Not known yet. Mate has not received the list from Škoda.'))
        : ops.length ? h('div', { class: 'row tight' }, ...ops.map((op) => h('span', { class: 'chip good', title: op }, icon('check', { size: 13 }), t(OP_LABEL[op] || op))))
          : h('div', { class: 'small' }, t('This car supports no remote operations.'))), { ic: 'sliders' });
  }


  // ---- raw viewer (loaded only when opened: it contains VIN and position)
  function rawCard() {
    const pre = h('pre', { class: 'b-raw', tabindex: 0, 'aria-label': t('Raw data') });
    const status = h('div');
    let loaded = false;
    const load = async () => {
      mount(status, loading());
      try {
        const r = await ctx.api.get(`${base}/raw`);
        pre.textContent = Object.keys(r || {}).length ? JSON.stringify(r, null, 2) : '';
        mount(status, Object.keys(r || {}).length ? null : empty(t('No raw data stored yet.'), null, 'info'));
        loaded = true;
      } catch (e) {
        mount(status, banner('bad', `${t('Could not load')}: ${e.message}`), button(t('Try again'), { ic: 'refresh', onClick: load }));
      }
    };
    const det = h('details', { class: 'b-rawbox', ontoggle: () => { if (det.open && !loaded) load(); } },
      h('summary', null, t('Show raw data')),
      h('div', { class: 'stack' }, banner('warn', t('The raw answer contains your VIN, licence plate and exact position. Do not post it publicly.')),
        h('div', { class: 'tiny muted' }, t('The last answer exactly as Škoda sent it.')), status, pre));
    return card(t('Raw data'), det, { ic: 'activity' });
  }

  function diagCard() {
    return card(t('Diagnostics'), h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('A report for bug reports: poller status, data parts, supported operations, recent calls and commands, and the answer from Škoda with VIN, plate, name, position and profile names removed. The API key and S-PIN are never included.')),
      h('div', null, h('a', { class: 'btn', href: `${base}/diagnostics`, download: 'skoda-mate-diagnostics.json' }, icon('download', { size: 16 }), t('Download diagnostics')))), { ic: 'download' });
  }

  function appCard(o) {
    return card(t('App'), healthError ? banner('bad', `${t('Could not load')}: ${healthError}`) : !health ? loading() : h('div', { class: 'stack' },
      h('div', { class: 'row' }, health.ok ? chip(t('Healthy'), 'good', 'check') : chip(t('Failed'), 'bad', 'alert'), o.demo ? chip(t('Demo mode'), 'info') : null),
      kv([[t('Version'), `v${health.version}`], [t('Connected to Škoda'), health.connected ? t('yes') : t('no')],
        [t('Last successful contact'), health.last_ok ? f.dateTime(health.last_ok) : '–'], [t('Last error'), tx(health, 'last_error') || t('none')]])), { ic: 'shield' });
  }

  const tabs = () => h('nav', { class: 'tabs', 'aria-label': t('System sections') },
    ...TABS.map(([k, label]) => h('a', { href: k === 'status' ? '#/system' : `#/system/${k}`, 'aria-current': k === tab ? 'page' : null }, t(label))));

  function panel() {
    const o = ctx.overview;
    if (tab === 'calls') return [callsCard()];
    if (tab === 'diagnostics') return [h('div', { class: 'grid g2' }, partsCard(o), h('div', { class: 'stack' }, rawCard(), diagCard()))];
    return [qualityCard(), h('div', { class: 'grid g2' }, budgetCard(o), pollerCard(o)), h('div', { class: 'grid g2' }, appCard(o), opsCard(o))];
  }

  function draw() {
    mount(root, h('h1', null, t('System')), tabs(), ...panel());
  }

  if (tab === 'capabilities') {
    mount(root, h('h1', null, t('System')), tabs());
    const inner = h('div', { class: 'stack' });
    root.append(inner);
    await capabilitiesPage(inner, ctx);
    ctx.setTitle(`${t('Capabilities')} · ${t('System')}`);
    return;
  }
  mount(root, h('h1', null, t('System')), tabs(), loading());
  await Promise.all([fetchAll(), fetchQuality()]);
  draw();
  // Re-drawing would collapse the raw viewer, so on a tick only refresh the live parts when it is closed.
  ctx.onTick(async () => { if (root.querySelector('.b-rawbox[open], .quality-all[open]')) return; await fetchAll(); draw(); });
}

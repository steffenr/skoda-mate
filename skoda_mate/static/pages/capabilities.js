// Capabilities: everything the official MyŠkoda API offers, what this car supports and reports right now,
// and what Mate adds on top. Data: GET /api/vehicles/{id}/capabilities (features.capabilities).
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, card, chip, empty, stat } from '../lib/ui.js';
import * as f from '../lib/format.js';
import { N_, t, tEnum, tn } from '../i18n.js';

const GROUPS = { read: N_('Read'), charging: N_('Charging'), climate: N_('Climate') };
const fmtVal = (r) => {
  const v = r.value;
  if (v == null) return '–';
  if (r.unit === 'time') return f.dateTime(v);
  if (r.unit === 'km') return f.km(v, 0);
  if (r.unit === 'url') return t('yes');
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'boolean') return v ? t('yes') : t('no');
  if (typeof v === 'number') return `${f.num(v, Number.isInteger(v) ? 0 : 1)}${r.unit && r.unit !== 'count' ? ` ${r.unit}` : ''}`;
  return typeof v === 'string' ? tEnum(v) : String(v);
};
const stateChip = (s) => chip(t(s), s === 'present' ? 'good' : s === 'unknown' ? '' : 'warn');

export default async function capabilities(root, ctx) {
  ctx.setTitle(t('Capabilities'));
  const data = await ctx.api.get(`/api/vehicles/${ctx.vid}/capabilities`);
  const s = data.summary, c = data.contract;

  const header = h('div', { class: 'stack' }, h('h2', null, t('What is possible with your car')),
    h('p', { class: 'muted' }, t('Everything the official Škoda API offers, what your car supports, and what Mate adds on top.')),
    h('div', { class: 'grid auto' },
      card(null, stat(t('Commands'), `${s.operations_supported} / ${s.operations_total}`, { ic: 'sliders', sub: t('commands supported') })),
      card(null, stat(t('Data the car reports'), `${s.parts_available} / ${s.parts_total}`, { ic: 'activity', sub: t('data parts available') })),
      card(null, stat(t('Request limit'), `${c.rate_limit_per_hour}`, { ic: 'signal', sub: `${t('per hour per car')}. ${t('Reading costs one request; every command costs one more.')}` })),
      card(null, stat(t('API version'), c.version, { ic: 'info', sub: h('a', { href: c.docs, target: '_blank', rel: 'noopener' }, t('API reference')) }))));

  const opRow = (o) => h('div', { class: 'b-line' },
    h('div', { style: { flex: 1, minWidth: 0 } },
      h('div', { class: 'row tight' }, h('strong', null, t(o.label)), h('code', { class: 'tiny muted' }, `${o.method} ${o.path}`)),
      h('div', { class: 'small' }, t(o.what)),
      h('div', { class: 'tiny muted' }, `${t("Parameters")}: ${t(o.params)} · ${t("In Mate")}: ${t(o.mate)}`)),
    h('div', { class: 'row tight' }, chip(o.supported === null ? t('unknown yet') : o.supported ? t('supported') : t('not supported'), o.supported ? 'good' : o.supported === false ? 'warn' : ''),
      o.supported === false ? null : h('a', { class: 'btn sm', href: `#/${o.page === 'overview' ? '' : o.page}` }, t('Open##action'))));
  const ops = card(t('Commands'), h('div', { class: 'stack' }, ...Object.entries(GROUPS).map(([g, label]) =>
    h('div', { class: 'stack' }, h('h3', null, t(label)), ...data.operations.filter((o) => o.group === g).map(opRow)))), { ic: 'sliders' });

  const parts = card(t('Data the car reports'), h('div', { class: 'stack' }, ...data.parts.filter((p) => !['unsupported', 'disabled', 'unavailable', 'missing'].includes(p.state)).map((p) =>
    h('details', { class: 'b-profile' },
      h('summary', null, h('strong', null, t(p.label)), ' ', stateChip(p.state), ' ', h('span', { class: 'tiny muted' }, tn('{reported}/{n} field reported', '{reported}/{n} fields reported', p.fields.length, { reported: p.reported }))),
      p.reason ? h('div', { class: 'small muted' }, t(p.reason)) : null,
      h('div', { class: 'scroll-x', tabindex: 0, role: 'region', 'aria-label': t(p.label) }, h('table', { class: 't' }, h('tbody', null, ...p.fields.map((r) =>
        h('tr', null, h('td', null, t(r.label)), h('td', { class: 'tiny muted' }, h('code', null, r.api)), h('td', { class: 'num' }, fmtVal(r)))))))))), { ic: 'activity' });

  const derived = card(t('What Mate adds'), h('div', { class: 'stack' }, ...data.derived.map((d) =>
    h('div', { class: 'b-line' }, h('div', { style: { flex: 1 } }, h('strong', null, t(d.title)), h('div', { class: 'small' }, t(d.how))),
      h('a', { class: 'btn sm', href: `#/${d.page}` }, t('Open##action'))))), { ic: 'plus' });


  // What the API offers but this car does not report (hidden from the data list above, stated here instead)
  const off = data.parts.filter((p) => ['unsupported', 'disabled', 'unavailable', 'missing'].includes(p.state));
  const unsupported = off.length ? card(t('Not supported by your car'), h('div', { class: 'stack' }, h('div', { class: 'small muted' }, t('The Škoda API offers these, but your car does not report them.')),
    ...off.map((p) => h('div', { class: 'b-line' }, h('div', { style: { flex: 1, minWidth: 0 } }, h('strong', null, t(p.label)), ' ', stateChip(p.state),
      p.reason ? h('div', { class: 'small muted' }, t(p.reason)) : null,
      h('div', { class: 'tiny muted' }, `${t('Would report')}: ${p.fields.map((r) => t(r.label)).join(', ')}`))))), { ic: 'info' }) : null;

  mount(root, header, ops, parts, derived, unsupported);
}

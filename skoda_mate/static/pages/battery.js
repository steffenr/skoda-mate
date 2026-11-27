// Battery: SoC and charging-power history, the charging settings the car reports, and an honest capacity ESTIMATE.
// Škoda does not report battery health. The estimate is wall energy per 100 % SoC and includes charging losses.
import { h, mount } from '../lib/dom.js';
import { icon } from '../lib/icons.js';
import { banner, button, card, chip, empty, kv, loading, seg, stat } from '../lib/ui.js';
import { lineChart } from '../lib/charts.js';
import * as f from '../lib/format.js';
import { rangeCard } from '../lib/rangecard.js';
import { extendDE, t } from '../i18n.js';

extendDE({
  'Battery history': 'Batterieverlauf', 'Range': 'Zeitraum', 'Battery': 'Batterie', 'Charging power': 'Ladeleistung',
  '24 h': '24 Std.', '7 d': '7 Tage', '30 d': '30 Tage', '1 y': '1 Jahr',
  'Not enough readings yet': 'Noch nicht genug Messwerte', 'The chart fills in as Mate reads the car.': 'Das Diagramm füllt sich, während Mate das Auto ausliest.',
  'Charging settings': 'Ladeeinstellungen', 'Charge limit': 'Ladelimit', 'Battery care limit': 'Limit im Schonmodus', 'Preferred mode': 'Bevorzugter Modus',
  'Unlock plug when charged': 'Stecker nach dem Laden entriegeln', 'Maximum current': 'Maximaler Strom', 'Battery care': 'Batterieschutz', 'on': 'an', 'off': 'aus',
  'Not reported': 'Nicht gemeldet', 'The car reports no charging settings.': 'Das Auto meldet keine Ladeeinstellungen.',
  'Manual': 'Manuell', 'Timer': 'Timer', 'Timer with climate': 'Timer mit Klimatisierung', 'Preferred charging times': 'Bevorzugte Ladezeiten',
  'Only own current': 'Nur eigener Strom', 'Immediate discharging': 'Sofort entladen', 'Home storage charging': 'Heimspeicher-Laden',
  'Permanent': 'Dauerhaft', 'Reduced': 'Reduziert', 'Maximum': 'Maximal', 'Off': 'Aus',
  'Charging profiles': 'Ladeprofile', 'Edit profiles under Control': 'Profile unter Steuerung bearbeiten', 'No charging profiles reported.': 'Keine Ladeprofile gemeldet.',
  'time windows': 'Zeitfenster', 'timers': 'Timer', 'minimum charge': 'Mindest-Ladestand', 'at the current position': 'am aktuellen Standort',
  'Battery capacity estimate': 'Schätzung der Batteriekapazität', 'Wall energy per 100 % charge': 'Netzenergie pro 100 % Ladung', 'Nominal capacity': 'Nennkapazität',
  'Charging efficiency': 'Ladewirkungsgrad', 'Charges used': 'Verwendete Ladevorgänge', 'Set in Settings': 'In den Einstellungen festlegen', 'Not set': 'Nicht gesetzt',
  'Estimate over time': 'Schätzung im Zeitverlauf', 'Wall energy per 100 % SoC': 'Netzenergie pro 100 % SoC',
  'This is an estimate, not battery health.': 'Das ist eine Schätzung, kein Batteriezustand.',
  'Škoda does not report battery health (SoH). The figure is the energy drawn from the wall for 100 % of charge, so it includes charging losses and will be higher than the usable battery capacity.':
    'Škoda meldet keinen Batteriezustand (SoH). Der Wert ist die aus dem Netz gezogene Energie für 100 % Ladung, enthält also Ladeverluste und liegt über der nutzbaren Batteriekapazität.',
  'No qualifying charges yet': 'Noch keine geeigneten Ladevorgänge', 'The estimate needs AC charges of at least 30 % that Mate saw from start to end, and the battery capacity from Settings.':
    'Die Schätzung braucht AC-Ladevorgänge von mindestens 30 %, die Mate vom Start bis zum Ende gesehen hat, sowie die Batteriekapazität aus den Einstellungen.',
  'Could not load battery data': 'Batteriedaten konnten nicht geladen werden', 'Try again': 'Erneut versuchen', 'Loading…': 'Lädt …',
});

const RANGES = [[24, '24 h'], [168, '7 d'], [720, '30 d'], [8760, '1 y']];
const MODE_LABEL = {
  MANUAL: 'Manual', TIMER: 'Timer', TIMER_CHARGING_WITH_CLIMATISATION: 'Timer with climate', PREFERRED_CHARGING_TIMES: 'Preferred charging times',
  ONLY_OWN_CURRENT: 'Only own current', IMMEDIATE_DISCHARGING: 'Immediate discharging', HOME_STORAGE_CHARGING: 'Home storage charging',
};
const word = (map, v) => (v == null || v === '' ? '–' : t(map[v] || v));
const WORDS = { PERMANENT: 'Permanent', OFF: 'Off', REDUCED: 'Reduced', MAXIMUM: 'Maximum' };

export default async function battery(root, ctx) {
  ctx.setTitle(t('Battery'));
  const base = `/api/vehicles/${ctx.vid}`;
  let hours = +(sessionStorage.getItem('b-battery-hours') || 168);
  if (!RANGES.some(([v]) => v === hours)) hours = 168;
  let data = null, seq = 0;
  const chartBox = h('div', null, loading());

  const failure = (e, retry) => mount(root, h('div', { class: 'card' }, banner('bad', `${t('Could not load battery data')}: ${e.message}`),
    h('div', { style: { marginTop: '12px' } }, button(t('Try again'), { onClick: retry, ic: 'refresh' }))));

  function historyChart() {
    const hist = data.history || [];
    if (hist.length < 2) { mount(chartBox, empty(t('Not enough readings yet'), t('The chart fills in as Mate reads the car.'), 'trend')); return; }
    mount(chartBox, lineChart({
      height: 240, yLeft: { min: 0, max: 100, fmt: (v) => `${v}%` }, yRight: { min: 0, fmt: (v) => `${v} kW` },
      series: [{ name: t('Battery'), data: hist.map((p) => ({ x: p.t, y: p.soc })), area: true, fmt: (v) => f.pct(v) },
        { name: t('Charging power'), data: hist.map((p) => ({ x: p.t, y: p.charging ? p.p : 0 })), axis: 'right', color: 'var(--chart-3)', step: true, fmt: (v) => f.kw(v) }],
    }));
  }

  function settingsCard() {
    const s = data.charging?.settings;
    if (!s) return card(t('Charging settings'), empty(t('The car reports no charging settings.'), ctx.overview.parts.charging?.reason, 'plug'), { ic: 'bolt' });
    return card(t('Charging settings'), kv([
      [t('Charge limit'), s.target_soc != null ? `${s.target_soc} %` : '–'],
      [t('Battery care limit'), s.care_target_soc != null ? `${s.care_target_soc} %` : '–'],
      [t('Battery care'), s.care_mode == null ? '–' : s.care_mode ? t('on') : t('off')],
      [t('Preferred mode'), word(MODE_LABEL, s.preferred_mode)],
      [t('Unlock plug when charged'), word(WORDS, s.auto_unlock_plug)],
      [t('Maximum current'), `${word(WORDS, s.max_current)}${s.max_current_a != null ? ` (${s.max_current_a} A)` : ''}`],
    ]), { ic: 'bolt', actions: h('a', { class: 'btn sm ghost', href: '#/control' }, t('Control')) });
  }

  function profilesCard() {
    const p = data.profiles;
    const list = p?.profiles || [];
    if (!list.length) return card(t('Charging profiles'), empty(t('No charging profiles reported.'), ctx.overview.parts.chargingProfiles?.reason, 'plug'), { ic: 'sliders' });
    const cur = p.current?.id;
    return card(t('Charging profiles'), h('div', { class: 'stack' }, ...list.map((x) => {
      const s = x.settings || {}, m = s.minBatteryStateOfCharge;
      return h('div', { class: 'b-prof' },
        h('div', { class: 'row between' }, h('strong', null, x.name || `#${x.id}`), h('span', { class: 'row tight' },
          x.id === cur ? chip(t('at the current position'), 'info', 'pin') : null,
          chip(s.targetStateOfChargeInPercent != null ? `${s.targetStateOfChargeInPercent} %` : '–', ''))),
        h('div', { class: 'small muted' }, [
          s.maxChargingCurrent ? `${t('Maximum current')}: ${word(WORDS, s.maxChargingCurrent)}` : null,
          s.autoUnlockPlugWhenCharged ? `${t('Unlock plug when charged')}: ${word(WORDS, s.autoUnlockPlugWhenCharged)}` : null,
          m?.enabled ? `${t('minimum charge')} ${m.minimumBatteryStateOfChargeInPercent} %` : null,
          `${t('time windows')}: ${(x.preferredChargingTimes || []).length}`, `${t('timers')}: ${(x.timers || []).length}`].filter(Boolean).join(' · ')));
    }), h('a', { href: '#/control' }, t('Edit profiles under Control'))), { ic: 'sliders' });
  }

  function estimateCard() {
    const est = data.estimate_kwh_at_wall, pts = data.points || [];
    const note = banner('info', h('strong', null, t('This is an estimate, not battery health.')), ' ',
      t('Škoda does not report battery health (SoH). The figure is the energy drawn from the wall for 100 % of charge, so it includes charging losses and will be higher than the usable battery capacity.'),
      data.note ? h('div', { class: 'tiny', style: { marginTop: '4px' } }, t(data.note)) : null);
    if (est == null || !data.samples) {
      return card(t('Battery capacity estimate'), h('div', { class: 'stack' }, empty(t('No qualifying charges yet'),
        t('The estimate needs AC charges of at least 30 % that Mate saw from start to end, and the battery capacity from Settings.'), 'battery'), note), { ic: 'gauge' });
    }
    return card(t('Battery capacity estimate'), h('div', { class: 'stack' },
      h('div', { class: 'grid auto' },
        stat(t('Wall energy per 100 % charge'), f.num(est, 1), { unit: 'kWh', ic: 'bolt', sub: `${data.samples} ${t('Charges used').toLowerCase()}` }),
        data.nominal_kwh != null ? stat(t('Nominal capacity'), f.num(data.nominal_kwh, 1), { unit: 'kWh', ic: 'battery' })
          : stat(t('Nominal capacity'), t('Not set'), { ic: 'battery', sub: h('a', { href: '#/settings' }, t('Set in Settings')) }),
        data.charging_efficiency != null ? stat(t('Charging efficiency'), f.num(data.charging_efficiency * 100, 1), { unit: '%', ic: 'gauge' }) : null),
      h('div', null, h('h3', { style: { marginBottom: '6px' } }, t('Estimate over time')),
        lineChart({ height: 190, yLeft: { fmt: (v) => `${f.num(v, 0)}` }, series: [{ name: t('Wall energy per 100 % SoC'), data: pts.map((p) => ({ x: p.at, y: p.kwh_per_100 })), fmt: (v) => f.kwh(v) }],
          emptyText: t('Not enough readings yet') })),
      note), { ic: 'gauge' });
  }

  function draw() {
    const range = seg(RANGES.map(([v, l]) => [v, t(l)]), hours, (v) => { hours = v; try { sessionStorage.setItem('b-battery-hours', v); } catch { /* optional */ } reload(true); });
    range.setAttribute('aria-labelledby', 'b-range-label');
    mount(root,
      card(t('Battery history'), h('div', { class: 'stack' },
        h('div', { class: 'row between' }, h('span', { class: 'small muted', id: 'b-range-label' }, t('Range')),
          range),
        chartBox), { ic: 'trend' }),
      h('div', { class: 'grid g2' }, settingsCard(), profilesCard()),
      rangeCard(data.projected_range),
      estimateCard());
    historyChart();
  }

  async function reload(chartOnly = false) {
    const mine = ++seq;
    if (chartOnly) mount(chartBox, loading());
    try {
      const d = await ctx.api.get(`${base}/battery?hours=${hours}&tz_offset=${new Date().getTimezoneOffset()}`);
      if (mine !== seq) return;
      data = d;
      if (chartOnly && root.firstChild) historyChart(); else draw();
    } catch (e) {
      if (mine !== seq) return;
      if (data && !chartOnly) return;   // background refresh failed: keep what is on screen
      if (chartOnly && data) mount(chartBox, banner('bad', `${t('Could not load battery data')}: ${e.message}`));
      else failure(e, () => { mount(root, loading()); reload(); });
    }
  }

  mount(root, loading());
  await reload();
  ctx.onTick(() => reload(false));
}

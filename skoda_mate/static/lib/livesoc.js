// A battery level between two readings. Škoda allows ~20 requests an hour, so while charging Mate extrapolates the last
// reading (display only: nothing estimated is ever stored) and says so with an info icon.
import { h } from './dom.js';
import { icon } from './icons.js';
import * as f from './format.js';
import { t } from '../i18n.js';

const MAX_EXTRAPOLATE_MIN = 90;  // never project further than this past the last reading
const MIN_AGE_MIN = 2;  // a reading this fresh is shown as is

// While charging, between two readings: move the last reading along the car's own forecast (level now -> limit over the
// time it said was left), or, without a forecast, along the charging power and the battery capacity. Never past the limit.
// Returns {soc, readAt} or null when the reading should be shown as is.
export function liveSoc(s, capacityKwh, now = Date.now()) {
  if (!s || !s.charging || s.soc == null) return null;
  const readAt = s.captured_at || s.recorded_at;
  const min = (now - Date.parse(readAt)) / 60000;
  if (!(min >= MIN_AGE_MIN)) return null;
  const m = Math.min(min, MAX_EXTRAPOLATE_MIN), ceiling = s.target_soc > 0 ? s.target_soc : 100;
  if (s.soc >= ceiling) return null;  // at the limit already: nothing left to project
  let est = null;
  if (s.target_soc > s.soc && s.remaining_min > 0) est = s.soc + (s.target_soc - s.soc) * Math.min(1, m / s.remaining_min);
  else if (s.charge_power_kw > 0 && capacityKwh > 0) est = s.soc + (s.charge_power_kw * (m / 60) / capacityKwh) * 100;
  if (est == null) return null;
  est = Math.min(est, ceiling);
  return Math.round(est) > Math.round(s.soc) ? { soc: est, readAt } : null;
}

export const ESTIMATE_TIP = () => t('Estimated, not read live. Škoda allows only 20 requests per hour, so Mate reads the car every few minutes. Between readings the battery level is extrapolated from the last reading and the time the car said was left to the charge limit. It is replaced by the real value with every new reading.');

// "(i) estimated · last reading 46 % 5 min ago": the icon carries the explanation as tooltip and accessible name
export function estimateNote(live, s) {
  if (!live) return null;
  const tip = ESTIMATE_TIP();
  return h('div', { class: 'tiny muted', style: { display: 'flex', alignItems: 'center', gap: '4px', marginTop: '4px', marginBottom: '10px' } },
    h('span', { tabindex: 0, role: 'img', title: tip, 'aria-label': tip, style: { display: 'inline-flex', cursor: 'help' } }, icon('info', { size: 14 })),
    `${t('estimated')} · ${t('last reading')} ${s.soc != null ? Math.round(s.soc) : '–'} % ${f.ago(live.readAt)}`);
}

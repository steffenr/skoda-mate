// Data-quality names, shared by the System page (the Data quality card) and the Activity List tab (the quality_fix and
// quality_review events), so a check or repair has one label in both places. Ids are quality.CHECKS / quality.ACTIONS.
import { t } from '../i18n.js';
import { h } from './dom.js';
import * as f from './format.js';

const CHECK = {
  open_trips: 'Trips that never ended', open_charges: 'Charges that never ended', estimated_charges: 'Charges with an estimated end', inferred_charges: 'Charges inferred from battery readings',
  approx_trips: 'Approximate trips', reading_gaps: 'Long gaps between readings', odometer_jumps: 'Odometer jumps or decreases', duplicate_trips: 'Groups of duplicate trips',
  api_errors: 'API errors in the last 24 h', stuck_operations: 'Operations stuck for over 30 min', missing_sections: 'Data sections missing',
};
const ACTION = {
  close_open_trips: 'Close open trips', close_open_charges: 'Close open charges', repair_charges: 'Repair charges',
  infer_charges: 'Add inferred charges', dedupe_trips: 'Merge duplicate trips',
};

// What each repair does to a row, in words a user can check against the trip or charge page. Mirrors quality.py:
// `_close_open_trips` / `_close_open_charges` (the end rules shared with activity.PARKED / NOT_CHARGING) and
// `_dedupe_trips` (the oldest row keeps its numbers, the copies go into merged_json, notes are joined).
const EXPLAIN = {
  close_open_trips: 'Each trip gets an end: the first reading after its start that shows the car parked, otherwise its last reading. The trip is then marked as approximate.',
  close_open_charges: 'Each charge gets an end: the first reading after its start that shows the car no longer charging, otherwise its last charging reading. The end is marked as estimated.',
  dedupe_trips: 'Each group becomes one trip: the oldest trip keeps its numbers and the notes of all copies. The copies leave the lists but are saved with it, and "Undo merge" on the trip page restores them.',
};

/** What a repair does, in the user's language; null for an action without a description. With `reviewed`, also says
 * that findings marked as reviewed are left alone (the repairs only touch findings newer than the review). */
export function fixExplanation(action, { reviewed = false } = {}) {
  if (!EXPLAIN[action]) return null;
  return reviewed ? `${t(EXPLAIN[action])} ${t('Findings you marked as reviewed stay as they are.')}` : t(EXPLAIN[action]);
}

/** A check's label in the user's language; an unknown id stays as it is. */
export const checkLabel = (id) => (CHECK[id] ? t(CHECK[id]) : id);
/** A repair action's label in the user's language; an unknown action stays as it is. */
export const actionLabel = (action) => (ACTION[action] ? t(ACTION[action]) : action);

// ---- one line per finding, built from the sample's structured fields (quality.py `_sample`): translated words plus
// formatted dates and numbers, never the backend's English `label` (which stays for other API clients and is the
// fallback for a kind this code does not know).

const SECTION = { info: 'Vehicle information', charging: 'Charging data', climate: 'Climate data', position: 'Position data' };

/** The line for one sample of a check: a link for a trip or charge, plain text for everything else. */
export function sampleNode(sm) {
  const day = f.dayLabel;
  switch (sm.kind) {
    case 'trip': case 'charge': {
      const link = h('a', { href: sm.href || `#/${sm.kind === 'trip' ? 'trips' : 'charges'}/${sm.id}` }, `${t(sm.kind === 'trip' ? 'Trip' : 'Charge')} #${sm.id}`);
      return h('span', null, link, `, ${day(sm.at)}`);
    }
    case 'gap': return `${t('Gap')}: ${f.num(sm.hours)} h, ${day(sm.from)} → ${day(sm.to)}`;
    case 'silence': return t('Silent since {date} ({hours} h)', { date: day(sm.from), hours: f.num(sm.hours) });
    case 'odometer': return `${t('Odometer')} ${f.num(sm.from_km)} → ${f.num(sm.to_km)} km, ${day(sm.at)}`;
    case 'api_error': return t('{endpoint} failed, {date} {time}', { endpoint: sm.endpoint, date: day(sm.at), time: f.time(sm.at) });
    case 'section': return t('Section {name} missing', { name: t(SECTION[sm.name] || sm.name) });
    default: return sm.label;
  }
}

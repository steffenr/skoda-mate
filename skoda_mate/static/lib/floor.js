// The "below the detection floor" display shared by the Overview parked card and Statistics → Parked. The charge level is
// a whole percent, so a stand that lost less than one percent has a median or a total of exactly zero: that reads as
// "below the detection floor", never as a measured 0.0.
import { extendDE, t } from '../i18n.js';
import { h } from './dom.js';
import * as f from './format.js';
import { stat } from './ui.js';

extendDE({
  'below the detection floor': 'unter der Nachweisgrenze', 'Median loss': 'Medianverlust', 'kWh/day': 'kWh/Tag',
});

export const floorText = () => t('below the detection floor');
export const belowFloor = (cls = 'small muted') => h('span', { class: cls }, floorText());
/** kWh as text, or the floor text for exactly zero (null stays a dash through `f.kwh`). */
export const kwhText = (v, digits = 1) => (v === 0 ? floorText() : f.kwh(v, digits));
/** The floor text as a stat's value (the stat's own unit styling is not wanted for a sentence). */
export const floorValue = () => h('small', { style: { marginLeft: 0 } }, floorText());
/** kWh as a node: the muted floor text for exactly zero. */
export const kwhOrFloor = (v, digits = 1) => (v === 0 ? belowFloor() : f.kwh(v, digits));
/** The "Median loss" figure: the floor text when the median is exactly zero, a dash when nothing was measured. */
export const medianLossStat = (median) => (median === 0
  ? stat(t('Median loss'), floorValue(), { ic: 'battery' })
  : stat(t('Median loss'), median != null ? f.num(median, 1) : '–', { unit: median != null ? t('kWh/day') : null, ic: 'battery' }));

// Pure-function checks for the frontend libraries (no DOM, no server): node unit.mjs
import assert from 'node:assert/strict';
import { niceScale } from '../../skoda_mate/static/lib/charts.js';

const s = niceScale(0, 0);
assert.ok(s.min === 0 && s.max >= 1 && s.ticks.every((t) => t >= 0), 'a flat zero series must not produce negative ticks');
const flat = niceScale(36, 36);
assert.ok(flat.min < 36 && flat.max > 36, 'a flat non-zero series still gets a range');
const t = niceScale(0, 97, 5);
assert.deepEqual([t.min, t.max], [0, 100]);
assert.ok(t.ticks.includes(0) && t.ticks.includes(100));
assert.deepEqual(niceScale(NaN, 1).ticks, [0, 1]);
console.log('frontend unit checks OK');

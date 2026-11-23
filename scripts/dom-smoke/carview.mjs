// Unit check of the car status states (no server): node carview.mjs
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
const dom = new JSDOM('<!doctype html><body></body>', { url: 'http://localhost/' });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, Node: dom.window.Node, localStorage: dom.window.localStorage });
const { carView } = await import('../../skoda_mate/static/lib/car.js');
const view = (snap) => carView({ snapshot: snap, sections: {} });
const text = (snap) => view(snap).innerText ?? view(snap).textContent.replace(/\s+/g, ' ');
const cells = (snap) => Object.fromEntries([...view(snap).querySelectorAll('.cs-cell')].map((c) => [c.querySelector('.cs-l').textContent, [c.querySelector('.cs-v').textContent, [...c.classList].find((x) => x !== 'cs-cell')]]));
const summary = (snap) => view(snap).querySelector('.cs-summary');

// everything closed: calm, one reassuring line, no alarm colours
let s = { windows_open: false, locked: true, doors_open: false, trunk_open: false, bonnet_open: false, lights_on: false };
assert.deepEqual(cells(s), { Doors: ['Locked', 'ok'], Windows: ['Closed', 'ok'], 'Trunk & bonnet': ['Closed', 'ok'], Lights: ['Off', 'ok'] });
assert.ok(summary(s).classList.contains('ok') && /Everything closed and locked/.test(summary(s).textContent));

// things open: they are named in the summary, flagged in their cell, and never also claimed closed
s = { windows_open: true, locked: false, doors_open: true, trunk_open: true, bonnet_open: false, lights_on: true };
let c = cells(s);
assert.equal(c.Doors[1], 'bad'); assert.equal(c.Windows[1], 'warn'); assert.equal(c['Trunk & bonnet'][1], 'bad'); assert.equal(c.Lights[1], 'info');
assert.ok(summary(s).classList.contains('bad') && /Door open/.test(summary(s).textContent) && /Window open/.test(summary(s).textContent) && /Trunk open/.test(summary(s).textContent));
assert.ok(!/Everything closed/.test(text(s)));

// only a window open: amber, not red
s = { windows_open: true, locked: true, doors_open: false, trunk_open: false, bonnet_open: false, lights_on: false };
assert.ok(summary(s).classList.contains('warn') && /Window open/.test(summary(s).textContent));

// unknown must never be shown as closed or locked
s = { windows_open: null, locked: null, doors_open: null, trunk_open: null, bonnet_open: null, lights_on: null };
c = cells(s);
assert.ok(Object.values(c).every(([v, k]) => v === 'Unknown' && k === 'unknown'), JSON.stringify(c));
assert.ok(summary(s).classList.contains('unknown') && /not reported/.test(summary(s).textContent));
assert.ok(!/Locked|Closed|Everything/.test(text(s)), text(s));

// partly known
s = { windows_open: false, locked: true, doors_open: false, trunk_open: null, bonnet_open: null, lights_on: null };
assert.ok(summary(s).classList.contains('partial') && /partly/.test(summary(s).textContent));

// unlocked but closed is flagged
s = { windows_open: false, locked: false, doors_open: false, trunk_open: false, bonnet_open: false, lights_on: false };
assert.equal(cells(s).Doors[0], 'Unlocked'); assert.ok(summary(s).classList.contains('bad'));

// sunroof
s = { windows_open: false, sunroof_open: true, locked: true, doors_open: false, trunk_open: false, bonnet_open: false, lights_on: false };
assert.equal(cells(s).Windows[0], 'Sunroof open');

// live line only when something is happening
assert.equal(view({ windows_open: false, locked: true }).querySelector('.badges'), null);
s = { charging: true, charge_power_kw: 10.8, soc: 64, remaining_min: 68, target_soc: 100, windows_open: false, locked: true };
assert.match(view(s).querySelector('.badges').textContent, /10\.8 kW · 64 % · 1 h 08 min to 100 %/);
assert.match(view({ charging: true }).querySelector('.badges').textContent, /Charging/);
console.log('car status states OK');

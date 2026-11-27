// Shared UI components. Everything returns DOM nodes built with h(); nothing parses HTML strings.
import { h, clear } from './dom.js';
import { icon } from './icons.js';
import { t } from '../i18n.js';

export function card(title, body, { actions, cls = '', icon: ic } = {}) {
  return h('section', { class: ['card', cls] },
    title || actions ? h('header', null, ic ? icon(ic, { size: 18 }) : null, h('h2', null, title), actions) : null,
    body);
}

export function stat(label, value, { sub, unit, ic, cls = '' } = {}) {
  return h('div', { class: ['stat', cls] },
    h('div', { class: 'label' }, ic ? icon(ic, { size: 15 }) : null, label),
    h('div', { class: 'value' }, value ?? '–', unit ? h('small', null, unit) : null),
    sub ? h('div', { class: 'sub' }, sub) : null);
}

export const chip = (text, kind = '', ic) => h('span', { class: ['chip', kind] }, ic ? icon(ic, { size: 13 }) : null, text);

export function button(label, { onClick, kind = '', ic, size = '', disabled, title, type = 'button' } = {}) {
  const b = h('button', { class: ['btn', kind, size], type, title, disabled, onclick: onClick },
    ic ? icon(ic, { size: 16 }) : null, label ? h('span', null, label) : null);
  return b;
}

/** Runs an async handler with a busy state; shows errors as a toast. */
export function asyncButton(label, handler, opts = {}) {
  const b = button(label, { ...opts, onClick: async () => {
    if (b.classList.contains('busy')) return;
    b.classList.add('busy'); b.setAttribute('aria-busy', 'true');
    try { await handler(); } catch (e) { toast(e.message || String(e), 'bad'); } finally { b.classList.remove('busy'); b.removeAttribute('aria-busy'); }
  } });
  return b;
}

export function banner(kind, ...content) {
  const ic = { warn: 'alert', bad: 'alert', info: 'info' }[kind] || 'info';
  return h('div', { class: ['banner', kind], role: kind === 'bad' ? 'alert' : null }, icon(ic, { size: 18 }), h('div', { class: 'grow' }, ...content));
}

export function empty(title, text, ic = 'info') {
  return h('div', { class: 'empty' }, icon(ic, { size: 30 }), h('strong', null, title), text ? h('div', null, text) : null);
}

export function loading(text = t('Loading…')) {
  return h('div', { class: 'empty', 'aria-busy': 'true' }, icon('refresh', { size: 26 }), h('div', null, text));
}

export function field(label, input, hint) {
  return h('label', { class: 'field' }, h('span', null, label), input, hint ? h('div', { class: 'tiny muted', style: { marginTop: '3px' } }, hint) : null);
}

export function seg(options, value, onChange, label) {
  const wrap = h('div', { class: 'seg', role: 'group', 'aria-label': label || null });
  const draw = (v) => {
    clear(wrap);
    for (const [val, label] of options) {
      wrap.append(h('button', { type: 'button', 'aria-pressed': String(val === v), onclick: () => { draw(val); onChange(val); } }, label));
    }
  };
  draw(value);
  return wrap;
}

export function kv(pairs) {
  const dl = h('dl', { class: 'kv' });
  for (const [k, v] of pairs) if (v !== undefined) dl.append(h('dt', null, k), h('dd', null, v ?? '–'));
  return dl;
}

/** Battery bar with an optional marker for the charge limit. */
export function socBar(soc, limit, { togo = false } = {}) {
  const cls = soc == null ? '' : soc < 15 ? 'low' : soc < 30 ? 'mid' : '';
  const from = Math.max(0, Math.min(100, soc ?? 0));
  return h('div', { class: ['bar', cls], role: 'img', 'aria-label': soc == null ? t('Battery unknown') : `${t('Battery')} ${Math.round(soc)} %` },
    h('i', { style: { width: `${from}%` } }),
    // striped stretch between now and the limit while charging: what is still to come
    togo ? h('u', { style: { left: `${from}%`, width: `${Math.min(100, limit) - from}%` } }) : null,
    limit != null ? h('b', { style: { left: `calc(${limit}% - 1.5px)` }, title: `${t('Charge limit')} ${limit} %` }) : null);
}

/**
 * table(columns, rows, {onRow, empty}) — columns: [{label, render(row), cls, num}]
 */
export function table(columns, rows, { onRow, emptyNode, label } = {}) {
  if (!rows.length) return emptyNode || empty(t('Nothing here yet'));
  const tbl = h('table', { class: 't' },
    h('thead', null, h('tr', null, ...columns.map((c) => h('th', { class: c.num ? 'num' : '' }, c.label)))),
    h('tbody', null, ...rows.map((r) => {
      const tr = h('tr', { class: onRow ? 'click' : '', tabindex: onRow ? 0 : null, onclick: onRow ? () => onRow(r) : null,
        onkeydown: onRow ? (e) => { if (e.key === 'Enter') onRow(r); } : null },
        ...columns.map((c) => h('td', { class: [c.num ? 'num' : '', c.cls] }, c.render(r))));
      return tr;
    })));
  // a region that can scroll sideways must be reachable and scrollable with the keyboard (WCAG 2.1.1)
  return h('div', { class: 'scroll-x', tabindex: 0, role: 'region', 'aria-label': label || t('Table') }, tbl);
}

// ---- modal / confirm / toast
/** `onClose` runs once when the dialog closes, however it closes (Escape, a click on the scrim, or `close()` from a button). */
export function modal(title, body, actions, { onClose } = {}) {
  const opener = document.activeElement;  // focus returns here when the dialog closes
  const scrim = h('div', { class: 'scrim', onclick: (e) => { if (e.target === scrim) close(); } });
  const focusables = () => [...m.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')]
    .filter((el) => el.getClientRects().length > 0);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    scrim.remove();
    document.removeEventListener('keydown', onKey);
    if (opener && opener.isConnected) opener.focus();
    if (onClose) onClose();
  };
  // Escape closes; Tab cycles inside the dialog (aria-modal alone does not stop assistive tech from leaving it).
  // Only the topmost dialog reacts, so Escape on a confirmation leaves the dialog under it open.
  const onKey = (e) => {
    if (scrim !== [...document.querySelectorAll('.scrim')].pop()) return;
    if (e.key === 'Escape') return close();
    if (e.key !== 'Tab') return;
    const items = focusables();
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener('keydown', onKey);
  const m = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('h2', null, title), body, h('div', { class: 'actions' }, ...(typeof actions === 'function' ? actions(close) : actions || [])));
  scrim.append(m);
  document.body.append(scrim);
  const first = m.querySelector('input,select,textarea,button');
  if (first) first.focus();
  return close;
}

export function confirmDialog(title, text, { confirmLabel = t('Confirm'), danger = false } = {}) {
  // Every way out ends in onClose, which resolves once: Escape, a click on the scrim and Cancel answer false, Confirm true.
  // `text` is a string (shown as one paragraph) or a prepared node (e.g. a paragraph plus a list of affected rows).
  return new Promise((resolve) => {
    let answer = false;
    modal(title, text instanceof Node ? text : h('p', null, text), (close) => [
      button(t('Cancel'), { onClick: close }),
      button(confirmLabel, { kind: danger ? 'danger' : 'primary', onClick: () => { answer = true; close(); } }),
    ], { onClose: () => resolve(answer) });
  });
}

let toastBox;
export function toast(message, kind = '') {
  if (!toastBox) { toastBox = h('div', { class: 'toasts', 'aria-live': 'polite' }); document.body.append(toastBox); }
  const el = h('div', { class: ['toast', kind], role: kind === 'bad' ? 'alert' : 'status' }, message);
  toastBox.append(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 8000 : 4500);
}

/** Keep a Save button disabled until the field differs from what is stored (nothing to save = nothing to press). Returns reset(newValue). */
export function enableOnChange(btn, input, initial = '') {
  let base = initial;
  const sync = () => { btn.disabled = input.value === base; };
  input.addEventListener('input', sync);
  sync();
  return (v) => { base = v; sync(); };
}

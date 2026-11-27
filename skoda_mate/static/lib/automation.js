// Settings → Automation: webhooks (add, edit, test, secret, delivery log) and the low-battery threshold.
// The signing secret reaches this code only in the answer to "create" and "new secret", and is shown once.
import { h, mount } from './dom.js';
import { icon } from './icons.js';
import { asyncButton, banner, button, card, chip, confirmDialog, field, loading, modal, toast } from './ui.js';
import * as f from './format.js';
import { t, tn, N_ } from '../i18n.js';

const EVENT_LABEL = {
  'trip.started': N_('Trip started'), 'trip.ended': N_('Trip ended'), 'charge.started': N_('Charging started'), 'charge.ended': N_('Charging ended'), 'charge.completed': N_('Charge limit reached'),
  'plug.connected': N_('Cable plugged in'), 'plug.disconnected': N_('Cable unplugged'), 'soc.low': N_('Battery low'), 'climate.started': N_('Climate started'), 'climate.ended': N_('Climate stopped'),
  'doors.opened': N_('Doors opened'), 'windows.opened': N_('Windows opened'), 'geofence.entered': N_('Arrived at a place'), 'geofence.left': N_('Left a place'), 'poll.failed': N_('Car data cannot be read'), test: N_('Test'),
};
const eventLabel = (name) => (EVENT_LABEL[name] ? t(EVENT_LABEL[name]) : name);
const STATUS = { ok: [N_('Delivered'), 'good', 'check'], failed: ['Failed', 'bad', 'alert'], pending: [N_('Waiting'), 'info', 'clock'], sending: [N_('Sending'), 'info', 'clock'] };
const statusChip = (d) => { const [label, kind, ic] = STATUS[d.status] || STATUS.failed; return chip(t(label), kind, ic); };
/** What the receiver answered: its HTTP status, or why there is none. */
const answerOf = (d) => [d.last_code ? `HTTP ${d.last_code}` : null, d.last_error ? t(d.last_error) : null].filter(Boolean).join(' · ');

export function automationCard(ctx) {
  const box = h('div');
  let data = null, error = null;

  async function load() {
    try { data = await ctx.api.get('/api/webhooks'); error = null; } catch (e) { data = null; error = e.message; }
    draw();
  }
  function showSecret(secret) {
    const input = h('input', { type: 'text', class: 'au-secret', readonly: true, value: secret, 'aria-label': t('Signing secret'), onfocus: (e) => e.target.select() });
    const body = h('div', { class: 'stack' }, banner('warn', t('Copy it now. Mate will not show it again.')), input,
      h('div', { class: 'small muted' }, t('Your receiver checks the X-Skoda-Mate-Signature header with it.')));
    modal(t('Signing secret'), body, (close) => [
      asyncButton(t('Copy'), async () => {
        try { await navigator.clipboard.writeText(secret); } catch { input.focus(); throw new Error(t('Could not copy. Select the text and copy it yourself.')); }
        toast(t('Copied'), 'good');
      }),
      button(t('Done'), { kind: 'primary', onClick: close }),
    ]);
  }

  function editor(hook) {
    const d = { name: hook?.name || '', url: hook?.url || '', enabled: hook ? hook.enabled : true, events: new Set(hook?.events || []) };
    const check = (checked, label, onChange, extra) => h('label', { class: 'b-check' },
      h('input', { type: 'checkbox', checked, onchange: (e) => onChange(e.target.checked) }), h('span', null, label, extra));
    const groups = data.event_groups.map((g) => h('fieldset', { class: 'au-group' }, h('legend', null, t(g.group)),
      ...g.events.map((name) => check(d.events.has(name), eventLabel(name), (on) => (on ? d.events.add(name) : d.events.delete(name)),
        h('code', { class: 'tiny muted au-code' }, name)))));
    const problem = h('div', { 'aria-live': 'polite' });
    let close = () => {};
    const body = h('div', { class: 'stack' },
      field(t('Name'), h('input', { type: 'text', maxlength: 60, autocomplete: 'off', value: d.name, oninput: (e) => { d.name = e.target.value; } })),
      field(t('URL'), h('input', { type: 'url', autocomplete: 'off', spellcheck: 'false', placeholder: 'http://192.168.1.10:8123/api/webhook/skoda-mate', value: d.url, oninput: (e) => { d.url = e.target.value; } })),
      banner('info', t('The events, including your car’s name and VIN and the names of your places, leave Mate and go to this address. Use an address you trust; https:// keeps them private on the way.')),
      h('h3', null, t('Events')), h('div', { class: 'au-events' }, ...groups),
      check(d.enabled, t('Enabled'), (on) => { d.enabled = on; }),
      hook ? h('div', { class: 'row' },
        asyncButton(t('New secret'), async () => {
          if (!await confirmDialog(t('Create a new secret?'), t('The old secret stops working at once. Your receiver needs the new one.'), { confirmLabel: t('New secret') })) return;
          const { secret } = await ctx.api.post(`/api/webhooks/${hook.id}/secret`);
          close(); await load(); showSecret(secret);
        }, { ic: 'key' }),
        asyncButton(t('Delete'), async () => {
          if (!await confirmDialog(t('Delete this webhook?'), t('Its delivery log is deleted too.'), { confirmLabel: t('Delete'), danger: true })) return;
          await ctx.api.del(`/api/webhooks/${hook.id}`);
          close(); toast(t('Webhook deleted'), 'good'); await load();
        }, { ic: 'trash', kind: 'danger' })) : null,
      problem);
    close = modal(t(hook ? N_('Edit webhook') : 'Add webhook'), body, (done) => [
      button(t('Cancel'), { onClick: done }),
      asyncButton(t('Save'), async () => {
        const payload = { name: d.name, url: d.url, enabled: d.enabled, events: [...d.events] };
        let made;
        try {
          made = hook ? await ctx.api.put(`/api/webhooks/${hook.id}`, payload) : await ctx.api.post('/api/webhooks', payload);
        } catch (e) { mount(problem, banner('bad', e.message)); return; }
        done(); await load();
        if (hook) toast(t('Webhook saved'), 'good'); else showSecret(made.secret);
      }, { ic: 'check', kind: 'primary' }),
    ]);
  }

  async function deliveryLog(hook) {
    const list = h('div', { class: 'stack' }, loading());
    const fill = async () => {
      const { deliveries } = await ctx.api.get(`/api/webhooks/${hook.id}/deliveries`);
      mount(list, deliveries.length ? h('ul', { class: 'au-log' }, ...deliveries.map((d) => h('li', { class: 'au-delivery' },
        h('div', { class: 'row between' }, h('strong', null, eventLabel(d.event)), statusChip(d)),
        h('div', { class: 'tiny muted' }, [f.dateTime(d.created_at), tn('{n} attempt', '{n} attempts', d.attempts), answerOf(d),
          d.next_at && d.attempts ? t('next try {time}', { time: f.dateTime(d.next_at) }) : null].filter(Boolean).join(' · ')),
        d.status === 'ok' || d.status === 'failed' ? asyncButton(t('Retry'), async () => {
          await ctx.api.post(`/api/webhooks/deliveries/${d.id}/retry`);
          toast(t('Queued again'), 'good'); await fill();
        }, { ic: 'refresh', size: 'sm' }) : null))) : h('div', { class: 'muted small' }, t('Nothing was sent yet.')));
    };
    modal(`${t('Last 20 deliveries')} · ${hook.name}`, list, (close) => [button(t('Close'), { onClick: close })], { onClose: load });
    try { await fill(); } catch (e) { mount(list, banner('bad', e.message)); }
  }

  function row(hook) {
    const last = hook.last_delivery;
    return h('li', { class: 'au-hook' },
      h('div', { class: 'row between' }, h('strong', { class: 'au-name' }, hook.name), hook.enabled ? chip(t('Enabled'), 'good', 'check') : chip(t('Disabled'), '', 'wifioff')),
      h('div', { class: 'small muted au-url' }, hook.url),
      h('div', { class: 'tiny muted' }, `${tn('{n} event', '{n} events', hook.events.length)}${last ? ` · ${t('Last delivery')}: ${t((STATUS[last.status] || STATUS.failed)[0])}, ${f.ago(last.created_at)}` : ''}`),
      hook.secret_unreadable ? banner('bad', t('The secret cannot be read. Create a new secret.')) : null,
      h('div', { class: 'row' },
        button(t('Edit'), { size: 'sm', onClick: () => editor(hook) }),
        asyncButton(t('Send test'), async () => {
          const result = await ctx.api.post(`/api/webhooks/${hook.id}/test`);
          toast(result.status === 'ok' ? t('The test was delivered.') : `${t('The test failed')}: ${answerOf(result)}`, result.status === 'ok' ? 'good' : 'bad');
          await load();
        }, { ic: 'signal', size: 'sm' }),
        button(t('Deliveries'), { size: 'sm', onClick: () => deliveryLog(hook) })));
  }

  function thresholdRow() {
    const [low, high] = data.soc_low_range;
    const input = h('input', { type: 'number', min: low, max: high, step: 1, inputmode: 'numeric', value: data.soc_low_threshold });
    return h('div', { class: 'form-row' },
      field(t('Low-battery warning below (%)'), input, t('The “Battery low” event is sent when the charge level falls below this value.')),
      asyncButton(t('Save'), async () => {
        await ctx.api.put('/api/webhooks/options', { soc_low_threshold: Number(input.value) });
        data.soc_low_threshold = Number(input.value);
        toast(t('Saved'), 'good');
      }, { ic: 'check' }));
  }

  function content() {
    if (error) return banner('bad', `${t('Could not load the webhooks')}: ${error}`);
    if (!data) return loading();
    return h('div', { class: 'stack' },
      h('div', { class: 'small muted' }, t('Mate sends signed JSON to your own address when something happens, for example to Home Assistant, Node-RED or n8n.')),
      h('h3', null, t('Webhooks')),
      data.webhooks.length ? h('ul', { class: 'au-hooks' }, ...data.webhooks.map(row)) : h('div', { class: 'small muted' }, t('No webhooks yet.')),
      h('div', null, h('button', { type: 'button', class: 'btn primary', onclick: () => editor(null) }, icon('plug', { size: 16 }), h('span', null, t('Add webhook')))),
      h('hr', { class: 'b-sep' }),
      thresholdRow());
  }

  function draw() { mount(box, card(t('Automation'), content(), { ic: 'signal', cls: 'au-card' })); }

  draw();
  load();
  return box;
}

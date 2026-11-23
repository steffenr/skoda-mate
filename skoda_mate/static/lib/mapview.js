// Leaflet maps, loaded on demand from cdnjs (pinned version) with OpenStreetMap tiles. Offline or blocked: a clear
// fallback with the coordinates instead of a blank box. Nothing is sent anywhere except tile requests.
import { h, clear } from './dom.js';
import { icon } from './icons.js';
import { t } from '../i18n.js';

// Subresource Integrity: the browser refuses a CDN file whose bytes differ from these hashes (a compromised or altered
// CDN cannot run code here). They belong to the exact pinned versions below: change a version, update its hashes
// (cdnjs lists them: https://api.cdnjs.com/libraries/<name>/<version>?fields=sri).
const CDN = { crossorigin: 'anonymous', referrerpolicy: 'no-referrer' };
const SRI = {
  'leaflet.min.css': 'sha512-h9FcoyWjHcOcmEVkxOfTLnmZFWIH0iZhZT1H2TbOq55xssQGEJHEaIm+PgoUaZbRvQTNTluNOEfb1ZRy6D3BOw==',
  'leaflet.min.js': 'sha512-puJW3E/qXDqYp9IfhAI54BJEaWIfloJ7JWs7OeD5i6ruC9JZL1gERT1wjtwXFlh7CjE7ZJ+/vcRZRkIYIb6p4g==',
  'L.Control.Locate.min.css': 'sha512-GzcB0NJ8U8qLDuXPvmTqnEuspU6oJ/bJuCIEqz2Xp+RreBuU+b4eax68kmC4kaNhhgAVa0kw+h9AJSNkBYijoA==',
  'L.Control.Locate.min.js': 'sha512-aAeieEn956BhgggbPtNf8V57jo5x79HhHoUbnmmiyeJTD8pej211YKnIgmywIPLlSKBFaBQbLbb44BcnzWrb3Q==',
};

const VERSION = '1.9.4';
const BASE = `https://cdnjs.cloudflare.com/ajax/libs/leaflet/${VERSION}`;
let loader;

export function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (loader) return loader;
  loader = new Promise((resolve, reject) => {
    document.head.append(h('link', { rel: 'stylesheet', href: `${BASE}/leaflet.min.css`, integrity: SRI['leaflet.min.css'], ...CDN }));
    const s = h('script', { src: `${BASE}/leaflet.min.js`, integrity: SRI['leaflet.min.js'], ...CDN });
    s.onload = () => resolve(window.L);
    s.onerror = () => { loader = null; reject(new Error('Leaflet could not be loaded')); };
    document.head.append(s);
  });
  return loader;
}

// Optional "show my position" button (leaflet.locatecontrol, pinned). It uses the browser's geolocation, which only works
// on https:// or localhost and only after the user allows it; the position never leaves the browser.
const LOCATE = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet-locatecontrol/0.82.0';
let locateLoader;
function loadLocate() {
  if (window.L?.control?.locate) return Promise.resolve();
  if (locateLoader) return locateLoader;
  locateLoader = new Promise((resolve, reject) => {
    document.head.append(h('link', { rel: 'stylesheet', href: `${LOCATE}/L.Control.Locate.min.css`, integrity: SRI['L.Control.Locate.min.css'], ...CDN }));
    const s = h('script', { src: `${LOCATE}/L.Control.Locate.min.js`, integrity: SRI['L.Control.Locate.min.js'], ...CDN });
    s.onload = () => resolve();
    s.onerror = () => { locateLoader = null; reject(new Error('locate plugin could not be loaded')); };
    document.head.append(s);
  });
  return locateLoader;
}

// `scale` 1 = 26 px; use it to size markers by importance (e.g. how often the car stood there).
const pinIcon = (L, kind = '', scale = 1) => {
  const s = Math.round(26 * Math.max(0.6, Math.min(scale, 2)));
  const el = document.createElement('div');
  el.className = `pin ${kind}`;
  el.style.width = el.style.height = `${s}px`;
  return L.divIcon({ className: '', html: el, iconSize: [s, s], iconAnchor: [s / 2, s], popupAnchor: [0, -s + 2] });
};
const cssColor = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

/**
 * mapView({height:'short'|''|'tall', markers:[{lat,lon,kind?,label?,html?}], lines:[[ [lat,lon], [lat,lon] ]], fit?:true})
 * Returns a container element immediately; the map appears when Leaflet is ready. `.update(opts)` redraws markers.
 */
export function mapView(opts) {
  const box = h('div', { class: ['map', opts.height || ''] });
  let map, layer, L;
  const fallback = (why) => {
    clear(box);
    const pts = (opts.markers || []).slice(0, 6);
    box.append(h('div', { class: 'map-fallback' }, h('div', null, icon('map', { size: 28 }),
      h('div', null, t('The map could not be loaded')), h('div', { class: 'tiny' }, why),
      ...pts.map((p) => h('div', { class: 'tiny' }, `${p.label || ''} ${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`)))));
  };
  const paint = (o) => {
    layer.clearLayers();
    const bounds = [];
    for (const ln of o.lines || []) { L.polyline(ln, { color: o.lineColor || cssColor('--accent', '#0b7a52'), weight: 4, opacity: .8, dashArray: o.dashed ? '6 8' : null }).addTo(layer); bounds.push(...ln); }
    for (const m of o.markers || []) {
      const mk = L.marker([m.lat, m.lon], { icon: pinIcon(L, m.kind, m.scale), title: m.label || '', draggable: !!m.draggable, keyboard: true }).addTo(layer);
      if (m.label && !m.draggable) mk.bindPopup(h('div', null, m.label));  // a DOM node, never a string: Leaflet would parse a string as HTML
      if (m.draggable && m.onDrag) mk.on('dragend', () => { const p = mk.getLatLng(); m.onDrag(p.lat, p.lng); });
      bounds.push([m.lat, m.lon]);
    }
    if (o.circle && o.circle.lat != null) {  // e.g. the home radius
      L.circle([o.circle.lat, o.circle.lon], { radius: o.circle.radius, color: o.lineColor || cssColor('--accent', '#0b7a52'), weight: 2, fillOpacity: 0.12, interactive: false }).addTo(layer);
      if (o.fit !== false) {  // circle.getBounds() needs a map view that does not exist yet on first paint: do the maths
        const dLat = o.circle.radius / 111320, dLon = dLat / Math.max(0.2, Math.cos((o.circle.lat * Math.PI) / 180));
        bounds.push([o.circle.lat - dLat, o.circle.lon - dLon], [o.circle.lat + dLat, o.circle.lon + dLon]);
      }
    }
    if (o.fit !== false && bounds.length) {
      if (bounds.length === 1) map.setView(bounds[0], o.zoom || 15);
      else map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
    } else if (!bounds.length) map.setView([50.1, 8.7], 5);
  };
  loadLeaflet().then((Lf) => {
    L = Lf;
    map = L.map(box, { scrollWheelZoom: false });
    // OSM's tile policy demands a Referer (else 403 "Access blocked"): send the origin, whatever the page policy says.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '© OpenStreetMap', referrerPolicy: 'strict-origin-when-cross-origin' }).addTo(map);
    layer = L.layerGroup().addTo(map);
    if (opts.onPick) { map.on('click', (e) => opts.onPick(e.latlng.lat, e.latlng.lng)); box.style.cursor = 'crosshair'; }
    if (opts.locate) {  // a missing plugin must never break the map itself
      loadLocate().then(() => {
        L.control.locate({ position: 'topleft', setView: opts.onLocate ? false : 'once', flyTo: true, showPopup: false, drawCircle: true,
          strings: { title: t('Show my position') }, locateOptions: { enableHighAccuracy: true, maxZoom: 17 } }).addTo(map);
        map.on('locationfound', (e) => opts.onLocate && opts.onLocate(e.latlng.lat, e.latlng.lng, e.accuracy));
        map.on('locationerror', (e) => opts.onLocateError && opts.onLocateError(e.message));
      }).catch(() => {});
    }
    paint(opts);
    new ResizeObserver(() => map.invalidateSize()).observe(box);
    setTimeout(() => map.invalidateSize(), 120);
    box.map = map;  // the Leaflet map, e.g. box.map.flyTo([lat, lon], 15) to focus an item
    box.update = (o) => paint({ ...opts, ...o });
  }).catch((e) => fallback(e.message));
  box.update = (o) => { opts = { ...opts, ...o }; };
  return box;
}

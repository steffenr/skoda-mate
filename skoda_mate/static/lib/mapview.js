// Leaflet maps, loaded on demand from cdnjs (pinned version) with OpenStreetMap tiles. Offline or blocked: a clear
// fallback with the coordinates instead of a blank box. Marker clustering is optional: when its plugin cannot load the
// map keeps plain pins. Nothing is sent anywhere except tile and CDN requests.
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
  'MarkerCluster.min.css': 'sha512-ENrTWqddXrLJsQS2A86QmvA17PkJ0GVm1bqj5aTgpeMAfDKN2+SIOLpKG8R/6KkimnhTb+VW5qqUHB/r1zaRgg==',
  'MarkerCluster.Default.min.css': 'sha512-fYyZwU1wU0QWB4Yutd/Pvhy5J1oWAwFXun1pt+Bps04WSe4Aq6tyHlT4+MHSJhD8JlLfgLuC4CbCnX5KHSjyCg==',
  'leaflet.markercluster.min.js': 'sha512-TiMWaqipFi2Vqt4ugRzsF8oRoGFlFFuqIi30FFxEPNw58Ov9mOy6LgC05ysfkxwLE0xVeZtmr92wVg9siAFRWA==',
};

const VERSION = '1.9.4';
const BASE = `https://cdnjs.cloudflare.com/ajax/libs/leaflet/${VERSION}`;
let loader;

// Crowded maps group nearby pins; pages pass `cluster: false` to keep every pin separate.
export const CLUSTER_OPTIONS = { maxClusterRadius: 50, disableClusteringAtZoom: 14, chunkedLoading: true, showCoverageOnHover: false, spiderfyOnMaxZoom: true };
const CLUSTER_VERSION = '1.5.3';
const CLUSTER_BASE = `https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/${CLUSTER_VERSION}`;

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

// Marker clustering (leaflet.markercluster, pinned) is an enhancement, never a dependency: a blocked or broken CDN leaves
// the caller's plain marker layer in place, so the map still shows every pin. The promise resets on failure, so a later
// call can retry instead of being stuck on the failed load.
let clusterLoader;
export function loadMarkerCluster() {
  if (window.L?.markerClusterGroup) return Promise.resolve();
  if (clusterLoader) return clusterLoader;
  clusterLoader = new Promise((resolve, reject) => {
    const fail = () => { clusterLoader = null; reject(new Error('marker cluster plugin could not be loaded')); };
    document.head.append(
      h('link', { rel: 'stylesheet', href: `${CLUSTER_BASE}/MarkerCluster.min.css`, integrity: SRI['MarkerCluster.min.css'], ...CDN }),
      h('link', { rel: 'stylesheet', href: `${CLUSTER_BASE}/MarkerCluster.Default.min.css`, integrity: SRI['MarkerCluster.Default.min.css'], ...CDN }));
    const s = h('script', { src: `${CLUSTER_BASE}/leaflet.markercluster.min.js`, integrity: SRI['leaflet.markercluster.min.js'], ...CDN });
    s.onload = () => (window.L?.markerClusterGroup ? resolve() : fail());  // a blocked or truncated file can still fire load
    s.onerror = fail;
    document.head.append(s);
  });
  return clusterLoader;
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
 * mapView({height:'short'|''|'tall', markers:[{lat,lon,kind?,label?,scale?,draggable?,noCluster?,onDrag?}],
 *   lines:[[ [lat,lon], [lat,lon] ]], circles:[{lat,lon,radius,color?,label?,id?}], circle?:{...}, cluster?:false,
 *   onCircleClick?: (id) => void, onMapClick?: (lat, lon) => void, fit?:true})
 * A circle's `label` becomes a text tooltip; only a circle with an `id` is clickable (onCircleClick) and stops map clicks,
 * so the legacy ownerless `circle` stays click-through.
 * Returns a container element immediately; the map appears when Leaflet is ready. `.update(opts)` redraws markers.
 */
export function mapView(opts) {
  const box = h('div', { class: ['map', opts.height || ''] });
  let map, lineLayer, markerLayer, plainLayer, L;
  const fallback = (why) => {
    clear(box);
    const pts = (opts.markers || []).slice(0, 6);
    box.append(h('div', { class: 'map-fallback' }, h('div', null, icon('map', { size: 28 }),
      h('div', null, t('The map could not be loaded')), h('div', { class: 'tiny' }, why),
      ...pts.map((p) => h('div', { class: 'tiny' }, `${p.label || ''} ${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`)))));
  };
  // A click on a place (circle) or a pin must not also reach the map's click handler, which may create a draft point.
  const stopClick = (e) => { if (e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent); };
  // The badge is a DOM node with textContent, never an HTML string: Leaflet would parse a string as markup.
  const clusterIcon = (cluster) => {
    const n = cluster.getChildCount();
    const size = n < 10 ? 34 : n < 100 ? 38 : 44;
    return L.divIcon({ className: '', html: h('div', { class: 'marker-cluster pin-cluster' }, String(n)), iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
  };
  const paint = (o) => {
    for (const l of [lineLayer, markerLayer, plainLayer]) l.clearLayers();
    const bounds = [];
    for (const ln of o.lines || []) { L.polyline(ln, { color: o.lineColor || cssColor('--accent', '#0b7a52'), weight: 4, opacity: .8, dashArray: o.dashed ? '6 8' : null }).addTo(lineLayer); bounds.push(...ln); }
    const circles = [...(o.circles || [])];
    if (o.circle && o.circle.lat != null) circles.unshift(o.circle);  // e.g. the home radius; kept for older callers
    for (const c of circles) {
      if (c.lat == null) continue;
      // Only a circle that identifies a place is interactive: the legacy ownerless `o.circle` (e.g. the prices page's home
      // radius) stays a passive hint, so a click inside it still reaches the map's click-to-place handler.
      const place = c.id != null;
      const shape = L.circle([c.lat, c.lon], { radius: c.radius, color: c.color || o.lineColor || cssColor('--accent', '#0b7a52'),
        weight: 1.5, fillOpacity: 0.08, interactive: place, bubblingMouseEvents: false }).addTo(lineLayer);
      if (c.label) shape.bindTooltip(h('div', null, String(c.label)));  // a DOM node, never a string: Leaflet parses strings as HTML
      if (place) shape.on('click', (e) => { stopClick(e); o.onCircleClick?.(c.id); });
      if (o.fit !== false) {  // circle.getBounds() needs a map view that does not exist yet on first paint: do the maths
        const dLat = c.radius / 111320, dLon = dLat / Math.max(0.2, Math.cos((c.lat * Math.PI) / 180));
        bounds.push([c.lat - dLat, c.lon - dLon], [c.lat + dLat, c.lon + dLon]);
      }
    }
    for (const m of o.markers || []) {
      const mk = L.marker([m.lat, m.lon], { icon: pinIcon(L, m.kind, m.scale), title: m.label || '', draggable: !!m.draggable, keyboard: true });
      if (m.label && !m.draggable) mk.bindPopup(h('div', null, m.label));  // a DOM node, never a string: Leaflet would parse a string as HTML
      if (m.draggable && m.onDrag) mk.on('dragend', () => { const p = mk.getLatLng(); m.onDrag(p.lat, p.lng); });
      mk.on('click', stopClick);
      (m.noCluster || m.draggable ? plainLayer : markerLayer).addLayer(mk);  // dragged pins never disappear into a cluster
      bounds.push([m.lat, m.lon]);
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
    lineLayer = L.layerGroup().addTo(map);
    markerLayer = L.layerGroup().addTo(map);
    plainLayer = L.layerGroup().addTo(map);
    // onMapClick covers draft points; onPick is the older name and keeps working.
    map.on('click', (e) => { opts.onMapClick?.(e.latlng.lat, e.latlng.lng); });
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
    if (opts.cluster !== false) {
      // Pins are drawn immediately; the cluster group replaces their layer only once the plugin has actually loaded.
      // A rejection leaves the plain layer in place, so there is never a blank map or an error banner for an optional extra.
      loadMarkerCluster().then(() => {
        markerLayer.remove();
        markerLayer = L.markerClusterGroup({ ...CLUSTER_OPTIONS, iconCreateFunction: clusterIcon }).addTo(map);
        plainLayer.remove(); plainLayer.addTo(map);  // drag handles and the car stay above the clusters
        paint(opts);
      }).catch(() => {});
    }
    new ResizeObserver(() => map.invalidateSize()).observe(box);
    setTimeout(() => map.invalidateSize(), 120);
    box.map = map;  // the Leaflet map, e.g. box.map.flyTo([lat, lon], 15) to focus an item
    box.update = (o) => { opts = { ...opts, ...o }; paint(opts); };
  }).catch((e) => fallback(e.message));
  box.update = (o) => { opts = { ...opts, ...o }; };
  return box;
}

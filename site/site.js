// Theme toggle, same behaviour as the dashboard: one button that switches to the opposite
// theme, remembers the choice, and shows sun in the dark / moon in the light.
(function () {
  var root = document.documentElement;
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  var sun = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Z"/>' +
    '<path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/></svg>';
  var moon = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M20.5 14.2A8.5 8.5 0 0 1 9.8 3.5a8.5 8.5 0 1 0 10.7 10.7Z"/></svg>';
  var dark = function () {
    return (root.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  };
  var labels = function () {
    // English until i18n.js loads a catalog, then the translated titles
    var l = window.__i18nLabels || {};
    return { light: l.light || 'Switch to light theme', dark: l.dark || 'Switch to dark theme' };
  };
  var paint = function () {
    btn.innerHTML = dark() ? sun : moon;
    var label = dark() ? labels().light : labels().dark;
    btn.title = label;
    btn.setAttribute('aria-label', label);
  };
  btn.addEventListener('click', function () {
    var next = dark() ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('skoda-mate-theme', next); } catch (e) { /* keep the session choice */ }
    paint();
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', paint);
  window.__paintTheme = paint;  // i18n.js re-calls this after loading a language
  paint();
})();

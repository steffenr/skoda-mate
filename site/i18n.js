// Landing-page i18n: the HTML carries English as the fallback; these JSON catalogs add the other
// 13 languages the app ships (same wording where the app already translates a term).
// The language comes from a stored choice, else the browser, else English; switched in the footer,
// without a reload. Translations are machine-drafted like the app's newer catalogs and marked for
// a native-speaker pass (docs/TRANSLATIONS.md).
(function () {
  'use strict';
  var NAMES = null;
  var CODES = ['en', 'ca', 'da', 'de', 'nl', 'fi', 'fr', 'hu', 'it', 'nb', 'es', 'sv', 'tr', 'uk'];

  function stored() {
    try { return localStorage.getItem('skoda-mate-lang'); } catch (e) { return null; }
  }
  function browserLang() {
    var prefs = navigator.languages || [navigator.language || 'en'];
    for (var i = 0; i < prefs.length; i++) {
      var p = prefs[i].toLowerCase();
      if (p === 'nn' || p.indexOf('nn') === 0) p = 'nb' + p.slice(2); // Nynorsk users get Bokmål
      for (var j = 0; j < CODES.length; j++) {
        if (p === CODES[j] || p.indexOf(CODES[j] + '-') === 0) return CODES[j];
      }
    }
    return 'en';
  }
  function wanted() {
    var s = stored();
    return s && CODES.indexOf(s) >= 0 ? s : browserLang();
  }

  var dicts = { en: null };
  var current = null;

  function apply(lang, dict) {
    current = lang;
    dicts[lang] = dict;
    document.documentElement.lang = lang === 'nb' ? 'nb' : lang;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var v = dict[el.dataset.i18n];
      if (typeof v === 'string') el.textContent = v;
    });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      var v = dict[el.dataset.i18nHtml];
      if (typeof v === 'string') el.innerHTML = v;
    });
    window.__i18nLabels = {
      light: dict.theme_to_light || 'Switch to light theme',
      dark: dict.theme_to_dark || 'Switch to dark theme',
    };
    if (window.__paintTheme) window.__paintTheme();
    var sel = document.getElementById('lang-select');
    if (sel) sel.value = lang;
  }

  function set(lang) {
    try { localStorage.setItem('skoda-mate-lang', lang); } catch (e) { /* keep the session choice */ }
    var dict = dicts[lang];
    if (dict) { apply(lang, dict); return; }
    fetch('i18n/' + lang + '.json').then(function (r) { return r.json(); }).then(function (dict) {
      apply(lang, dict);
    }).catch(function () { /* offline or bad catalog: English stays */ });
  }

  document.addEventListener('DOMContentLoaded', function () {
    fetch('i18n/languages.json').then(function (r) { return r.json(); }).then(function (n) { NAMES = n; });
    var sel = document.getElementById('lang-select');
    if (sel) {
      sel.innerHTML = '';
      CODES.forEach(function (code) {
        var o = document.createElement('option');
        o.value = code;
        o.textContent = (NAMES && NAMES[code]) || code;
        sel.appendChild(o);
      });
      sel.addEventListener('change', function () { set(sel.value); });
    }
    set(wanted());
  });

  window.__setLang = set;
})();

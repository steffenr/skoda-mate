// Landing-page i18n: the HTML carries English as the fallback; these JSON catalogs add the other
// 14 languages the app ships (same wording where the app already translates a term).
// The language comes from a stored choice, else the browser, else English; switched with the
// selector in the header, without a reload. Translations are machine-drafted like the app's newer
// catalogs and marked for a native-speaker pass (docs/TRANSLATIONS.md).
(function () {
  'use strict';
  var NATIVE = {
    en: 'English', ca: 'Català', cs: 'Čeština', da: 'Dansk', de: 'Deutsch', nl: 'Nederlands', fi: 'Suomi',
    fr: 'Français', hu: 'Magyar', it: 'Italiano', nb: 'Norsk bokmål', es: 'Español',
    sv: 'Svenska', tr: 'Türkçe', uk: 'Українська',
  };
  var CODES = Object.keys(NATIVE);

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
    return s && NATIVE[s] ? s : browserLang();
  }

  var dicts = { en: null };
  var current = null;

  function apply(lang, dict) {
    current = lang;
    dicts[lang] = dict;
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var v = dict[el.dataset.i18n];
      if (typeof v === 'string') el.textContent = v;
    });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      var v = dict[el.dataset.i18nHtml];
      if (typeof v === 'string') el.innerHTML = v;
    });
    document.querySelectorAll('[data-i18n-aria]').forEach(function (el) {
      var v = dict[el.dataset.i18nAria];
      if (typeof v === 'string') el.setAttribute('aria-label', v);
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
    var sel = document.getElementById('lang-select');
    if (sel) {
      sel.innerHTML = '';
      CODES.forEach(function (code) {
        var o = document.createElement('option');
        o.value = code;
        o.textContent = NATIVE[code]; // always the full native name
        sel.appendChild(o);
      });
      sel.addEventListener('change', function () { set(sel.value); });
    }
    set(wanted());
  });

  window.__setLang = set;
})();

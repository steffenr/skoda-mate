# Translations

The dashboard is written in English. Every other language is one file, `skoda_mate/static/i18n/<code>.json`.
Setup and login are English only: they are shown before the language setting exists.

## How a text is translated

| In the code | In the catalog |
|---|---|
| `t('Trips')` | `"Trips": "Fahrten"` |
| `t('Updated {ago}', { ago })` | `"Updated {ago}": "Aktualisiert {ago}"` |
| `t('Open##action')` | `"Open##action": "Öffnen"` (and `"Open": "Offen"`) |
| `tn('{n} trip', '{n} trips', n)` | `"{n} trips": {"one": "{n} Fahrt", "other": "{n} Fahrten"}` |
| `N_('Public DC')` in a table, translated later with `t(row)` | `"Public DC": "…"` |
| a backend template in `skoda_mate/messages.py` | the template itself as the key |

- **The key is the English text.** Changing the English changes the key, so every catalog needs it again; coverage says so.
- **`##context`** tells apart one English text that needs two translations. English shows only the part before `##`.
- **Placeholders** (`{ago}`) keep their names. Move them wherever the sentence needs them. Quotation marks around a
  placeholder are part of the text: use your language's own (`„{name}“`, `« {name} »`). A fraction sent by the
  backend is already written the way the locale writes it.
- **Plural forms** follow the [CLDR plural rules](https://www.unicode.org/cldr/charts/latest/supplemental/language_plural_rules.html):
  give every category the language has (German: `one`, `other`; Ukrainian: `one`, `few`, `many`, `other`; Japanese:
  `other`). `{n}` may be left out only of a form that stands for a single number (German `one` is just 1; Ukrainian
  `one` is also 21 and French `one` also 0, so those keep `{n}`).
- **Whole sentences.** Never join translated pieces, put a translated word into another sentence, or change a
  translation's case in code.
- **Not translated:** product names (Škoda, MyŠkoda, Home Assistant, MQTT), units, and what the car or Škoda reports
  (names, addresses, raw values the app does not know).

## Backend messages

A refusal or status keeps its English text where it always was (`detail`, `error`, `message`) and gains
`<field>_i18n: {"message": template, "params": {…}}`. The dashboard translates the template; other clients can keep
reading the English. The template is not a stable error code: it changes when the wording does. MQTT and webhook
payloads and the stored logs stay English.

## The key list

`skoda_mate/static/i18n/keys.json` lists every key, where it is used (context for translators) and, for plural keys, the
English singular. Two extractors write it, and CI fails when it is stale:

```sh
node scripts/dom-smoke/i18n_extract.mjs          # the frontend section
.venv/bin/python scripts/i18n_backend.py         # the backend section
node scripts/dom-smoke/i18n_coverage.mjs         # every catalog against the list
```

Coverage fails on a missing or unused entry, a changed placeholder, a missing plural form, and on a lowercase key that
looks like a piece of a sentence.

## Adding a language

1. Write `skoda_mate/static/i18n/<code>.json` with every key of `keys.json`, one entry per line, keys sorted.
2. Register it: `CATALOGS` in `static/i18n.js` and `LANGUAGES` in `skoda_mate/languages.py` (code, name in the language
   itself, BCP 47 locale such as `zh-Hans`). A language is listed only when coverage passes for it.
3. Look at it: with a demo server, switch the language in Settings and go through the pages at phone width.
   `browser_e2e.mjs` also opens every page at 360 px in each offered language and fails on overflow, after a pseudo-language
   pass (`pseudo_pass.mjs`) with longer text.
4. Record its review state below.

Automated checks find missing text and broken placeholders. They cannot tell whether a text reads well, so a person who
speaks the language should check it before it is released.

## Machine translation

Drafts may come from a translation service, run by hand by a developer; the app and CI never call one. Send only texts
from `keys.json` and notes about them, never anything from `data/`, `.env`, logs or screenshots. No service key belongs
in the repository, a project settings file, a script or CI. Check placeholders with coverage afterwards.

## Review state

| Language | Catalog | Review |
|---|---|---|
| English (source) | — | — |
| German | `de.json` | reference translation |

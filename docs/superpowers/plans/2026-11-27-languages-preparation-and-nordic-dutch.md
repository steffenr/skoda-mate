# Languages: Preparation, then Danish, Dutch, Swedish, Norwegian and Finnish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the interface safe to translate, then add da, nl, sv, nb and fi.

**Architecture:** Part A closes the gaps that would otherwise be translated into every language, in one PR. Part B
builds a translator brief from `keys.json` and the sources; one subagent per language writes its catalog and its
glossary; the existing coverage, browser and a back-translation check gate it. A second PR.

**Tech Stack:** as batch 1; DeepL's hosted connector only for the back-translation check.

**Spec:** `docs/superpowers/specs/2026-11-26-places-insight-automation-design.md` §4.11. Earlier: batch 1 plan,
`2026-11-27-languages-framework.md`, and `docs/TRANSLATIONS.md`.

## Global Constraints

- Group by group (chosen 2026-11-27). Release rule as the spec says: a language is offered once its catalog is complete
  and passes the checks; `docs/TRANSLATIONS.md` states whether a person who speaks it has reviewed it; the app shows no
  badge; no machine-only translation is called reviewed. **Confirm this when reviewing the plan.**
- English and German wording on screen changes only where a task says so.
- No new dependency or build step. The app and CI call no translation service. No service key anywhere in the
  repository. To DeepL go only catalog texts, never `data/`, `.env`, logs or screenshots.
- Units (`km`, `kWh`, `h`, `min`, `s`) stay independent of the language, as the spec says.
- Gates after each part: pytest, ruff, mypy, `unit.mjs`, both `--check` extractors, `i18n_coverage.mjs`, and the four
  browser-job steps in Docker. Every fix gets a test.
- Part A on `feature/language-prep`, Part B on a new branch from `main` after A is merged. Commit per task; push and
  open a PR when its part is done and the user asks.

## Review Focus

1. The catalog request hangs: the dashboard appears in English within a few seconds instead of staying blank. (A2)
2. A catalog is not an object (`null`, a list, an HTML error page): English, no crash. (A2)
3. A translator copies English through, or translates a product name, topic path or setting name: it is listed for
   review. (B1)
4. A translator's file is cut off or has a duplicate key: assembling fails and names the part and the key. (B1)
5. A long Finnish compound in a tab, chip, button or table head at 360 px: nothing overflows. (B3)

---

# Part A: preparation

### A1: Plural rules from the registered locale

**Files:** `scripts/dom-smoke/i18n_lib.mjs`, `i18n_coverage.mjs`, `unit.mjs`.
**Produces:** `languages(): {code, name, locale}[]`, read from `skoda_mate/languages.py`.

- [ ] Test: `languages()` returns the entries of `languages.py` (today en and de with their locales); coverage fails,
  naming the code, for a catalog in `CATALOGS` with no entry there.
- [ ] Implement; coverage passes `locale` to `compare`. Run the checks. Commit.

### A2: A catalog that fails leaves a consistent English page

**Files:** `static/i18n.js`, `static/app.js`, `unit.mjs`.
**Produces:** after a failed load, `getLang() === 'en'` and `getLocale() === 'en'`; `app.js` takes the format locale and
`<html lang>` from `getLocale()` after `await setLang()`.

- [ ] Tests: a rejecting load, a load resolving to `null`, to `[]` and to a string all give `en`/`en` and English text;
  `jsonCatalog` passes an abort signal that fires after 5 s (inject the timeout so the test does not wait).
- [ ] Implement with `AbortSignal.timeout`. Commit.

### A3: What would be wrong in another language

**Files:** `pages/{system,stats,capabilities,charges,events}.js`, `static/i18n.js`, `messages.py`, `commands.py`,
`importer.py`, `merge.py`, `presenters.py`, `de.json`, `keys.json`.

- [ ] Tests first, one per item:
  - `Reviewed {date}` is one key; `{n} inferred` is one key; the two sentences under "Request limit" are two separate
    elements, with no `. ` joined in code.
  - Counts that other languages inflect use `tn`: `{n} changed`, `{n} reviewed`, `and {n} more`, `{n} Running`,
    `{n} Important`, `{n} Info`, `{n} inferred`.
  - `tm` formats a non-integer number parameter for the locale (15.5 reads "15,5" in German); integers and strings stay.
    `CMD_RANGE` sends numbers.
  - Quotes belong to the template, not to the value: `BAD_DATE`, `CMD_UNKNOWN`, `IMPORT_TIME_ZONE`, `IMPORT_BAD_DATE`
    send the bare value. The English `detail` reads as before.
  - The `24 h` legend goes through `t()` (German "24 Std.").
- [ ] Implement; add German; run extractors and coverage; compare text snapshots (baseline: `main` before this part) and
  list each difference in the commit message. Commit.

### A4: Language picker and a layout check per language

**Files:** `pages/settings.js`, `lib/ui.js`, `scripts/dom-smoke/{browser_e2e,pseudo_pass,text_snapshot}.mjs`.
**Produces:** a `<select id="set-lang">` with one `<option lang=…>` per entry of `S.languages`;
`layoutPass(browser, base, code, check, errors)` in `pseudo_pass.mjs`.

- [ ] Change the e2e steps that press "Deutsch" to choose the option; watch them fail.
- [ ] Implement. `layoutPass` opens every route at 360 px in a real language and fails on horizontal overflow;
  `browser_e2e.mjs` runs it for each language of `GET /api/settings` except `en`. Commit.

### A5: Gates, review, PR

- [ ] All gates. One fresh reviewer for Part A against Review Focus 1 and 2; fix Critical and Important findings.
- [ ] Report; PR when the user asks.

---

# Part B: da, nl, sv, nb, fi

Locales: `da`, `nl`, `sv`, `nb`, `fi` (names: Dansk, Nederlands, Svenska, Norsk bokmål, Suomi). All five have the
plural forms `one` and `other`.

### B1: Brief, assembly and lint

**Files:** create `scripts/dom-smoke/i18n_brief.mjs`, `i18n_assemble.mjs`, `scripts/i18n_notes.json`,
`scripts/i18n_terms.md`; modify `i18n_lib.mjs`, `unit.mjs`.

**Produces:**
- `brief(locale)`: one entry per key `{key, english, one?, categories: {category: [example numbers]}, files,
  line, note?}`; `line` is the first source line (JS or Python) holding the text. Written in parts of 240 entries.
  It reads no catalog.
- `i18n_notes.json`: `{key: note}` for every key with a context suffix and every key of one or two words whose meaning
  the line does not show.
- `i18n_terms.md`: the app's terms with a one-line English definition each (trip, charge, charging session, charging
  profile, place, home place, parked loss, odometer, charge level, range, preconditioning, webhook, delivery) and what
  stays untranslated (product names, units, MQTT topics, setting and parameter names such as `DEMO=1`, API values).
- `assemble(parts, keys, locale) -> {catalog, problems}`: merges `<code>.part<n>.json`; problems for a part that is not
  valid JSON, a key twice, and everything `compare` reports.
- `lint(keys, catalog) -> string[]`: texts identical to the English, and a protected token of the English (product name,
  `{…}/VIN/…` path, `X=1` setting, ALL_CAPS value) missing from the translation. A list for review, not a gate.

- [ ] Tests for `brief` (a plural key carries both English forms and the locale's categories; no German appears),
  `assemble` (truncated part, duplicate key) and `lint` (copied English, translated product name).
- [ ] Implement; every context key has a note. Commit.

### B2: Translate

- [ ] One subagent per language, five, in parallel. Each reads only the brief parts and `i18n_terms.md`, calls no
  translation service, and writes: `docs/translations/<code>.md` **first** (form of address with one line of reasoning,
  its word for every term, open questions), then the parts. It runs nothing else and edits no other file.
  Pilot rule: start Danish alone; when its parts assemble and the lint list has been read, start the other four.
- [ ] Assemble each; send problems back to the same subagent until `compare` reports none.
- [ ] Read each lint list; send real faults back. Commit per language.

### B3: Check, register, document

- [ ] Back-translation check per language: about 100 texts (all context keys, short labels and the lint hits) through
  DeepL `translate-text` into English, placeholders left in. Compare meaning with the English. For each doubtful one,
  give the same subagent the finding; it fixes the text or says why it stands. DeepL does not write catalog text.
  A language DeepL cannot read is recorded as not checked.
- [ ] Register each complete language in `CATALOGS` and `languages.py`; `test_languages.py` expects seven entries,
  sorted en, de, then by native name.
- [ ] `docs/TRANSLATIONS.md`: review table with, per language, "not reviewed by a speaker" or who reviewed it, and how
  to report a wrong text. README lists the languages. `docs/FEATURE-PARITY.md` updated.
- [ ] All gates, including `layoutPass` for the seven languages; fix overflow in CSS.
- [ ] One fresh reviewer for Part B: code, tooling and Review Focus 3 to 5 (it cannot judge the wording, and says so).
- [ ] Report: per language the entries, lint hits, back-translation findings and open questions. Demo link. PR when the
  user asks.

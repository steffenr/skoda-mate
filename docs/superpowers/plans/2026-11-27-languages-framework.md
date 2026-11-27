# Languages, Batch 1 (Framework and en/de) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the English and German interface to a system that can take 15 more languages, one file each.

**Architecture:** `static/i18n.js` loads one catalog on demand; `static/i18n/de.json` holds all German. Two extractors
write `static/i18n/keys.json`, and coverage checks every catalog against it. `languages.py` lists the languages;
`messages.py` holds the backend's user-facing templates.

**Tech Stack:** vanilla ES modules (no build step), FastAPI, pytest, Node 26 scripts in `scripts/dom-smoke`, puppeteer-core.

**Spec:** `docs/superpowers/specs/2026-11-26-places-insight-automation-design.md` §4.11, including "Added 2026-11-27".
Where "Added" differs from the older text (catalog format, plurals), "Added" wins.

## Global Constraints

- English and German wording on screen stays as it is. The only allowed differences are the ones task 1's comparison
  reports and the task that caused them lists and justifies (clashing keys, rebuilt sentences).
- `languages.py` lists only `en` and `de` in this batch. No other catalog, no CJK font change, no new picker design.
- No new dependency, no build step, no new request to Škoda. Setup and login stay English.
- DOM through `h()`, no inline script, CSP unchanged. Catalogs are JSON data, never code; values are text, never HTML.
- Demo and browser runs use a scratch database, never `data/`.
- Every behaviour change gets a test. Gates: `uv run --extra dev pytest -q`, `ruff check`, `mypy`, `unit.mjs`,
  `i18n_coverage.mjs`, `run.mjs`, `browser_e2e.mjs`, `a11y_axe.mjs`, `a11y_contrast.mjs`.
- Branch `feature/languages`. Commit per task; push and PR only when the user asks.
- Shell: commands die after 120 s. Run the demo server and the full browser job in detached Docker containers.

## Review Focus

1. A catalog fails to load (offline, stale cache): the page renders in English, without an error screen. (Task 2)
2. The language is switched twice quickly: the last choice wins, even if the first catalog arrives later. (Task 2)
3. A translation drops or renames a placeholder: coverage fails and names language, key and placeholder. (Task 9)
4. A parameter comes from outside (webhook name, Škoda's error detail) and contains `{name}` or HTML: it appears
   literally, with no second substitution. (Tasks 2 and 7)
5. The database holds a language code that is not offered (downgrade, hand edit): the dashboard shows English and
   Settings can still be saved. (Task 5)

---

### Task 1: Text snapshot of the current interface

**Files:** Create `scripts/dom-smoke/text_snapshot.mjs`.

**Interfaces:**
- Produces: `BASE=… node text_snapshot.mjs <out.json>` writes `{ "<lang> <route>": string[] }` for `en` and `de`:
  visible text lines plus every `title`, `aria-label` and `placeholder`, digits replaced by `0`, sorted and unique.
  `node text_snapshot.mjs --diff a.json b.json` prints added and removed lines per entry and exits 1 on any difference.

- [ ] **Step 1:** Write the script. Cover every `PAGES` route (ids `1` for detail pages), the Statistics, Activity and
  System tabs, the Settings automation and MQTT cards, and the "More" menu at 360 px.
- [ ] **Step 2:** Run it twice against one fresh demo server; `--diff` of the two runs must be empty. Remove sources of
  noise (relative times, live values) in the script until it is.
- [ ] **Step 3:** Save the baseline to the scratchpad. It must be taken before any file under `skoda_mate/` changes.
- [ ] **Step 4:** Commit `test: snapshot the interface text per language`.

### Task 2: The loader

**Files:** Modify `static/i18n.js`, `static/app.js`; Test `scripts/dom-smoke/unit.mjs`.

**Interfaces — Produces:**
- `type Catalog = Record<string, string | Record<string, string>>` (an object holds plural forms by CLDR category)
- `CATALOGS: Record<string, () => Promise<Catalog>>`, each `fetch`ing `/static/i18n/<code>.json`; a non-OK answer rejects
- `tn(one: string, other: string, n: number, vars?): string`, catalog key `other`; the form is chosen with
  `Intl.PluralRules(getLocale()).select(n)`, falling back to the entry's `other`, then to English. `{n}` is `vars.n`
  if given (a formatted number), else `n`.
- `async setLang(code: string, locale?: string): Promise<void>`; `getLang()`; `getLocale()` (`locale ?? code`)
- `t(key: string, vars?: Record<string, string|number>): string`
- `N_(key: string): string` (returns `key`); `hasKey(key: string): boolean`; `catalog(): Catalog`

`extendDE` stays until task 3 so the pages keep working.

- [ ] **Step 1:** Failing tests in `unit.mjs`, with test-only entries added to `CATALOGS`:
  - `t('{n} cars', {n: 2}) === '2 cars'` in English.
  - `t('Open##action') === 'Open'` in English; a catalog entry for the full key wins.
  - Missing key falls back to English with the suffix removed.
  - `t('Hi {name}', {name: '{x} <b>', x: 'no'}) === 'Hi {x} <b>'`; an unknown placeholder stays `{like this}`.
  - A catalog whose load rejects: `setLang` resolves, `t` returns English.
  - English `tn('{n} day', '{n} days', n)`: `1 day`, `0 days`, `2 days`.
  - With a test catalog for locale `uk` holding `one`, `few`, `many`, `other`: n = 1 and 21 → `one`; 2 and 22 → `few`;
    5 and 11 → `many`; 1.5 → `other`. A missing category falls back to `other`.
  - `setLang('slow')` then `setLang('fast')`, slow resolving last: the fast catalog is active.
- [ ] **Step 2:** `node unit.mjs`; expect these to fail.
- [ ] **Step 3:** Implement. One regex pass over the template for substitution. A sequence counter guards the race.
- [ ] **Step 4:** In `app.js`, `await setLang(...)` before anything is painted.
- [ ] **Step 5:** `node unit.mjs` and `i18n_coverage.mjs` pass. Commit `feat(i18n): load catalogs with placeholders and context`.

### Task 3: One German catalog

**Files:** Create `static/i18n/de.json`; delete `static/de_backend.js`; modify `static/i18n.js`, every file that calls
`extendDE`, `static/app.js` (remove `preloadPages` and the import), `pages/{control,prices,capabilities}.js`,
`scripts/dom-smoke/{i18n_coverage,german_leaks}.mjs`, `tests/test_web.py`.

**Interfaces — Produces:** `static/i18n/de.json` = `{ "English": "Deutsch", … }`, one entry per line, keys sorted.

- [ ] **Step 1:** Make `test_range_errors_have_german_entries` read `static/i18n/de.json`; run it; expect fail.
- [ ] **Step 2:** For each of the 28 clashing keys (29 registrations, one repeated), decide and record in a table in the
  commit message: **same meaning** → keep the wording the baseline shows; **different meaning** (`Range`, `Open`, `To`,
  `Charging`, `Driving`, `Enabled` and any other found by reading the call sites) → split into `'Key##context'` and
  change the call sites. To list them, load each `extendDE` block and print keys registered with two values.
- [ ] **Step 3:** Generate `de.json` from the registered entries, apply the decisions, remove every `extendDE` block.
  `enum:` entries stay for now. `CATALOGS` gets its `de` entry.
- [ ] **Step 4:** `i18n_coverage.mjs` reads `de.json` for its keys. Declare its `missing` map before the nav-label loop
  (today a missing label crashes the script). `german_leaks.mjs` uses `catalog()`. Check: remove one nav entry locally,
  see it reported, restore it.
- [ ] **Step 5:** pytest, `unit.mjs`, coverage pass. Snapshot diff: explain every line. Commit
  `refactor(i18n): move all German into one catalog`.

### Task 4: Formats and API values

**Files:** Modify `static/i18n.js`, `static/lib/format.js`, `static/i18n/de.json`, `pages/prices.js`, other callers of
`f.getLang()`; Test `unit.mjs`.

**Interfaces:**
- Consumes: `getLocale()`, `t`, `N_`.
- Produces: `ENUM_LABELS: Record<string, string>` in `static/i18n.js`, each value written `N_('…')` (with a context
  suffix where the German differs from the same plain word); `tEnum(v)` returns `t(ENUM_LABELS[v])`, else the
  humanised value. `f.setLocale({units, language, locale})`, `f.getLocale()`.

- [ ] **Step 1:** Failing tests: with a test catalog, `dayLabel(now)`, yesterday and `ago(10)` use its `Today`,
  `Yesterday`, `just now`; `tEnum('CONNECT_CABLE') === 'Connect cable'`; with German `'Kabel anschließen'`;
  `tEnum('NEW_VALUE') === 'New value'`; non-enum input is returned unchanged; every former `enum:` key is in `ENUM_LABELS`.
- [ ] **Step 2:** Run; expect fail.
- [ ] **Step 3:** Implement. All `Intl` and `toLocale*` calls take the BCP-47 locale. `prices.js` already asks for
  `f.getLocale` which does not exist, so it uses the browser's language today; add a test for it. Remove the callers'
  `t(tEnum(v))` double translation.
- [ ] **Step 4:** Tests, coverage, snapshot diff. Commit `refactor(i18n): translate formats and API values through t()`.

### Task 5: Languages from the backend

**Files:** Create `skoda_mate/languages.py`, `tests/test_languages.py`; modify `routers/settings.py`, `static/app.js`,
`pages/settings.js`.

**Interfaces — Produces:**
- `@dataclass(frozen=True) class Language: code: str; name: str; locale: str`;
  `LANGUAGES = (Language("en","English","en"), Language("de","Deutsch","de"))`; `BY_CODE: dict[str, Language]`
- `GET /api/settings` adds `languages: [{code,name,locale}]` and `locale: str`.

- [ ] **Step 1:** Failing tests: GET returns exactly those two entries and `locale`; PUT `{"language":"xx"}` → 400;
  with `xx` stored, GET returns `language: "en"`, `locale: "en"` and PUT `{"units":"mi"}` → 200; the keys of `CATALOGS`
  in `static/i18n.js` plus `en` equal `BY_CODE`.
- [ ] **Step 2:** Run; expect fail.
- [ ] **Step 3:** Implement. The picker renders `S.languages`, each option with its own `lang` attribute (so screen
  readers pronounce the native name; no flags); `app.js` passes the locale to `setLang` and
  `f.setLocale` and sets `document.documentElement.lang` to it.
- [ ] **Step 4:** Tests, snapshot diff. Commit `feat(i18n): list languages from the backend`.

### Task 6: HTTP errors as templates

**Files:** Create `skoda_mate/messages.py`, `tests/test_messages.py`; modify `web.py` (register the handler only),
`routers/*.py`, `presenters.py`, `places.py`, `merge.py`, `mqtt_config.py`, `webhooks.py`, `commands.py`, `costs.py`,
`activity.py`, `importer.py`, `quality.py`, `static/app.js`.

**Interfaces — Produces:**
- `class Msg(NamedTuple): template: str; params: dict` with `__str__` returning the formatted English.
- `class Template(str)`; calling it, `RADIUS(lo=20, hi=5000)`, returns a `Msg`. Every user-facing template is a module
  constant; `TEMPLATES: tuple[Template, ...]` lists them all.
- `of(value: Exception | str) -> Msg` (an exception's `args[0]` if it is a `Msg` or `Template`, else its text).
- `class UserError(HTTPException)`: `UserError(status, message)`; response body
  `{"detail": "<English>", "detail_i18n": {"message": "<template>", "params": {…}}}`.
- Frontend: the `Error` from `request()` has `message = t(i18n.message, i18n.params)` when `detail_i18n` is present.

Scope: every refusal a signed-in dashboard user can see. English-only exceptions, listed in `messages.py`'s docstring:
setup and login pages, and answers the dashboard never shows.

- [ ] **Step 1:** Failing tests: a static refusal (`"Place not found."`) keeps its `detail` and gains `detail_i18n`;
  a dynamic one (`poll_idle_s` out of range) has `params` `{"key": "poll_idle_s", "lo": 180, "hi": 21600}`;
  `str(of(ValueError(NAME(name="{x}"))))` keeps `{x}` literally; `TEMPLATES` contains every `Template` in the module;
  each template's placeholders equal the parameters used in its test call.
- [ ] **Step 2:** Run; expect fail.
- [ ] **Step 3:** Implement and migrate. The existing English `detail` strings must not change: the existing tests that
  assert them stay untouched. `t(e.message)` wrappers in the pages that become double translation are removed.
- [ ] **Step 4:** All gates for Python; add the German entries for newly translatable messages. Commit
  `feat(i18n): send backend refusals as templates`.

### Task 7: Messages inside normal responses

**Files:** Modify `messages.py`, `client.py`, `poller.py`, `cloud.py`, `ha_mqtt.py`, `routers/{mqtt,vehicles,setup}.py`,
`quality.py`, `static/i18n.js`, and the pages that show these fields; Test `tests/test_messages.py`,
`unit.mjs`.

**Interfaces:**
- Consumes: `Msg`, `Template`.
- Produces: a sibling `<field>_i18n` next to `error` (poller status, refresh and command results, MQTT status),
  `message` (MQTT test, quality repair). JS: `tx(obj, field = 'error'): string|null` in `static/i18n.js`.

- [ ] **Step 1:** Failing tests: a poll failing with an unmapped Škoda status and detail `"<i>{x}</i>"` returns the
  same English `error` as today and `error_i18n.params.detail == "<i>{x}</i>"`; a budget refusal carries `seconds`;
  a quality repair carries `n`; `tx` falls back to the plain string when there is no `_i18n`.
- [ ] **Step 2:** Run; expect fail.
- [ ] **Step 3:** Implement. MQTT topic payloads and webhook payloads stay exactly as they are. The command log and
  `webhook_deliveries.last_error` keep storing English; static ones are translated on display as today.
- [ ] **Step 4:** Tests, German entries, snapshot diff. Commit `feat(i18n): translate status and result messages`.

### Task 8: Whole sentences

**Files:** Modify the pages, `app.js`, `lib/*.js`, `i18n/de.json`.

Rule: if the order or form of words depends on the language, it is one key with named placeholders. Independent items
joined by a separator (`' · '`, a label followed by `: ` and a value) may stay. Every count in a sentence uses `tn`
(today the code picks with `n === 1`, in about seven places in the dashboard; search for more). Do not insert one
translated word into another sentence, and do not change a translation's case in code (`.toLowerCase()`).

- [ ] **Step 1:** Add to `i18n_coverage.mjs` a check that fails for any `t`/`N_` key that starts with a lowercase letter
  and is not in `STANDALONE` (a list in the script of labels that stand alone, each with a short reason). Run it; the
  failures plus a search for template strings holding two or more `t()` calls form the work list.
- [ ] **Step 2:** Failing unit test for a sentence with a link or bold part: export
  `tParts(key, nodes: Record<string, Node|string>): Array<Node|string>` from `static/i18n.js`, which splits a
  translated sentence at its placeholders, so a node can move within the sentence.
- [ ] **Step 3:** Rebuild the sentences, area by area (shell, overview/car, trips/charges, battery/stats, events/system,
  settings/control/places/prices/import). After each area: coverage and snapshot diff, then commit.
- [ ] **Step 4:** The check from step 1 passes. Any wording difference left in the diff is listed in the commit message.

### Task 9: Extract the keys and gate every catalog

**Files:** Create `scripts/dom-smoke/i18n_extract.mjs`, `scripts/i18n_backend.py`, `static/i18n/keys.json`,
`tests/test_i18n_keys.py`; modify `i18n_coverage.mjs`, `.github/workflows/ci.yml`, files that hold tables of strings.

**Interfaces — Produces:**
- `keys.json` = `{"backend": {key: entry}, "frontend": {key: entry}}`, sorted; each script rewrites only its own
  section. `entry` = `{"files": [where it is used], "one"?: "<English singular>"}`: translators see where a text
  appears, and `one` marks a plural key. Both accept `--check` (exit 1 and name the difference if stale).
- Frontend sources: literal `t`, `N_`, `tParts` first arguments, both `tn` texts and `PAGES` labels.
- Backend sources: `messages.TEMPLATES`, the user-facing strings in `features.py`, and the strings other backend
  tables send to be passed through `t()` (webhook event groups, quality texts).

- [ ] **Step 1:** Failing tests: pytest asserts `i18n_backend.py --check` passes and that every `TEMPLATES` entry and
  every `features.py` title and reason is in `keys.json`. `unit.mjs` asserts `compare(keys, catalog)` reports a missing
  key, an extra key and a placeholder mismatch `{lo}`/`{low}`, each with the key; and, for a plural key, any
  category of `new Intl.PluralRules(locale).resolvedOptions().pluralCategories` that the entry lacks.
- [ ] **Step 2:** Run; expect fail.
- [ ] **Step 3:** Implement; coverage loops over `CATALOGS` and reports per language.
- [ ] **Step 4:** Clear the "extra in de" list: for each, mark the source with `N_('…')`, add the backend source to
  `i18n_backend.py`, or, after a search shows nothing uses it, delete it. About 390 entries are not found by a literal
  `t()` scan today. Never delete one on the scan alone.
- [ ] **Step 5:** CI frontend job runs `i18n_extract.mjs --check` and coverage; the pytest above covers the backend.
- [ ] **Step 6:** Coverage reports `de: 0 missing, 0 extra, 0 placeholder mismatches`. Commit
  `test(i18n): gate catalogs against the extracted keys`.

### Task 10: Docs and full verification

**Files:** `AGENTS.md` (Translations rule, CI list, mypy file count), `docs/DASHBOARD.md`, `DESIGN.md`,
`docs/FEATURE-PARITY.md`, new `docs/TRANSLATIONS.md`.

- [ ] **Step 1:** `docs/TRANSLATIONS.md`: add a language (catalog file, `CATALOGS`, `languages.py`), run extractor and
  coverage, context suffixes, placeholders, plural forms, and a review-status table (de: reference).
- [ ] **Step 2:** Add a pseudo-language pass to `browser_e2e.mjs`, without any app code for it: intercept the request
  for `de.json` and answer with a catalog built from `keys.json` (accented letters, `⟦…⟧` around each text, about 40 %
  longer, placeholders untouched). At 360 px, on every route: report visible text outside the brackets (missed or
  pieced together; car data, names and numbers are allowed) and fail on horizontal overflow. Fix what it finds.
- [ ] **Step 3:** Run every gate, the full browser job in Docker, `german_leaks.mjs` and the final snapshot diff.
  `browser_e2e.mjs` gains one check: switching to German and back updates `<html lang>` without a reload.
- [ ] **Step 4:** One fresh reviewer checks the whole branch against the spec and Review Focus. Fix findings, rerun gates.
- [ ] **Step 5:** Commit, then report the results and give the user a demo link. Push and PR wait for the user.

---

## After batch 1 (separate plan)

**Decided 2026-11-27, after trials on 50 German texts:** translation subagents write the catalogs, each getting the
English, a usage note, the code line that shows the text and a glossary with the form of address; DeepL is only a
second opinion on doubtful or short texts. DeepL Free ignored the context setting and the formality setting, and
rejected document uploads (403, cause unknown). This replaces the "DeepL draft" step below where they differ.

**DeepL (does not affect batch 1).** Use DeepL's hosted connector, `https://mcp.deepl.com/v1/mcp`, which signs in with
OAuth. No DeepL API key and no local `deepl-mcp-server`: nothing secret goes into the repository, a project
`.mcp.json`, a script, a prompt or CI. Translating stays a manual step; the app and CI never call DeepL.
- Send only interface strings from `keys.json` and their glossary or context notes: never anything from `data/`, `.env`,
  logs or screenshots. DeepL's free terms exclude personal and confidential data and allow training on submitted text.
- DeepL Free has no glossary, context or formality over this connector; seat-based plans have them.
- Pilot first: translate a sample of about 100 keys to German, including short ambiguous labels, placeholders and
  plurals, and compare with the reference `de.json`. Ask for the supported target languages and check Catalan.
- Then: DeepL draft → review against file locations and glossary → coverage (placeholders, plural categories) → review
  by someone who speaks the language. The connector's documented parameters show no way to protect `{placeholders}`, so
  the coverage check decides. A language DeepL cannot do is translated by a subagent and recorded as such in
  `docs/TRANSLATIONS.md`.

Four translator subagents (da/nl/sv/nb/fi · fr/es/it/ca · hu/tr/uk · ja/ko/zh_Hans), each writing only its
`static/i18n/<code>.json` files against `keys.json`, with the same short glossary (car and charging terms, formal or
informal address per language, product names left untranslated). The main session registers the languages, turns the picker into a
select, adds the CJK font stack and the 360 px long-string check, and runs the gates. A language is registered only when
coverage passes for it.

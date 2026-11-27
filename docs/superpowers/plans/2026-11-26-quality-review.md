# Mark a Data-Quality Check as Reviewed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One action per data-quality check, "Mark as reviewed", that stops the check counting until a newer finding of that kind appears, and can be undone.

**Architecture:** A `quality_reviews` table stores one review per car and check. `quality.checks()` filters each check's count and samples to findings newer than the review and also reports the unfiltered total; a new `quality.review()` sets or clears a review and logs an event, behind a new POST route. The System page card (Task 9 of the activity plan) gets the button, a reviewed state with Undo, and adjusted counts.

**Tech Stack:** Python 3, FastAPI, SQLite, pytest; vanilla ES modules (`h()`, `ui.js` helpers), Node 26 browser checks.

**Spec:** `docs/superpowers/specs/2026-11-26-quality-review-design.md` (builds on Tasks 7–9 of `docs/superpowers/plans/2026-11-27-activity-and-trust.md`; card code in `skoda_mate/static/pages/system.js`).

## Global Constraints

- A reviewed check counts and samples only findings whose own time is **strictly after** `reviewed_at`; `total` always counts all findings in the window.
- Finding times: open/estimated/inferred/approx trips and charges and duplicate groups by `started_at`; reading gaps and odometer jumps by the later reading's `recorded_at`; API errors by `api_calls.at` (epoch seconds — compare as a number); stuck operations by `updated_at`. `missing_sections` has no time: the review stores the names missing at review time (JSON list in `detail`); the check then counts only names missing now that are not in that list.
- Stored timestamps are UTC ISO strings with `+00:00` (as `ctx.now_iso()` writes them); compare ISO strings only in that form.
- Every action writes one `events` row: kind `quality_review`, detail `<check>:on` or `<check>:off`, `at` = now.
- Unknown check → 400 with the exact text `"Unknown check."` (German in `static/de_backend.js`: `'Unknown check.': 'Unbekannte Prüfung.'`).
- Frontend: every visible string is `t('English')` with a German entry via `extendDE`; `t()` takes one argument (compose counts and dates with `f.*`); DOM only via `h()`; no new hosts.
- Exact copy: `Mark as reviewed`, `Reviewed`, `Undo`, `new since`, `Everything else looks consistent or was reviewed.`
- Gates before every commit: `uv run --extra dev pytest -q`, `uv run --extra dev ruff check`, `uv run --extra dev mypy`; frontend tasks also `browser_e2e.mjs`, `run.mjs`, `i18n_coverage.mjs` (0 missing).

## Review Focus

- A finding exactly at `reviewed_at` stays reviewed; one a second later counts (strictly after).
- A review on car A never changes car B's checks.
- Reviewing again moves `reviewed_at` forward (upsert), it never creates a second row.
- `missing_sections`: reviewed with `position` missing; then `charging` also goes missing → count 1, sample `charging` only; `position` reappearing and vanishing again does not count.
- An undo restores the full count and samples immediately (no stale state on the card after the POST).

---

### Task 1: Reviews in the backend

**Files:**
- Modify: `skoda_mate/schema.py` (add the table to `SCHEMA`)
- Modify: `skoda_mate/quality.py`
- Modify: `skoda_mate/routers/quality.py`
- Modify: `skoda_mate/static/de_backend.js` (`'Unknown check.'`)
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: `quality.CHECKS`, `quality.checks(conn, vid, now_iso)` items `{id, severity, count, summary, samples, fix}`.
- Produces: items gain `reviewed_at: str | None` and `total: int`; `count`/`samples`/`summary` describe only unreviewed findings. `quality.review(conn, vid: int, check: str, reviewed: bool, now_iso: str) -> dict` returning `{"check": check, "reviewed_at": now_iso | None}`; raises `ValueError("Unknown check.")` for an id not in `CHECKS`. Route `POST /api/vehicles/{vid}/quality/review`, body `{"check": str, "reviewed": bool}`, returns `review()`'s dict; 400 on ValueError, 404 for another car (same ownership helper as the neighbouring routes).

- [ ] **Step 1: Add the table** to `SCHEMA` in `schema.py`:
  `CREATE TABLE IF NOT EXISTS quality_reviews (vehicle_id INTEGER NOT NULL, check_id TEXT NOT NULL, reviewed_at TEXT NOT NULL, detail TEXT, PRIMARY KEY (vehicle_id, check_id));`

- [ ] **Step 2: Write the failing tests** in `tests/test_quality.py` (reuse its helpers `_setup`, `_trip`, `_charge`, `_snap`, `_other`, `_by_id`, `NOW`, `_ts`):
  - `test_review_hides_a_check_until_a_newer_finding`: two open trips (30 h and 40 h old); `review(..., "open_trips", True, NOW_ISO)` → `checks` at NOW gives `count == 0`, `total == 2`, `samples == []`, `reviewed_at == NOW_ISO`; then insert an open trip started at `NOW + 1 s` and check at `NOW + 25 h` → `count == 1`, `total == 3`, one sample pointing at the new trip.
  - `test_a_finding_exactly_at_the_review_time_stays_reviewed`: odometer decrease whose later reading is at exactly `NOW_ISO`; review at `NOW_ISO` → `count == 0`.
  - `test_review_is_per_vehicle`: review on car A leaves car B's `open_trips` count and `reviewed_at is None`.
  - `test_review_again_moves_the_time_forward_and_undo_restores`: review at NOW, review again at NOW + 1 h → one row in `quality_reviews`, `reviewed_at` = NOW + 1 h; `review(..., False, ...)` → row gone, `count == total`, `reviewed_at is None`.
  - `test_api_errors_compare_epoch_seconds`: errors at `NOW − 2 h` and `NOW − 10 min` (epoch); review at `NOW − 1 h` → `count == 1`.
  - `test_missing_sections_review_remembers_the_names`: state has info, charging, climate (position missing); review → `count == 0`; delete `charging` from `vehicle_state` → `count == 1`, `samples == [{"label": "Section charging missing", "href": None}]`, `total == 2`.
  - `test_each_review_logs_one_event`: review then undo → events `[(NOW_ISO, "quality_review", "open_trips:on"), (later, "quality_review", "open_trips:off")]`.
  - `test_review_unknown_check_is_400` (unit: `ValueError` match `"Unknown check."`; route: 400 and `detail == "Unknown check."`), `test_review_route_other_vehicle_404`, `test_review_route_requires_a_session` (401), `test_review_route_sets_and_clears` (POST true → GET shows `reviewed_at`; POST false → `reviewed_at is None`).
  - Extend `test_empty_database_returns_every_check_in_order_with_zero_counts` to assert every item has `total == 0` and `reviewed_at is None`.

- [ ] **Step 3: Run them** — `uv run --extra dev pytest tests/test_quality.py -q`; expected: the new tests fail (`review` missing, no `total`/`reviewed_at`).

- [ ] **Step 4: Implement.** Load the car's reviews once at the top of `checks()`. Thread an optional "after" bound into each check's existing SQL (`AND <time column> > ?`) for both count and samples; compute `total` with the existing unfiltered query. Keep one definition per query (the module already shares `_OPEN_ROWS` and `_DUPLICATE_GROUPS` between checks and fixes — do not fork them). `review()` upserts (`INSERT … ON CONFLICT(vehicle_id, check_id) DO UPDATE`) with `detail` = JSON list of currently missing section names for `missing_sections` (else NULL), or deletes on undo, then writes the event and commits once. Add the route with a pydantic body like `FixBody`.

- [ ] **Step 5: Run** the quality tests, then the full gates; expected all green.

- [ ] **Step 6: Commit** — `git commit -m "feat(quality): mark a check as reviewed until a newer finding appears"`

---

### Task 2: Review and undo on the card

**Files:**
- Modify: `skoda_mate/static/pages/system.js` (`reviewModal`, `qualityCard`, German entries)
- Modify: `skoda_mate/static/pages-b.css` (only if the reviewed state needs a `quality-` rule)
- Test: `scripts/dom-smoke/browser_e2e.mjs` (extend the Task 9 block "2b. data-quality card on System")

**Interfaces:**
- Consumes: Task 1's item fields `reviewed_at`, `total`, and `POST …/quality/review` `{check, reviewed}`.

- [ ] **Step 1: Write the failing browser checks** in the existing quality fixture block (extend its GET fixture with `reviewed_at`/`total`, and intercept POST `…/quality/review`, recording the body):
  - `Review modal offers Mark as reviewed and posts {check, reviewed:true}`: open Review on a finding, click `Mark as reviewed` → POST body equals `{"check": "<id>", "reviewed": true}`, toast shown, modal closed, card refreshed.
  - `A reviewed check with no new findings sits under Show all checks with Reviewed <date> and Undo`: fixture item `count: 0, total: 2, reviewed_at: <iso>` → not in the visible rows, present inside `.quality-all` with text `Reviewed` and an `Undo` button; header chips do not count it; quiet line is `Everything else looks consistent or was reviewed.`
  - `Undo posts {check, reviewed:false} and refreshes`.
  - `A reviewed check with new findings shows them marked new since <date>`: fixture `count: 1, total: 3, reviewed_at: <iso>` → visible row contains `new since`.
  - Keep the 360 px no-horizontal-scroll assertion for the card with a reviewed row present.

- [ ] **Step 2: Run the frontend checks** (background wrapper) — expected: the new checks FAIL, all others ok.

- [ ] **Step 3: Implement.** In `reviewModal`, add `asyncButton(t('Mark as reviewed'), …)` next to Fix (shown for any check with `count > 0`); on success toast `t('Reviewed')`, close, refresh. In `qualityCard`, treat a check with `reviewed_at && count === 0` as reviewed: list it inside "Show all checks" with `${t('Reviewed')} ${f.dayLabel(reviewed_at)}` and `button(t('Undo'))` (POST `reviewed:false`, then refresh); a check with `reviewed_at && count > 0` shows `${t('new since')} ${f.dayLabel(reviewed_at)}` in its row. Show the `<details>` whenever there are clear or reviewed checks. Quiet line: `Everything else looks consistent or was reviewed.` when any check is reviewed, else the existing lines. German entries for all new strings.

- [ ] **Step 4: Run** the three frontend checks and the backend gates — expected all green, `i18n_coverage` 0 missing.

- [ ] **Step 5: Commit** — `git commit -m "feat(quality): review and undo data-quality checks on the System page"`

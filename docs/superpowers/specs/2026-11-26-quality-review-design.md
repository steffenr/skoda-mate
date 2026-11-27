# Data quality: mark a check as reviewed

Short design (small change). Extends the data-quality card from phase 2 (Tasks 7–9 of
`docs/superpowers/plans/2026-11-27-activity-and-trust.md`, spec §4.7).

## Why

The card should show what still needs attention. Most findings cannot be fixed (an odometer jump, a reading gap, an
inferred charge) and only age out of the 30-day window, so a finding the owner has already looked at stays on the card,
often as "important", for up to a month. The owner needs a way to say "seen it, fine" without hiding anything new.

## Goals, non-goals, anti-goals

- Goal: one action per check, "Mark as reviewed", that stops the check counting until a newer finding of that kind
  appears; then it counts (and shows) only the new ones. Reversible.
- Non-goal: marking individual findings (decided: per check). Non-goal: editing or deleting data.
- Anti-goal: a review that hides a problem which happened after it. Anti-goal: the header showing "all clear" while the
  owner cannot tell that something was reviewed away.

## Approaches

1. **Per check, by time (chosen).** Store when the check was reviewed; count only findings newer than that. Covers all
   checks with one rule; cannot keep one of five findings open.
2. Per finding. Every finding needs a stable id and the card a full list instead of five examples. Rejected by the owner:
   more than the card needs.
3. Per check, by count (hide while the count does not grow). Rejected: when an old finding ages out and a new one arrives,
   the count stays the same and the new finding would stay hidden.

## Design

- **Storage:** new table `quality_reviews(vehicle_id, check_id, reviewed_at, detail, PRIMARY KEY(vehicle_id, check_id))`,
  created in `schema.py` like the other tables. `detail` is only used by `missing_sections` (below).
- **Rule:** a reviewed check counts and samples only findings whose own time is after `reviewed_at`:
  trips/charges by `started_at`, reading gaps and odometer jumps by the later reading's time, duplicate groups by their
  `started_at`, API errors by `at`, stuck operations by `updated_at`. `missing_sections` has no time: the review stores
  the missing section names in `detail`, and the check counts only sections missing now that were not in that list.
- **Applies to every check with findings**, including the three with a Fix (the owner may decide an open trip is fine).
- **API:** `GET /quality` items gain `reviewed_at` (ISO or null) and `total` (all findings in the window, ignoring the
  review); `count` and `samples` become "not yet reviewed". `POST /api/vehicles/{vid}/quality/review` with
  `{"check": <id>, "reviewed": true|false}` sets the review to now, or clears it; an unknown check is 400
  `"Unknown check."`. Each review or undo writes one `events` row (`quality_review`, `<check>:on|off`), like fixes.
- **Card:** the Review modal gets "Mark as reviewed" next to Fix. A reviewed check with no new findings moves under
  "Show all checks" with "Reviewed <date>" and an "Undo" button; the header chips count only unreviewed findings, and
  the quiet line reads "Everything else looks consistent or was reviewed." when anything is reviewed. A reviewed check
  that has new findings shows them as usual, marked "new since <date>".
- **German** for every new string; `"Unknown check."` in `de_backend.js`.

## Left to the builder

Exact copy beyond the strings above, button placement in the modal, the CSS, and the test layout (unit tests in
`tests/test_quality.py`, route tests, and the e2e fixture flow from Task 9 extended with review and undo).

## Known limit

A finding dated before the review that reaches the database later (for example an old CSV import that creates
duplicate trips) stays hidden until the review is undone. Rare; accepted for a time-based rule.

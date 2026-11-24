# Changelog

All releases are reviewed, independently reproduced builds of Taksh Pathak's portfolio
implementation. Per-release evidence lives in [`docs/history/`](docs/history) and, for the
current release, in [`docs/v06/`](docs/v06).

## v0.6.0

Release gates from the independent v0.5.1 review, each reproduced before it was fixed.

### Fixed
- **First-message constraints were less protected than later edits.** A schema-valid planner
  response that omitted `min_seats` for "seven-seat SUV … under $950 monthly" saved no seat
  requirement and showed five-seat vehicles. Discovery and edits now share one server-side
  reconciliation path (`app/rental_constraints.py`). Explicit customer evidence overrides
  omitted or contradicting planner fields, ungrounded planner values are never saved, and every
  override is returned and shown to the customer.
- **"Under $875" included $875.** Strict bounds are canonicalized to the exact inclusive
  integer-cent ceiling (`< X` → `<= X − 1¢`). "At most" stays inclusive, "can't go over" and
  "no more than" are ceilings, and "more than six seats" means a minimum of seven. Saved v0.5
  searches keep their meaning. Two frozen expectations that had recorded the inclusive behavior
  were corrected; the vehicle IDs are unchanged.
- **Browser suites collided on port 3000.** `npm start` forks `next-server`, which survived the
  runner. A shared harness now runs each server in its own process group, signals the group,
  and waits for port release. Both suites pass back to back, twice in a row.
- **Compose could not start on any Docker host.** The `modelcache` volume was mounted over a
  path missing from the image, so Docker created it root-owned and the non-root `index` service
  failed with `PermissionError`. Restart persistence is now verified end to end.
- **Search form showed a stale budget** after a chat edit. It now remounts when the saved query
  changes, and the flagship browser test asserts this. Zero-count quote lines are hidden.
- Evaluation metric: a turn that clarified and saved nothing was counted as a "silent
  relaxation". It now counts as a task failure only.
- Migration scripts now call the active interpreter (`sys.executable`) rather than a bare
  `python`, and can use system PostgreSQL binaries.

### Added
- Anthropic Messages API adapter beside OpenAI Responses, sharing one instrumented contract
  (`AI_MODE=anthropic`).
- Frozen `release_v06` live-vs-deterministic scenario set (11 scenarios, 28 steps), committed
  before any run. Live result (`gpt-5.4-mini-2026-03-17`, single pass): 8/11 scenarios vs. 5/11
  offline, 0 unsafe outcomes.
- Flagship Chromium demo (`scripts/flagship_browser.py`) and README screenshots.
- One-command release runner (`scripts/verify_release.py`) with per-gate logs and a summary.
- Regression test: `alembic upgrade head` followed by `alembic check` must be clean.
- Rental desk UI rebuilt from typed components: saved-search chips (as enforced in SQL), a
  model-mode badge, server-decision notes, and status explanations for each record.

### Changed
- Backend formatted and linted with ruff (rules E, F, W, I, B, UP, SIM). Exception chaining
  (`raise … from`) and `zip(strict=True)` were added where lengths must match.
- Historical evidence moved to `docs/history/`.

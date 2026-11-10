# Movie Showtimes — Home Assistant custom integration

Shows the showtimes of the user's favourite French cinemas in Home Assistant. Domain: `movie_showtimes`. Distributed through HACS.

The repository was generated from the `ha-dev-environment` Copier template (`.copier-answers.yml`). Files managed by the template (`scripts/`, `.github/workflows/`, `.pre-commit-config.yaml`, most of `pyproject.toml`) are changed upstream then pulled with `copier update` — do not edit them here unless the user asks.

## Data source: `allocine-seances` (one source, France only)

- PyPI `allocine-seances` (import: `from allocineAPI.allocineAPI import allocineAPI`), MIT, by lefevre-dev. Scrapes allocine.fr; it is not an official API and may break when the site changes.
- API: `get_top_villes()`, `get_departements()`, `get_circuit()` return location ids (`ville-…`, `departement-…`, `circuit-…`); `get_cinema(id_location)` returns `{id, name, address}`; `get_showtime(id_cinema, "YYYY-MM-DD")` returns `[{title, showtimes: [{startsAt, diffusionVersion}]}]`, where `diffusionVersion` is `ORIGINAL`, `DUBBED` or `LOCAL` (French-language film, counted as VF); the README's `{duration, VF, VO}` shape is outdated. `get_movies(id_cinema, date_str)` exists too.
- Unknown cinema id → bare `Exception("Error 404")`; a known cinema with nothing that day → `[]`. An item whose `movie` is null crashes the call (`TypeError`).
- **It is synchronous** (`requests.get`, **no timeout**) and depends on `requests` without declaring it (Home Assistant ships `requests`). Consequences, which are not negotiable:
  - Never call it on the event loop: always in an executor job.
  - Enforce a timeout in our wrapper (it has none of its own).
  - Pin the exact version in `manifest.json` `requirements`.
- AlloCiné is the only source in v1, implemented as one provider of the client's source abstraction (see docs/architecture.md, D13). The coordinator, entities, config flow and Store depend only on that abstraction; adding a source means adding a provider.
- No authentication: `ConfigEntryAuthFailed` and reauth flows do not apply.
- Showtimes come back as naive ISO datetimes in French local time: convert them to aware datetimes in `Europe/Paris` inside the client. Entities display them as `HH:MM` in Home Assistant's configured time zone.
- It is scraping: expect the HTML to change. A parsing failure must surface as a clear client exception (and `UpdateFailed`), never as a crash or as silently empty data.
- Be gentle with allocine.fr: one cinema per config entry, a refresh interval of hours rather than minutes, no request per entity.

## Project-specific review points

On top of the agents' generic checklists:

- Every `allocineAPI` call goes through the client, in an executor, under a timeout.
- Datetimes are aware (`Europe/Paris`); "today" is computed in Home Assistant's time zone, not UTC.
- VF / VO showtimes are both kept and distinguishable.
- An empty showtime list (cinema closed that day) is valid data, not an error.

## Architecture

- `custom_components/movie_showtimes/client/` — the bundled client: the source abstraction (`provider.py`, `registry.py`), source-neutral models and exceptions, and one module per source in `providers/` (`providers/allocine.py`, a wrapper around `allocineAPI`). **It must not import `homeassistant`**: its tests run without Home Assistant. A provider converts its source's raw data into our models and its errors into our exceptions; nothing outside its provider module touches `allocineAPI`.
- `custom_components/movie_showtimes/*.py` — the Home Assistant side: config flow (choose a location, then a cinema), a `DataUpdateCoordinator` per config entry, entities, diagnostics, translations (`strings.json` + `translations/en.json`, `fr.json`).
- Design notes and decisions live in `docs/` (start with `docs/architecture.md`).

## Commands

Always `uv run --no-sync …` (a sync would uninstall the `default_config` packages).

- Lint, like CI: `scripts/lint` (scopes: `client`, `integration`, `tests`, `repo`, `src`, `all`). The `repo` scope rewrites json/yaml/md with Prettier.
- Tests with coverage gates, like CI: `scripts/test` (scopes: `client`, `integration`). **Each scope must reach 95 % on its own**: client code must be covered by `tests/movie_showtimes/client/`, not by the Home Assistant tests.
- One test, no gate: `uv run --no-sync pytest tests/path/test_x.py -q`.
- Run Home Assistant locally against `./config`: `scripts/develop`.

## Conventions

- Python 3.14, ruff `select = ["ALL"]`, pylint, pyright, docstring-linter (Google style, every argument documented, no `Returns:` for `None`). Code, docstrings and commits in English.
- Follow the Home Assistant integration quality scale: config flow with unique ids, `ConfigEntryNotReady` / `UpdateFailed` on errors, `runtime_data` on the config entry, `has_entity_name`, translations for every user-facing string, no blocking I/O in the event loop.
- Tests never hit the network: mock `allocineAPI` (client tests) or our client (integration tests). Use recorded fixtures under `tests/**/fixtures/`.
- Conventional commits (checked by commitlint). Work on branches off `develop`; PRs target `develop`.

## Agents (`.claude/agents/`)

Generic Home Assistant integration agents — nothing in them is specific to this project; they read this file for that. They are meant to move to the `ha-dev-environment` template later, so keep project knowledge here, not in them.

The usual pipeline for a feature: **ha-architect** (design, writes in `docs/`) → **ha-developer** (implements) → **ha-test-writer** (tests, coverage) → **ha-reviewer** (read-only review). The main session orchestrates and gets each agent's report. Quick factual lookups (where is X, what do the HA docs say about Y) go to **ha-lookup** (haiku, read-only); subagents cannot call each other, so the main session does that routing.

Before a commit or PR, **ha-ci-quality-guardian** runs the CI checks locally and fixes the mechanical failures. **ha-release-manager** prepares a release (version, notes, develop → main PR, GitHub release) and, when explicitly asked, creates the commits (on a topic branch, never on `develop` or `main`); it never pushes, tags, merges or publishes anything.

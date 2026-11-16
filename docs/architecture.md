# Movie Showtimes — architecture (v1)

Status: implemented (v1 + film enrichment D24–D31; client 403 tests, integration 212, 99 % each). Pinned Home Assistant: `2026.10.1`
(`pyproject.toml`). Data source: `allocine-seances==0.0.14`.

**Film enrichment, VO / VOST and accessibility (D2 revised, D24–D31)** is designed in
[`docs/design/film-enrichment.md`](design/film-enrichment.md). The sections it changes (§1, §2, §3.2, §3.3,
§3.5, §5.3, §7, §8, §10, §11, §12, §13.3, Appendix A) carry a short note that points there instead of repeating it.

**Lovelace card (D32–D41)**, served and registered by the integration, is designed in
[`docs/design/lovelace-card.md`](design/lovelace-card.md) (a near-verbatim copy of the reference card
`bastgau/ha-betaseries` `card/upcoming-media-card.js` plus an adapter, in three phase-1 steps). **Phase 1
supersedes D35, D39-D41: the card was restarted from the reference copy; D32 (delivery) and D33 (binding by
device) stay.** D34, D36-D38 describe the earlier rewrite and are to be re-read against the short design.
It touches §1, §3 (module tree), §10 and §11 here.

## 1. Goal and scope

Show, in Home Assistant, what is on at one AlloCiné cinema over the next seven days.

### In scope (v1)

- A config flow where the user types an AlloCiné cinema id (e.g. `W0124`) or pastes the cinema's
  allocine.fr URL, plus a display name. The id is checked against allocine.fr before the entry is created.
- One config entry per cinema, the cinema id is the unique id. One entry = one device (a service device).
- Seven sensors per device, one per day from today to today + 6. State = number of films that still have a
  showtime to come that day. Attribute = those films, each with its title and its remaining showtimes
  split by VF / VO / VOST (D2 revised), as `HH:MM` in Home Assistant's time zone.
- (D24) Each film also carries what the showtimes document already holds about it and its showtimes (runtime,
  genres, certificate, ratings, poster, synopsis, cast, formats, booking links, accessibility: PMR, SME subtitles,
  audio description …), **with no extra request**.
  Design: `docs/design/film-enrichment.md`.
- "Today" is today in Home Assistant's time zone. The sensors move to the next day at local midnight, and
  showtimes drop out 15 min after they start, all without waiting for a refresh (§4.4).
- A refresh twice a day (every 12 h).
- (D13) The integration works against a source-neutral provider abstraction. AlloCiné is its only
  provider in v1 (§13).
- (D12) The last good data survives restarts. A restart with fresh data makes no request, and a restart
  while allocine.fr is down keeps showing the last good data (§12).
- Diagnostics, English and French translations, icon translations.

### Out of scope (v1)

| Left out                                                         | Why                                                                                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Browsing or searching cinemas (by ville / département / circuit) | User decision. `get_cinema()` and the location calls stay unused. The client can add them later without touching the entities.                                                                                                                                                                                                     |
| Filters (VF / VO only, favourite films)                          | User decision. Templates can do it from the attributes.                                                                                                                                                                                                                                                                            |
| Calling `get_movies` (film metadata)                             | Not needed: the film data is read from the document our pagination already receives, at no extra request (D24, D25). Calling `get_movies` as well would double the load (≈ +16 requests a day), and it is fragile: `UnboundLocalError` when `releases` is empty, `KeyError` when `poster` or `flags` is missing, a bare `except:`. |
| `timeBeforeStart`, `nextDate`, `editorialReviews`                | `timeBeforeStart` is unreliable; `nextDate`'s role is unverified; editorial reviews dropped by the user (design doc §1.3).                                                                                                                                                                                                         |
| Calendar entity                                                  | User decision. (The Lovelace card, first left out too, is now in scope: D32–D41, `docs/design/lovelace-card.md`.)                                                                                                                                                                                                                  |
| Options flow, reconfigure flow                                   | Nothing to configure after setup. The name can be changed in the UI (entry title / device name). To change the cinema, the user adds a new entry.                                                                                                                                                                                  |
| Reauthentication                                                 | The source has no authentication. `ConfigEntryAuthFailed` is never raised.                                                                                                                                                                                                                                                         |
| Repair issues (e.g. a cinema removed from AlloCiné)              | Rare. v1 shows the failure as unavailable entities plus a logged, translated `UpdateFailed`. Could be added later.                                                                                                                                                                                                                 |
| Discovery, dynamic devices, stale devices                        | Not applicable: one fixed device per entry, removed with the entry.                                                                                                                                                                                                                                                                |
| Platinum `async-dependency` / `inject-websession`                | The library is synchronous `requests`. The client runs it in an executor (see §3.4).                                                                                                                                                                                                                                               |

## 2. The data source, as observed (not as documented)

From reading `src/allocineAPI/allocineAPI.py` at 0.0.14 (GitHub `master`, `pyproject` version 0.0.14)
and the live endpoint.

- `allocineAPI` has no `__init__` and no session. Every HTTP call is a bare `requests.get(path, params=…)`
  in `_get_request` / `_get_json_request`, **with no timeout**. A non-200 status raises a bare
  `Exception("Error <status>")`. Invalid JSON raises `ValueError` (re-raised).
- `get_showtime(id_cinema, date_str)` pages through
  `https://www.allocine.fr/_/showtimes/theater-<id>/d-<YYYY-MM-DD>/p-<n>` (JSON, 15 films per page).
  It returns:

  ```python
  [{"title": str, "showtimes": [{"startsAt": "2026-11-11T15:00:00", "diffusionVersion": "DUBBED"}, ...]}, ...]
  ```

  The showtimes are deduplicated by `internalId` across the JSON buckets (`original`, `original_st`,
  `multiple`, …). The version is only in `diffusionVersion`. Values seen: `ORIGINAL`, `DUBBED`, `LOCAL`.
  The labels depend on the cinema (three real captures, design doc §0): French films are `LOCAL` at W7520,
  `DUBBED` at C0159, and `ORIGINAL` in `original_st` for _La Gradiva_ at W0124 (D2 revised).

  **(D25) The provider no longer calls `get_showtime`.** It pages through the same URLs itself
  (`URLs.showtime_url` + our `_get_json_request` override), with the same request count, and parses the full
  documents (design doc §2, §4). The library's loop also sets `page` from the response, so a server repeating
  page 1 would make it loop for ever; ours iterates a bounded range.

- It reads `element["movie"]["title"]` **without a `None` check** (`get_movies` has one). A result
  with `"movie": null` (a non-film event) makes the whole call fail with a `TypeError`.
- Responses seen on the live endpoint:
  - Unknown cinema id (`ZZ9999`): **HTTP 404**, so the library raises `Exception("Error 404")`.
  - Known cinema, a date with nothing on (`W0124`, `2027-03-01`): **HTTP 200**,
    `{"error": true, "message": "no.showtime.error", "messageParam": {"day": …, "page": …}, "pagination": {"totalPages": 0, …}, "results": []}`.
    The library returns `[]` for it.
  - Known cinema with showtimes: HTTP 200, `"error": false`, `results` filled.
  - **(D17)** With the library's default `User-Agent: python-requests/x.y`, allocine.fr (Cloudflare) answers
    **HTTP 403**. With an honest identity of our own it answers 200 (verified by the user). The
    slash-less `…/p-<n>` URL the library builds answers **301** to `…/p-<n>/`.
- **No call returns a cinema's name from its id.** `get_cinema()` needs a location id. The showtimes
  JSON has no theater object (the id only appears inside ticketing URLs), and `get_movies` returns film
  metadata only. The name is only in the HTML page `https://www.allocine.fr/seance/salle_gen_csalle=<id>.html`
  (`<h1>`), which the library does not parse. Decision D1: the user types the name (§4.1).
- Dependencies: `requires_dist = ["beautifulsoup4"]` (unpinned). `requests` is used but not declared.
  `bs4` is imported at module import, even though `get_showtime` never uses it.

### Risks and known limitations (D17)

- **This is scraping behind a bot protection.** allocine.fr has no public API for this. The endpoint is the
  site's own JSON, behind Cloudflare, and it can refuse us (403 / 429) or change shape at any time, without
  notice. A refusal shows up as `access_denied` (§6). A change of shape shows up as `invalid_response`.
  Neither ever shows up as a crash or as silently empty data.
- **We identify ourselves honestly and never try to evade the protection.** We send
  `User-Agent: ha-movie-showtimes/0.1`, never a browser's identity. We use no extra headers, cookies,
  TLS or fingerprint tricks, proxies, or retries meant to get past a block. If the site refuses us, the
  integration reports it and waits for its normal 12 h refresh.
- We keep the load low by design: one cinema per entry, about 16 requests a day per cinema, no request
  per entity, no request at a restart with fresh data (D12), and the canonical URL so that no 301 doubles
  the requests (D17).
- **The site's Terms of Use have not been reviewed.** Whether automated access is allowed is unknown. The
  README should say so, and users run the integration at their own risk.
- The library is unofficial and pinned exactly (`0.0.14`). We depend on its private `_get_json_request`
  (D8) and, since D25, on its public `URLs.showtime_url`; the signature guards (§8.1, design doc §4.2) catch a
  change of either.
- **"Today" is Home Assistant's date; the days are AlloCiné (Paris) dates.** The sensors request the HA
  local date (`dt_util.now().date() + offset`) and AlloCiné answers for that Paris date. With Home
  Assistant far from Paris, the HA "today" can be a different calendar day from the one in Paris. "Today"
  then shows the Paris day with that date, not the day currently going on in Paris. This follows D10:
  grouping by AlloCiné date, only the displayed time converted. It changes nothing for installations in
  France.
- **The 60 s backstop cannot cancel the worker thread.** When `asyncio.timeout(call_timeout)` fires, the
  refresh is aborted (`SourceTimeoutError`), but the executor thread running the library keeps going until
  its current request's own connect/read timeouts (10 s / 20 s) end it. The worst case is bounded: at most
  the remaining requests of that one day's pagination, each under those timeouts. There is no burst of
  requests, and the next attempt is the scheduled one (30 min, D19).
- **Existence check depends on the live site's 404.** An unknown cinema id is rejected by allocine.fr with
  HTTP 404 (verified by the user), hence `invalid_cinema_id`. An existing cinema with nothing on that day
  answers an empty list, which is accepted (§4.1). If AlloCiné stopped answering 404, unknown ids would
  be accepted as empty cinemas.

### Version pins

- `manifest.json` → `"requirements": ["allocine-seances==0.0.14"]`.
- **Do not pin `beautifulsoup4`.** Our code never imports it, and Home Assistant core has no constraint
  for it. The core `scrape` integration pins `beautifulsoup4==4.13.3`. An exact pin of our own could
  conflict with it on installs that use both. Leaving it unpinned lets pip take whatever is installed
  or the latest version.
- `requests` is provided by Home Assistant (`requests==2.34.2` in `package_constraints.txt`). Do not list it.
- Dev environment: add `allocine-seances==0.0.14` to `[project].dependencies` in `pyproject.toml`, so
  that both CI jobs install it (each one runs `uv sync --group homeassistant …`, which also provides
  `requests`). Then run `uv lock`. Approved by the user (D7).

## 3. Modules and responsibilities

```
custom_components/movie_showtimes/
├── __init__.py          setup / unload / remove (store), midnight listener; gets the provider from the registry (D13);
│                        (D32) CONFIG_SCHEMA + async_setup → card.async_register_card, once per run
├── card.py              (D32) serves frontend/movie-showtimes-card.js and adds it with add_extra_js_url (?v=hash)
├── frontend/movie-showtimes-card.js   (D32–D41) the Lovelace card + editor, one vanilla ES module, no build;
│                        forked from the reference upcoming-media-card (MIT notices in its header, D39)
├── const.py             DOMAIN, CONF_SOURCE, CONF_CINEMA_ID, intervals, day counts, attribute names, storage constants
├── config_flow.py       user step (source; skipped with one source) → cinema step (D13)
├── coordinator.py       MovieShowtimesCoordinator, MovieShowtimesConfigEntry, CachedDay
├── store.py             (D12) ShowtimesStore, StoredSnapshot, (de)serialisation, §12
├── entity.py            MovieShowtimesEntity (device info, base CoordinatorEntity)
├── sensor.py            the 7 day sensors
├── showtimes.py         pure helpers: drop past showtimes, build attributes (HA time zone)
├── diagnostics.py
├── manifest.json
├── icons.json
├── strings.json
├── translations/en.json, translations/fr.json
└── client/              NO homeassistant import. Layout after D13 (§13.2):
    ├── __init__.py      re-exports the source-neutral API (models, exceptions, provider, registry)
    ├── models.py        source-neutral dataclasses, ShowtimeVersion
    ├── exceptions.py    source-neutral exceptions (ShowtimesError, …)
    ├── provider.py      ShowtimesProvider (ABC), SourceInfo, CinemaInfo
    ├── registry.py      PROVIDERS, get_provider_class, create_provider
    └── providers/
        ├── __init__.py
        └── allocine.py  AllocineProvider: the former api.py (URL/id parsing, library override, timeouts, Paris)
```

> **(D13)** §3.1–§3.3 describe how the AlloCiné source behaves, and that behaviour is unchanged. The
> **names** are superseded by §13: `AllocineClient` → `AllocineProvider` (in `client/providers/allocine.py`),
> `normalize_cinema_id` → `AllocineProvider.normalize_cinema_ref`, and the `Allocine*Error` classes →
> the neutral exceptions of §13.3 (mapping table there). §3.5 onwards uses the neutral names.

### 3.1 `client/exceptions.py`

**(D13) The hierarchy is defined in §13.3** (`ShowtimesError`, `SourceConnectionError`,
`SourceTimeoutError`, `CinemaNotFoundError`, `SourceParseError`, `InvalidCinemaRefError`,
`UnknownSourceError`). The `Allocine*` names used in §3.3 and §8.1 are the pre-D13 names; read them through
the rename table in §13.3. All of them carry a plain message, and the original exception is chained with
`raise … from err`.

### 3.2 `client/models.py`

> **(D24–D31)** `Showtime` gains optional `subtitled` (classic subtitles), `hard_of_hearing_subtitles`,
> `disabled_access`, `audio_description`, `formats`, `preview`, `weekly_outing`, `ticket_url`;
> `Film` gains optional `ref` and `details: FilmDetails | None`; new `ShowtimeFormats`, `Rating`, `Credit`,
> `FilmDetails`. All have defaults, so other sources and the fake provider are unchanged. Signatures:
> design doc §3. The block below shows the v1 core fields only.

```python
class ShowtimeVersion(StrEnum):
    ORIGINAL = "original"   # "ORIGINAL" of a film not exactly ["FRENCH"] -> VO, or VOST if subtitled (D2)
    DUBBED = "dubbed"       # "DUBBED"                     -> VF
    LOCAL = "local"         # "LOCAL", or "ORIGINAL" of a film whose languages are exactly ["FRENCH"] -> VF (D2)
    UNKNOWN = "unknown"     # any other value; kept, not dropped

@dataclass(frozen=True, slots=True, kw_only=True)
class Showtime:
    starts_at: datetime          # aware, tzinfo = ZoneInfo("Europe/Paris")
    version: ShowtimeVersion

@dataclass(frozen=True, slots=True, kw_only=True)
class Film:
    title: str
    showtimes: tuple[Showtime, ...]   # sorted by starts_at, never empty

@dataclass(frozen=True, slots=True, kw_only=True)
class DayShowtimes:
    cinema_id: str
    day: date
    films: tuple[Film, ...]           # sorted by title.casefold(); () = nothing on that day (valid)
```

Frozen, hashable tuples, so equality is cheap and the coordinator can use `always_update=False`.

### 3.3 `client/api.py`

```python
DEFAULT_CONNECT_TIMEOUT: Final = 10.0   # s, per HTTP request (inside the thread)
DEFAULT_READ_TIMEOUT: Final = 20.0      # s, per HTTP request (inside the thread)
DEFAULT_CALL_TIMEOUT: Final = 60.0      # s, whole get_showtime call incl. pagination (asyncio backstop)

def normalize_cinema_id(raw: str) -> str:
    """Return the cinema id from a bare id or an allocine.fr cinema URL (rules below).

    Raises:
        InvalidCinemaIdError: neither a valid id nor a supported URL.
    """

class AllocineClient:
    def __init__(
        self,
        *,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
    ) -> None: ...

    async def async_get_day(self, cinema_id: str, day: date) -> DayShowtimes:
        """Fetch and parse one day's showtimes.

        Raises:
            InvalidCinemaIdError, AllocineCinemaNotFoundError, AllocineConnectionError,
            AllocineTimeoutError, AllocineParseError.
        """
```

`normalize_cinema_id` is a pure function with no I/O. It runs in this order:

1. `value = raw.strip()`. If it is empty → `InvalidCinemaIdError`.
2. **URL form.** If `value` contains `"://"` or starts with `"www."` or `"allocine.fr"`, it is a URL. A
   missing scheme is completed with `https://`, then the result goes to `urllib.parse.urlsplit`. Accepted:
   - scheme `http` or `https`;
   - host (lower-cased, default port only) `allocine.fr`, `www.allocine.fr` or `m.allocine.fr`;
   - path `/seance/salle_gen_csalle=<ID>.html`, with an optional trailing `/`. Matched with
     `re.fullmatch(r"/seance/salle_gen_csalle=([A-Za-z0-9]+)\.html/?", path)`;
   - any query string and any fragment, both ignored (`?utm_source=…`, `#shwt_date=2026-11-12`).

   `<ID>` is extracted and then goes through step 3. Any other host, scheme or path, for example a film
   page `/film/fichefilm_gen_cfilm=….html` or `allocine.fr.evil.com` → `InvalidCinemaIdError`.

3. **Bare id.** `value.upper()` must fully match `^[A-Z0-9]{2,10}$`, otherwise `InvalidCinemaIdError`.

The id is put into a URL path, which is why the characters are restricted. The real ids look like one
letter followed by four digits (`W0124`, `P3757`). The regex is looser on purpose, so that a valid id with
an unexpected format is not rejected. `async_get_day` calls the function too, as defence in depth (a URL
passed to it is accepted).

Only the cinema page form is supported. It is the one the user sees in the browser, and the one in the
device's `configuration_url`. No other URL form is accepted (decision D9).

Internals (private, but the developer must follow them):

- `class _AllocineAPIWithTimeout(allocineAPI)` overrides **`_get_json_request(self, path, url_params=None)`**.
  Its signature is the library's, and `get_showtime` is its only user. The override:
  - **(D17) requests the canonical URL with a trailing slash.** The library builds `…/p-<n>` without one,
    so the override appends `/` when the path lacks it. The slash-less URL answers `301` to `…/p-<n>/` on
    every call, which doubled the HTTP requests;
  - calls `requests.get(path, params=url_params, timeout=(connect, read), headers={"User-Agent": USER_AGENT})`
    with **(D17)** `USER_AGENT: Final = "ha-movie-showtimes/0.1"`, a named module constant.
    allocine.fr (Cloudflare) answers `403` to the default `python-requests/x.y` identity and `200` to an
    honest one (verified by the user). The value **identifies this integration; it never impersonates a
    browser**. No other header, cookie, TLS fingerprint trick, proxy, or retry meant to get past a block is
    allowed. If the site still refuses, that is an error to report (below);
  - status 404 → `CinemaNotFoundError`. **(D17) 403 or 429 → `SourceAccessDeniedError(f"HTTP {status}")`**
    (§13.3). Any other non-200 → `SourceConnectionError(f"HTTP {status}")`;
  - body not JSON (`ValueError`) → `AllocineParseError`;
  - ~~removes the `results` items whose `"movie"` is `None`~~ **(D25) moved to our parser**, which skips them
    with a debug line; the library no longer walks the results, so its `TypeError` cannot happen.

  This is the only way to get a real timeout inside the worker thread: an `asyncio` timeout alone would
  leave the thread blocked forever. It also gives a typed 404 instead of parsing `"Error 404"`. The
  coupling to a private method is acceptable because the version is pinned exactly. A test pins the
  override's signature against the installed library (§8.1).

- `def _fetch_day_sync(self, cinema_id: str, day: date) -> DayShowtimes` runs **in the executor**. It
  fetches with ~~`get_showtime(cinema_id, day.isoformat())`~~ **(D25) `self._api.fetch_showtime_pages(cinema_id, day.isoformat())`**,
  our own bounded loop over `URLs.showtime_url(…, n)` that keeps no state on the instance (design doc §4.2), and
  converts the documents to models (design doc §4.3–§4.8). The conversion runs in
  the thread as well, because building the `ZoneInfo` may read tzdata. Errors are mapped like this:
  - `requests.Timeout` → `AllocineTimeoutError`; other `requests.RequestException` → `AllocineConnectionError`;
  - `KeyError`, `TypeError`, `ValueError` while the library walks the JSON, or while we convert → `AllocineParseError`;
  - our own `AllocineError`s pass through unchanged;
  - any other `Exception`, for example the library's bare `Exception("Error …")` if the override ever stops
    being called → `AllocineError` (generic). Never a crash.
- `async_get_day` runs:
  `async with asyncio.timeout(call_timeout): await asyncio.get_running_loop().run_in_executor(None, partial(self._fetch_day_sync, …))`.
  On `TimeoutError` it raises `AllocineTimeoutError`. Home Assistant installs its executor as the loop's
  default, so this is the same pool that `hass.async_add_executor_job` uses, and the client still does
  not import Home Assistant.
- One `_AllocineAPIWithTimeout` instance per client. The library keeps no state, so the instance is safe
  to use from the executor. **(D25) Our pagination keeps none either** (local variables only): a thread
  abandoned by the 60 s backstop can still be running when a manual refresh starts another day call on the same
  instance.
- Conversion rules (the required fields; the optional enrichment and the VO / VOST rules are in the design doc
  §4, and **never raise**, D28):
  - `startsAt`: `datetime.fromisoformat`. If it is naive → `.replace(tzinfo=ZoneInfo("Europe/Paris"))`; if
    it is aware → `.astimezone(ZoneInfo("Europe/Paris"))`. A missing or unparsable value → `AllocineParseError`.
  - `diffusionVersion` → `ShowtimeVersion`, with **(D2) `ORIGINAL` of a film whose `languages` are exactly
    `["FRENCH"]` → `LOCAL`** (design doc §4.4). An unknown value → `UNKNOWN`, logged once per value at warning
    level (stdlib `logging`, logger `custom_components.movie_showtimes.client`).
  - A film with an empty or non-string title → `AllocineParseError`. A film with no showtimes is dropped.
  - Sorting: films by `title.casefold()`, showtimes by `starts_at`.
  - The library returning `[]` → `DayShowtimes(films=())`. **That is valid data, not an error.**

### 3.4 Why sequential, why these timeouts

A refresh makes 8 day calls (§4.3). Usually each one is a single HTTP request: 15 films per page, and a
small cinema has fewer. They are awaited **one after the other**, never with `gather`, to be gentle with
allocine.fr. Each HTTP request gets at most 10 s to connect and 20 s per read. Each day call gets at most
60 s overall, pagination included. If allocine.fr stops responding, the refresh ends at the first failure
(§4.3), so the worst case is about one minute.

### 3.5 Home Assistant side

`const.py`:

```python
DOMAIN: Final = "movie_showtimes"         # moved here from __init__.py
CONF_SOURCE: Final = "source"             # (D13) provider id, e.g. "allocine"
CONF_CINEMA_ID: Final = "cinema_id"       # the provider's canonical cinema id
UPDATE_INTERVAL: Final = timedelta(hours=12)
DAYS_EXPOSED: Final = 7                   # sensors: today .. today+6
DAYS_FETCHED: Final = 8                   # today .. today+7 (one buffer day, see §4.4)
SHOWTIME_GRACE_PERIOD: Final = timedelta(minutes=15)   # a showtime stays visible until starts_at + this (D11)
MAX_DATA_AGE: Final = timedelta(hours=48)   # (D12) a day's data is shown at most this long after it was fetched
RETRY_AFTER_CONNECTION_ERROR: Final = timedelta(minutes=30)   # (D19) early retry after a transient connection error
STORAGE_VERSION: Final = 1                  # (D12) §12.2; unchanged by D27 (nothing released)
STORAGE_MINOR_VERSION: Final = 1            # (D12)
ATTR_DATE: Final = "date"
ATTR_FILMS: Final = "films"
ATTR_FETCHED_AT: Final = "fetched_at"       # (D12)
ATTR_VOST: Final = "vost"                   # (D26) plus ATTR_DETAILS and the other film keys, design doc §6
```

`coordinator.py`:

```python
type MovieShowtimesConfigEntry = ConfigEntry[MovieShowtimesCoordinator]

@dataclass(frozen=True, slots=True, kw_only=True)
class CachedDay:                              # (D12) one day as held in memory and in the store
    showtimes: DayShowtimes
    fetched_at: datetime                      # aware UTC; when this day was last fetched successfully

type ShowtimesData = dict[date, CachedDay]    # (D12) was dict[date, DayShowtimes]

class MovieShowtimesCoordinator(DataUpdateCoordinator[ShowtimesData]):
    config_entry: MovieShowtimesConfigEntry
    last_refresh: datetime | None             # (D12) aware UTC; end of the last successful _async_update_data
    restored_from_store: bool                 # (D12) for diagnostics

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MovieShowtimesConfigEntry,
        provider: ShowtimesProvider,          # (D13) was client: AllocineClient
        store: ShowtimesStore,                # (D12)
    ) -> None:
        # super().__init__(hass, _LOGGER, config_entry=config_entry, name=f"{DOMAIN} {config_entry.unique_id}",
        #                  update_interval=UPDATE_INTERVAL, always_update=False)

    @property
    def cinema_id(self) -> str: ...            # config_entry.data[CONF_CINEMA_ID]

    @property
    def provider(self) -> ShowtimesProvider: ...   # (D13) entities read provider.source / provider.cinema_url()

    async def async_initialize(self) -> None:  # (D12) replaces the bare first refresh, §12.3
        """Restore from the store, refresh only if needed; raise ConfigEntryNotReady only with nothing usable."""

    async def _async_update_data(self) -> ShowtimesData: ...
    # §4.3. (D12): starts with self.update_interval = UPDATE_INTERVAL, merges a partial result (§12.4),
    # saves the snapshot, sets last_refresh, and ends with _async_schedule_next_showtime(result).

    @callback
    def async_handle_midnight(self, now: datetime) -> None:     # §4.4, via async_track_time_change
        """Re-render the entities so that each day sensor moves to its new date."""

    @callback
    def _async_handle_showtime_started(self, now: datetime) -> None:   # §4.4, via async_track_point_in_time
        """Re-render the entities so that the showtime that just started drops out, then re-arm."""

    @callback
    def _async_schedule_next_showtime(self, data: ShowtimesData) -> None:
        """Cancel the pending timer; arm one at the earliest instant > dt_util.utcnow() among
        every starts_at + SHOWTIME_GRACE_PERIOD and (D12/D18) every day's day_data_expiry(cached) (none if none)."""

    async def async_shutdown(self) -> None:
        """Cancel the showtime timer, then await super().async_shutdown()."""
```

`self._unsub_showtime: CALLBACK_TYPE | None` holds the pending timer. Both callbacks call
`self.async_update_listeners()` then `self._async_schedule_next_showtime(self.data)`. `async_shutdown` is
already registered by `DataUpdateCoordinator.__init__` through `config_entry.async_on_unload`
(HA 2026.10.1, `update_coordinator.py`), so overriding it is enough to cancel the timer on unload.

`showtimes.py` (Home Assistant side, pure functions, no I/O). The sensor uses them, and they are unit-tested
directly:

```python
def remaining_films(day: DayShowtimes, now: datetime) -> tuple[Film, ...]:
    """Films of day with only their showtimes whose starts_at + SHOWTIME_GRACE_PERIOD > now. A film left with none is dropped."""

def attribute_version(showtime: Showtime) -> str:              # (D26)
    """"vf" (DUBBED, LOCAL), "vost" (ORIGINAL, subtitled is True), "vo" (ORIGINAL otherwise), "other" (UNKNOWN)."""

def film_attributes(film: Film) -> dict[str, Any]:             # (D24, D29) shape: design doc §6
    """{"title", "vf", "vo", "vost"[, "other"], "accessibility": {"pmr", "sme", "audio_description"},
    <light film keys>, "details": {…, "showtimes": [...]}}:
    times as dt_util.as_local(starts_at).strftime("%H:%M")."""

def day_data_expiry(cached: CachedDay) -> datetime:          # (D18)
    """cached.fetched_at + MAX_DATA_AGE: the instant a day's data stops being shown."""

def is_day_usable(cached: CachedDay, now: datetime) -> bool:   # (D18)
    """now < day_data_expiry(cached). Callers check for a missing day themselves."""
```

**(D18) One expression for the age limit.** A day's data is usable while `now < fetched_at + MAX_DATA_AGE`,
which is strict, and unusable from that instant on. This mirrors the showtime rule, where a showtime is
dropped at exactly `starts_at + grace`. Every use goes through these two helpers: the sensor's
availability, the restore check in `async_initialize`, the partial-refresh merge, and the re-render timer,
which is armed at `day_data_expiry(cached)` when that is after now. The bug this fixes: the timer fired at
exactly `fetched_at + 48 h`, while the condition was `age <= 48 h`, so at that instant the data was still
"usable", nothing changed, and no later timer was armed. The sensor stayed available indefinitely.
Exact names follow the implementation.

`entity.py`: `class MovieShowtimesEntity(CoordinatorEntity[MovieShowtimesCoordinator])` with
`_attr_has_entity_name = True` and `_attr_device_info = DeviceInfo(...)` (§5.1).

`sensor.py`: `PARALLEL_UPDATES = 0`, `async_setup_entry` adds the 7 sensors,
`class MovieShowtimesDaySensor(MovieShowtimesEntity, SensorEntity)` (§5).

`__init__.py`:

```python
PLATFORMS: Final = [Platform.SENSOR]

async def async_setup_entry(hass: HomeAssistant, entry: MovieShowtimesConfigEntry) -> bool:
    # try: provider = create_provider(entry.data[CONF_SOURCE], session=async_get_clientsession(hass))   (D13)
    # except UnknownSourceError as err: raise ConfigEntryError(translation_domain=DOMAIN,
    #                                         translation_key="unknown_source", …) from err
    # store = ShowtimesStore(hass, entry.entry_id)                                                 (D12)
    # coordinator = MovieShowtimesCoordinator(hass, entry, provider, store)
    # await coordinator.async_initialize()   (D12, §12.3; was async_config_entry_first_refresh())
    # entry.runtime_data = coordinator
    # entry.async_on_unload(async_track_time_change(hass, coordinator.async_handle_midnight,
    #                                                hour=0, minute=0, second=0))
    # await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

async def async_unload_entry(hass: HomeAssistant, entry: MovieShowtimesConfigEntry) -> bool:
    # return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_remove_entry(hass: HomeAssistant, entry: MovieShowtimesConfigEntry) -> None:   # (D12)
    # await ShowtimesStore(hass, entry.entry_id).async_remove()
    # A new instance: runtime_data is gone after unload. Store.async_remove ignores a missing file.
```

`manifest.json`: `"config_flow": true`, `"requirements": ["allocine-seances==0.0.14"]`,
no `loggers` key: the library never uses `logging`, and our own modules log under
`custom_components.movie_showtimes`. Keep `integration_type: "service"` and `iot_class: "cloud_polling"`.

## 4. Data flow

### 4.1 Config flow (`config_flow.py`: steps `user` → `cinema`, D13)

Schemas use **`probatio`** (`probatio.Schema`, `probatio.Required`). Home Assistant 2026.10.1 uses it
instead of voluptuous for flow schemas (`homeassistant/data_entry_flow.py` imports `probatio`).

**Step `user` (choose the source, D13).** With a single registered provider (v1: AlloCiné only), it shows
nothing. It sets `self._source = next(iter(PROVIDERS))` and returns `await self.async_step_cinema()`. With
two or more, it shows a form with one required field, `source`: a `SelectSelector` whose options are the
registry's ids, labelled through `selector.source.options.<id>` translations. On submit it stores the
choice and continues to `cinema`. Details and the rule for adding a source: §13.5.

**Step `cinema`** (what was `user` before D13). Form fields:

| Key                  | Type                                                                 | Notes                                                                                                                                                                                                                                                                                                                           |
| -------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cinema_id`          | text, required                                                       | The provider's cinema reference. For AlloCiné that is the id (`W0124`) or the cinema page URL (`https://www.allocine.fr/seance/salle_gen_csalle=W0124.html`). The step `description` gives the source's own examples through `description_placeholders` (`source_name`, `ref_example`, `url_example` from `SourceInfo`, §13.3). |
| `name` (`CONF_NAME`) | text, **optional** (D22; `probatio.Optional(CONF_NAME, default="")`) | The display name, used for the entry title and the device name. Stripped. Blank → `f"{SourceInfo.name} - {cinema_id}"`, e.g. `AlloCiné - W0124`, also when the reference was a pasted URL (the canonical id is used).                                                                                                           |

On submit (`provider = create_provider(self._source, session=async_get_clientsession(self.hass))`):

1. `cinema_id = provider.normalize_cinema_ref(user_input["cinema_id"])`. For AlloCiné this accepts an id or
   a URL (§3.3). `InvalidCinemaRefError` → `errors["cinema_id"] = "invalid_cinema_id"`, and the form is
   shown again without any request.
2. Name stripped. It is never an error (D22: `name_required` no longer exists); a blank name is replaced
   at step 5.
3. `await self.async_set_unique_id(f"{source_id}_{cinema_id}")` (e.g. `allocine_W0124`, D13), then
   `self._abort_if_unique_id_configured()` → abort `already_configured`, before any network call.
4. Validation: `await provider.async_validate_cinema(cinema_id, dt_util.now().date())`.

   | Outcome                                                    | Result                                                                                 |
   | ---------------------------------------------------------- | -------------------------------------------------------------------------------------- |
   | `CinemaInfo` returned                                      | the cinema exists → create the entry                                                   |
   | `CinemaNotFoundError`                                      | `errors["cinema_id"] = "invalid_cinema_id"`                                            |
   | `SourceAccessDeniedError` (HTTP 403 / 429, D17)            | `errors["base"] = "access_denied"`, `_LOGGER.warning` with the cause (the HTTP status) |
   | other `SourceConnectionError` (incl. `SourceTimeoutError`) | `errors["base"] = "cannot_connect"`, `_LOGGER.warning` with the cause (D17)            |
   | `SourceParseError` / any other `ShowtimesError`            | `errors["base"] = "unknown"`, `_LOGGER.exception(...)`                                 |

   For AlloCiné, `async_validate_cinema` fetches that day (§13.4), which is how the three cases are told
   apart. "Does not exist" is the HTTP 404. "Unreachable" is a network error, a timeout or another HTTP
   status. "Exists but nothing on" is a 200 with `no.showtime.error`, an empty day, and that is a success.

5. `self.async_create_entry(title=name or f"{provider.source.name} - {cinema_id}", data={CONF_SOURCE: source_id, CONF_CINEMA_ID: cinema_id})`
   (through `_async_finish`).

The form is shown again with the user's input (`add_suggested_values_to_schema`) after an error.

**Cinema name (decisions D1, D22):** the user may type it, or leave it blank for the default title. No
call of the library can resolve an id to a name (§2), and there is no scraping of the `<h1>`.

### 4.2 Config entry contents

- `unique_id` = **`f"{source_id}_{cinema_id}"`** (D13), e.g. `"allocine_W0124"`. It is the same whether the
  user typed the id or pasted the URL, and two sources can never collide.
- `title` = the name the user typed.
- `data` = `{"source": "allocine", "cinema_id": "W0124"}` (D13: `source` recorded from v1). The source and
  the cinema id are what the entry is, so they go in `data`.
- `options` = `{}`. Nothing is optional in v1.
- Config entry `VERSION = 1`, `MINOR_VERSION = 1`. No `async_migrate_entry` is needed: nothing has been
  released yet, and `source` is present from the first version (§13.6).

### 4.3 Coordinator refresh (`_async_update_data`)

- `update_interval = 12 h`, as the user asked ("twice a day"). The programme changes rarely, and
  `CLAUDE.md` asks for hours between refreshes. That makes 16 requests a day per cinema (8 days × 2) in
  the usual one-page case.
- `today = dt_util.now().date()`, which uses Home Assistant's time zone. Days fetched:
  `today + timedelta(days=i)` for `i in range(DAYS_FETCHED)`. They go in order, one at a time, through
  `provider.async_get_day` (D13: was `client.async_get_day`).
- Failure policy, on the neutral exceptions (D13, §13.3). Every `UpdateFailed` passes
  `translation_placeholders={"source": provider.source.name}`, so the messages name the source without
  hard-coding allocine.fr:
  - **(D17) `SourceAccessDeniedError`** (HTTP 403 / 429) on any day → stop at once and raise
    `UpdateFailed(…, translation_key="access_denied", translation_placeholders={"source": …, "status": …})`.
    It is caught before its parent `SourceConnectionError`. Log **one** warning with the HTTP status when
    the refusal starts: only while `self.last_update_success` is still `True`, so failing refreshes in a
    row do not repeat it. The coordinator's own "Error fetching / recovered" lines still apply. **No
    `retry_after`** (D19): never retry early to get past a refusal; the next attempt is the normal 12 h one;
  - other `SourceConnectionError` (incl. `SourceTimeoutError`) on any day → **stop at once** (do not try the
    remaining days against a site that is down) and raise
    `UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect", …, retry_after=RETRY_AFTER_CONNECTION_ERROR.total_seconds())`.
    **(D19)** The transient failure is retried after 30 min, using the coordinator's built-in `retry_after`
    (one-shot: the following schedule is the normal interval again). Repeated failures are retried every
    30 min until a success, and the 12 h rhythm restarts from that success (`_async_update_data` resets
    `update_interval` first). These retries add no log line: the coordinator logs once when it starts
    failing and once on recovery. At setup, HA ignores `retry_after` during the first refresh, so §12.3
    applies it itself;
  - `CinemaNotFoundError` on any day → stop and raise `UpdateFailed(…, translation_key="cinema_not_found")`,
    with no `retry_after` (12 h).
  - `SourceParseError` (or another `ShowtimesError`) on one day → log the day, **leave
    that day out of the result** and go on. **(D20) Logged once per episode:**
    - WARNING for the first failing day of a refresh when the previous refresh had no parse failure;
    - DEBUG otherwise, i.e. the other failing days of that refresh, and the following refreshes while
      failures go on.

    The flag `_parse_failing = bool(failed)` is written at the end of every refresh that went through all
    days. It is `True` after any parse failure, every day included, and reset by a clean refresh. A refresh
    aborted by a connection, access or not-found error leaves it unchanged. Parse failures get no `retry_after` (12 h). If **every** day fails this way →
    `UpdateFailed(…, translation_key="invalid_response")`. If the site changes, every day fails and this
    becomes a clear `UpdateFailed`. A one-off odd day keeps its previous copy if there is one (D12,
    §12.4), and otherwise its sensor is unavailable (§5.3). Nothing is replaced with empty data.

- It returns `dict[date, CachedDay]` (D12). The successful days get `fetched_at = now`. A day that failed
  to parse keeps the previous `CachedDay` from `self.data`, if it is in range and not older than
  `MAX_DATA_AGE` (§12.4).
- On success it saves the snapshot to the store, **only while the entry state is `SETUP_IN_PROGRESS` or
  `LOADED`** (D21), and sets `last_refresh` (D12, §12.4).
- When an `UpdateFailed` is raised, the coordinator keeps the previous `data`, sets
  `last_update_success = False`, logs once (`log-when-unavailable`) and tries again at the next interval.
  **(D12) The sensors no longer go unavailable because of that:** they keep showing the previous data
  until it is older than `MAX_DATA_AGE` (§5.3, §12.5). The store is not touched.
- **(D12) Setup no longer calls `async_config_entry_first_refresh` directly.** `async_initialize` (§12.3)
  calls it only when the stored data is not fresh, and turns its `ConfigEntryNotReady` into "serve the
  stored data" when the store holds something usable. With nothing usable stored, a failure is still
  `ConfigEntryNotReady`, and Home Assistant retries with backoff (`test-before-setup`).
- A refresh at setup makes 8 sequential calls, typically a few seconds. Home Assistant only logs a warning
  if setup goes over 10 s, which is acceptable.

### 4.4 Time-driven re-renders: midnight rollover and past showtimes

What a sensor shows depends on the data **and on the current time**. The data is **keyed by real date**,
not by offset, and the coordinator keeps every showtime of every fetched day, past ones included.
Everything time-dependent is computed by the sensor when it renders, from a single `now = dt_util.now()`:

- its date: `now.date() + timedelta(days=offset)`, with `now` in Home Assistant's time zone;
- its day: `coordinator.data.get(that_date)`;
- its content: `remaining_films(day, now)` (§3.5). A showtime is kept only while
  `starts_at + SHOWTIME_GRACE_PERIOD > now`, so it stays visible for 15 minutes after it starts (the
  adverts) and is dropped at exactly `starts_at + 15 min` (decision D11). A film with no showtime left is
  dropped from the list **and from the count**. On future days nothing has started yet, so in practice
  this only affects "Today".

Two timers make the sensors re-render at the moments the result changes. **No network call is made**
when either one fires:

1. **Midnight**, for the day change: `async_track_time_change(hass, coordinator.async_handle_midnight,
hour=0, minute=0, second=0)`, registered in `async_setup_entry` and removed through
   `entry.async_on_unload`. At 00:00:00 local time every sensor renders for its new date: "Today" now shows
   what was fetched as "tomorrow".
2. **The next showtime expiry**, for past showtimes: a one-shot
   `async_track_point_in_time(hass, coordinator._async_handle_showtime_started, next_expiry)`.
   `next_expiry` is the earliest instant strictly after now among every `starts_at + SHOWTIME_GRACE_PERIOD`
   and **(D12) every day's `day_data_expiry(cached)` = `fetched_at + MAX_DATA_AGE`**, so that a day that
   becomes too old turns unavailable on time. Usability is strict (`now < expiry`, D18), so at the instant
   the timer fires the day is already unusable. It is computed across all of `data`, and armed by `_async_schedule_next_showtime`,
   which runs:
   - at the end of every successful `_async_update_data`, with the new data;
   - **(D12) in `async_initialize` after data is restored from the store** (§12.3);
   - after each showtime timer fires, which also covers several showtimes at the same minute in one fire;
   - after the midnight callback.

   The timer and `remaining_films` use the same constant and the same expression, so the drop happens
   exactly when the timer fires.

   Each arming cancels the pending timer first, so at most one is pending per coordinator. After a failed
   refresh the timer from the last good data stays armed, which is right, because the sensors still render
   that data. `async_shutdown` cancels it on unload.

**Why an exact timer and not a fixed cadence.** The output changes only at known instants: the expiry
times (start + 15 min) of the showtimes we already hold, and local midnight. A timer at the next expiry
re-renders exactly then, accurate to the second. That is one wake-up per distinct start time, typically
5 to 40 a day per cinema. A periodic tick every minute would mean 1,440 wake-ups × 7 sensors a day, mostly
re-rendering nothing, and would still be up to a minute late. `async_track_point_in_time` fires "at or
after" its time, so the sensor's `now` is always ≥ `next_expiry` and the expired showtime is dropped. The
next arming looks strictly after that `now`, so the same showtime cannot fire twice.

The grace period does not carry over midnight. A showtime at 23:50 on day D is visible on "Today" until
midnight, and then "Today" becomes D+1. Each day keeps its AlloCiné date bucket (D10), so the 23:50 showtime
is not moved onto D+1 for its last 5 minutes. Both timers just call `coordinator.async_update_listeners()`. The
5 sensors whose output did not change write the same state again, and the state machine does not fire a
`state_changed` event for that.

The midnight listener stays separate from the showtime timer. On a closed day there may be no future
showtime for days, but midnight still has to move the sensors. Keeping a plain cron-style listener for it
is simpler than merging "next midnight" into the one-shot computation.

Other properties of this design:

- Because each refresh fetches **8 days** (today … today + 7, decision D3), the new "today + 6" is already
  in the data after midnight. With a 12 h interval the next refresh is always less than 24 h away.
- A sensor can never show the wrong day. Even if refreshes fail for days, a sensor only shows data for its
  actual date, or is unavailable: when its date is not in `data`, or (D12) when its data is older than
  `MAX_DATA_AGE`.
- Days older than today stay in `data` until the next refresh replaces it. They are harmless and unused.
- A refresh during the day returns today's full list again, past showtimes included. That is harmless,
  because filtering happens at render time, never in the coordinator. Diagnostics show the unfiltered data.
- Time zones: "today", midnight and the `HH:MM` rendering use Home Assistant's time zone (`dt_util`). The
  client's datetimes are aware `Europe/Paris`, so the comparison `starts_at + grace > now` is correct
  whatever Home Assistant's zone is. Showtimes stay grouped by their AlloCiné (French) date, and only the
  displayed time is converted (decision D10). With a zone far from Paris, an evening showtime can display
  as an early-morning `HH:MM` on the sensor of its AlloCiné date. That is accepted.

### 4.5 How data reaches the entities

`coordinator.data` (refreshed, or restored from the store at setup, D12) → `CoordinatorEntity` listener
(data refresh, midnight or showtime timer) →
`MovieShowtimesDaySensor._handle_coordinator_update`. It computes the state once from a single `now`
(§5.3) and writes it. There is no request per entity.

## 5. Entities

### 5.1 Device

```python
DeviceInfo(
    identifiers={(DOMAIN, entry.unique_id)},                 # (D13) "allocine_W0124", was the bare cinema id
    name=entry.title,
    manufacturer=provider.source.name,                       # (D13) "AlloCiné", from SourceInfo
    entry_type=DeviceEntryType.SERVICE,
    configuration_url=provider.cinema_url(cinema_id),        # (D13) moved from const.CINEMA_URL into the provider
)
```

If `cinema_url` returns `None` (a source with no public cinema page), `configuration_url` is left out.

### 5.2 The 7 sensors (`sensor` platform)

One `SensorEntityDescription` per offset, built from a tuple in `sensor.py`:

| offset | `key`   | `translation_key` | en name   | fr name      | default entity_id (device "Cinéma l'Etincelle") |
| ------ | ------- | ----------------- | --------- | ------------ | ----------------------------------------------- |
| 0      | `day_0` | `today`           | Today     | Aujourd'hui  | `sensor.cinema_l_etincelle_today`               |
| 1      | `day_1` | `tomorrow`        | Tomorrow  | Demain       | `sensor.cinema_l_etincelle_tomorrow`            |
| 2      | `day_2` | `day_2`           | In 2 days | Dans 2 jours | `sensor.cinema_l_etincelle_in_2_days`           |
| 3…6    | `day_N` | `day_N`           | In N days | Dans N jours | `sensor.cinema_l_etincelle_in_N_days`           |

- `unique_id = f"{entry.unique_id}_{description.key}"` (D13), e.g. `allocine_W0124_day_0`. It is namespaced
  by source, and tied to the offset, never to a date.
- `has_entity_name = True`. The name comes from the translation. Names are static, so no weekday names:
  the actual date is in the `date` attribute.
- Icon: `icons.json` → `entity.sensor.<translation_key>.default = "mdi:movie-open"` (icon translations).
- No `device_class` (none fits a film count), no `state_class` (long-term statistics of a film count would
  be meaningless), no unit, no `entity_category`. All 7 are enabled by default (the user asked for them).

### 5.3 State and attributes

The sensor computes its whole state **once per render**, from one `now`, in a private
`_compute(now) -> None`. That way `available`, the state and the attributes always agree. A boundary
crossed between two property reads cannot give a count that disagrees with the list. `_compute` is called
from `__init__` and from `_handle_coordinator_update`, the latter before `super()._handle_coordinator_update()`
writes the state. It sets:

- `self._day_usable` **(D12, replaces `_day_present`)**: `cached = coordinator.data.get(that_date)` is
  not `None` **and** `is_day_usable(cached, now)`, i.e. `now < fetched_at + MAX_DATA_AGE` (D18).
  **`available` = `self._day_usable` only.** It deliberately does **not** call `super().available`, so it
  ignores `coordinator.last_update_success`. The data is a timetable keyed by real date and filtered by
  the current time, so the last good copy stays correct after a failed refresh or a restart while
  allocine.fr is down, within `MAX_DATA_AGE`. The `entity-unavailable` rule still holds: a sensor goes
  unavailable when its data cannot be trusted (too old) or does not exist (day not covered). It never
  shows `0` for a day it knows nothing about. Rationale and limits: §12.5.
- `_attr_native_value` (`int`): `len(remaining_films(cached.showtimes, now))`. **0 on a closed day, and 0
  from 15 min after the last showtime of the day starts. The sensor stays available in both cases.**
- `_attr_extra_state_attributes`:

  ```json
  {
    "date": "2026-11-11",
    "fetched_at": "2026-11-11T07:00:12+01:00",
    "films": [
      { "title": "Film A", "vf": ["15:00", "20:30"], "vo": [], "vost": [], "accessibility": { "pmr": ["20:30"], "sme": [], "audio_description": [] }, "runtime": 105, "details": { "showtimes": […] } },
      { "title": "Film B", "vf": [], "vo": [], "vost": ["18:00"], "accessibility": { "pmr": [], "sme": [], "audio_description": [] }, "details": { "showtimes": […] } }
    ]
  }
  ```

  (Abridged. **(D24, D29)** The complete per-film shape, with every enrichment key, the rule "omitted when
  `None` / empty" and four real examples from C0159 and W7520, is in the design doc §6.)
  - `films` holds only the films and showtimes **not yet expired**, i.e. `starts_at + 15 min > now`
    (§4.4), built with `film_attributes`. That applies to `details.showtimes` too.
  - Times are `"HH:MM"` strings **in Home Assistant's configured time zone**:
    `dt_util.as_local(starts_at).strftime("%H:%M")`. The client gives aware `Europe/Paris` datetimes, and
    the conversion happens here, on the Home Assistant side (decision D6). They are sorted by instant.
    For a French installation (`Europe/Paris`) they are exactly the times on allocine.fr.
  - `vf` = `DUBBED` + `LOCAL` (subtitled or not), `vost` = `ORIGINAL` with `subtitled is True`, `vo` =
    `ORIGINAL` otherwise (decision D2, revised; D26). The provider maps an `ORIGINAL` showtime of a film whose
    `languages` are exactly `["FRENCH"]` to `LOCAL`, so it is in `vf`. `subtitled` means classic subtitles: a
    `*_st` list, the tag `Showtime.Accessibility.Subtitled` or a `Localization.Subtitle.*` tag (both conventions
    are real). **(D30, D31)** `accessibility` lists the `pmr`, `sme` and `audio_description` showtimes. The three keys are always present, possibly empty. If a film has `UNKNOWN`
    showtimes, `other` is added to that film only. No version is silently lost.
  - Films in the client's order (by title).
  - `date` is the sensor's date (ISO), always present when available.
  - **(D12) `fetched_at`**: when this day's data was fetched from allocine.fr, as an ISO datetime in Home
    Assistant's time zone (`dt_util.as_local(cached.fetched_at).isoformat()`). Since sensors may now show
    data kept through a failed refresh or a restart, this tells the user (and templates) how old it is. It
    is small and changes only at a successful refresh, so it stays recorded.

- Size and recorder: the state is a short integer, well under the 255-character limit. `films` can grow
  large: a multiplex with about 25 films × 8 showtimes is around 3 KB per sensor, × 7 sensors, rewritten at
  every change. Home Assistant drops recorded attributes over 16 KiB (`MAX_STATE_ATTRS_BYTES`) and logs a
  warning. **So `_unrecorded_attributes = frozenset({ATTR_FILMS})`**: the history keeps the count, the
  `date` and `fetched_at`, not the list.
- **(D29)** With the enrichment, `films` is much larger (measured: ≈ 127 KB per sensor for C0159, 36 films, ≈ 73 KB for W7520, 26 films; no cap, user
  decision). The recorder excludes unrecorded attributes by top-level key before its 16 KiB check, and every new
  key is nested inside `films`, so **the recorder is not affected**. No new top-level attribute may be added.
  Heavy keys sit under each film's `details`. Cost on the frontend side: design doc §7.

## 6. Errors — where raised, what the user sees

| Where                                       | Raised                                                                                                                                    | User sees                                                                                                                                                                                                                                                 |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| config flow                                 | form errors `invalid_cinema_id`, `access_denied` (D17), `cannot_connect`, `unknown`; abort `already_configured` (D22: no `name_required`) | Translated message on the form / abort dialog. `access_denied` and `cannot_connect` also log their cause.                                                                                                                                                 |
| refresh refused, HTTP 403 / 429 (D17)       | `UpdateFailed` (`access_denied`), one warning with the status per refusal episode                                                         | Same as any failed refresh (previous data kept until `MAX_DATA_AGE`). The message says the source refused the request, not that it is unreachable.                                                                                                        |
| setup, fresh store (D12)                    | nothing, no request                                                                                                                       | Sensors immediately show the stored data.                                                                                                                                                                                                                 |
| setup, stale store, refresh fails (D12)     | `UpdateFailed` caught in `async_initialize`, warning logged                                                                               | Entry loaded. Sensors show the stored data (`fetched_at` shows its age), unavailable per day beyond `MAX_DATA_AGE`.                                                                                                                                       |
| setup, nothing usable stored, refresh fails | `UpdateFailed` → `ConfigEntryNotReady`                                                                                                    | Entry "Failed to set up, will retry" with the translated reason. Automatic retry.                                                                                                                                                                         |
| later refresh                               | `UpdateFailed` (`cannot_connect`, `cinema_not_found`, `invalid_response`)                                                                 | (D12) Sensors keep the previous data until it is older than `MAX_DATA_AGE`, then unavailable. One log line when the refresh starts failing, one when it recovers. (D19) `cannot_connect` is retried every 30 min until it succeeds; the others wait 12 h. |
| one day unparsable                          | warning log, previous copy of the day kept (D12)                                                                                          | That day keeps its previous data if it has one, otherwise its sensor is unavailable. The others are fine.                                                                                                                                                 |
| store corrupt / unreadable (D12)            | HA renames a corrupt file and raises its own repair; we log a warning                                                                     | As "nothing usable stored".                                                                                                                                                                                                                               |
| closed day                                  | nothing                                                                                                                                   | State `0`, `films: []`.                                                                                                                                                                                                                                   |
| last showtime of today started 15 min ago   | nothing (showtime timer re-render)                                                                                                        | "Today" state `0`, `films: []`, still available.                                                                                                                                                                                                          |

`strings.json` sections (D13: source-neutral wording, the source's name comes from placeholders):

- `config.step.user`: the source choice. Title, `data.source`, `data_description.source`. Shown only with
  two or more sources;
- `config.step.cinema`: title "Add a cinema"; a description using `{source_name}`, `{ref_example}` and
  `{url_example}`; `data` and `data_description` for `cinema_id` and `name`. The data description stays
  generic, because the examples live in the description;
- `selector.source.options.<source_id>` (`allocine` → "AlloCiné");
- `config.error`: `invalid_cinema_id`, `access_denied` (D17), `cannot_connect`, `unknown` (D22: no
  `name_required`; the `name` data description says a blank name gives "{source} - {id}").
  Generic texts, e.g. "Invalid or unknown cinema. Check the reference you entered." and, for
  `access_denied`, "The source refused the request (it may be blocking automated access). Try again later.";
- `config.abort.already_configured`;
- `entity.sensor.<translation_key>.name` ×7;
- `exceptions`: `cannot_connect`, `cinema_not_found` and `invalid_response`, each with `{source}`
  ("Could not reach {source} to fetch the showtimes."), plus `unknown_source` with `{source}` ("This
  entry uses the source {source}, which this version of the integration does not provide."), plus
  **(D17)** `access_denied` with `{source}` and `{status}` ("{source} refused the request (HTTP {status}).
  It may be blocking automated access; the next refresh will try again.").

The same keys go in `translations/en.json` and `translations/fr.json`.

## 7. Diagnostics (`diagnostics.py`)

`async_get_config_entry_diagnostics` returns:

- `entry`: `title`, `data` (includes `source`), `unique_id`;
- `source` **(D13)**: `{"id", "name", "time_zone"}` from `provider.source`. It comes from the provider, so
  diagnostics never name AlloCiné themselves;
- `coordinator`: `last_update_success`, `last_exception` (`repr`), `update_interval`, **(D12)**
  `last_refresh` (ISO), `restored_from_store` (bool), `data_age_seconds` (now − `last_refresh`);
- `days`: `{iso_date: {"fetched_at": iso, "film_count": n, "films": [{"title", "showtimes": [{"starts_at": iso, "version"}]}]}}`
  (`fetched_at` added by D12). **(D24)** Each film adds `ref`, each showtime its four flags (`subtitled`,
  `hard_of_hearing_subtitles`, `disabled_access`, `audio_description`), and a top-level `films`
  holds the film catalogue as the store writes it (design doc §5.2, §10 step 7).

There are no secrets: no credentials, and the cinema id and name are public. It still goes through
`async_redact_data(…, TO_REDACT)` with `TO_REDACT: Final = set()`, so there is one obvious place to add
a field if a secret ever appears.

## 8. Test plan

Tests never touch the network. Each coverage scope must reach 95 % on its own.

> **(D13)** The layout of the tests changes; see §13.8. What §8.1 lists becomes the **AlloCiné provider's
> own tests** (`tests/movie_showtimes/client/providers/test_allocine.py`), plus the shared contract suite.
> §8.2 runs against a **fake provider**, never against AlloCiné. Exception names follow §13.3.

### 8.1 Client — `tests/movie_showtimes/client/` (no Home Assistant)

> **(D24–D31)** The enrichment, pagination, VO / VOST and store tests, and the fixture plan, are in the design
> doc §9. **The fixtures listed below are synthetic** (they use `dubbed` / `local` lists that AlloCiné does not
> send, and an int `page`); the real captures are W0124 (`/tmp/lib/r.json`, one film), C0159 (a full day, 3 pages) and
> W7520 (a full day, 2 pages), from which trimmed real fixtures are derived by removing keys only (design doc §9.1). Since D25, "pagination" and "the library walks the JSON" mean our own
> loop and parser; add the `URLs.showtime_url` guard next to the `_get_json_request` one (design doc §4.2).

Fixtures in `tests/movie_showtimes/client/fixtures/`, recorded from
`https://www.allocine.fr/_/showtimes/theater-<id>/d-<date>/p-<n>` and trimmed to the keys the library
reads (`pagination`, `results[].movie.title`, `results[].showtimes.*[].{startsAt,diffusionVersion,internalId}`),
plus one untrimmed recording:

- `showtimes_W0124.json`: one page, `DUBBED` + `LOCAL`;
- `showtimes_two_pages_p1.json` / `_p2.json`: pagination;
- `showtimes_empty.json`: `error: true`, `no.showtime.error`, `totalPages: 0`;
- `showtimes_null_movie.json`: one `"movie": null` item;
- `showtimes_original.json`: `ORIGINAL` + an unknown `diffusionVersion`.

The tests patch `requests.get` as our override calls it (the client module's `requests`), returning fake
responses (`status_code`, `text`). They must cover:

- the happy path into `DayShowtimes`: titles, versions, sorting, and films without showtimes dropped;
- the empty day gives `films == ()` and no exception;
- pagination: two requests, results merged;
- the `movie: null` item is removed, and the other films are still returned;
- naive `startsAt` becomes aware `Europe/Paris` (one winter date at +01:00, one summer date at +02:00),
  and an aware `startsAt` is converted;
- `diffusionVersion` mapping, including `UNKNOWN` and its single warning;
- the timeout is passed to `requests.get` (`timeout=(10.0, 20.0)` by default, custom values honoured);
- **(D17)** every request sends `headers={"User-Agent": USER_AGENT}`, equal to `"ha-movie-showtimes/0.1"`,
  and **no other header** (assert the exact `headers` mapping, and no `cookies` argument). The requested
  URL ends with `/`: `…/d-<date>/p-1/` and `…/p-2/`, with the slash added once, never doubled. A two-page
  day makes exactly two `requests.get` calls;
- error mapping: 404 → `CinemaNotFoundError`; **(D17) 403 and 429 → `SourceAccessDeniedError`** (also an
  instance of `SourceConnectionError`), with the status in the message; 500 → `SourceConnectionError`
  (not access denied). The pre-D13 names below read through §13.3:
  `requests.Timeout` → `AllocineTimeoutError`; `requests.ConnectionError` → `AllocineConnectionError`;
  non-JSON body → `AllocineParseError`; missing `pagination` / `results` / `title` / `startsAt` and a bad
  datetime → `AllocineParseError`; a bare `Exception` from the library → `AllocineError`; every one chained
  with `__cause__`;
- the asyncio backstop: `_fetch_day_sync` blocks (an `Event.wait`) with `call_timeout=0.05` →
  `AllocineTimeoutError`;
- it runs off the loop: the sync work runs in a thread other than the event loop's (record
  `threading.get_ident()`);
- `normalize_cinema_id`, parametrized:
  - **Bare ids:** `" w0124 "` → `"W0124"`. `""`, `"   "`, `"W0124/../x"`, `"é"`, `"W"` (too short) and an
    11-character id → `InvalidCinemaIdError`.
  - **Accepted URLs, all → `"W0124"`:**
    - `https://www.allocine.fr/seance/salle_gen_csalle=W0124.html`;
    - the same with `http://`, without `www.`, with `m.`, with an upper-case host (`WWW.AlloCine.FR`) and
      with no scheme (`www.allocine.fr/seance/…`, `allocine.fr/seance/…`);
    - with a trailing `/`;
    - with `?utm_source=x` and with `#shwt_date=2026-11-12`;
    - a lower-case id in the URL (`…csalle=w0124.html`);
    - surrounding whitespace.
  - **Rejected URLs:**
    - another host (`https://example.com/seance/salle_gen_csalle=W0124.html`, `https://allocine.fr.evil.com/…`);
    - scheme `ftp://`;
    - a film page (`/film/fichefilm_gen_cfilm=12345.html`);
    - `/seance/salle_gen_csalle=.html` (empty id), `…csalle=W0124.htm`, `…csalle=W01/24.html`, an id
      longer than 10 characters, and the bare host `https://www.allocine.fr/`.
  - `async_get_day` with a bad id raises before any request, and accepts a URL;
- the library contract: the override's parameters match the library's `_get_json_request` **by name,
  kind and default**, compared over `inspect.signature(...).parameters`. Do **not** compare the
  `Signature` objects with `==`: our override has stricter annotations
  (`path: str, url_params: dict[str, Any] | None = None) -> dict[str, Any]`) than the untyped library. A
  library bump that renames, reorders or re-defaults a parameter then fails the test;
- the boundary: no `homeassistant` import in `client/`. A plain `import custom_components.movie_showtimes.client`
  cannot test this: it runs the parent `custom_components/movie_showtimes/__init__.py`, which imports Home
  Assistant. Do one of the following:
  - **(preferred)** in a subprocess (`python -I`), stub the two parent packages first. Put
    `types.ModuleType("custom_components")` and `types.ModuleType("custom_components.movie_showtimes")` in
    `sys.modules`, each with `__path__` set to the real directory. Then import the client package (and
    every submodule, by walking `pkgutil.walk_packages`) and assert that no `homeassistant` or
    `homeassistant.*` module is in `sys.modules`;
  - or an AST scan of every `client/**/*.py` for `import homeassistant…` and `from homeassistant… import`.

### 8.2 Integration — `tests/` excluding the client (Home Assistant, client mocked)

(D13) The registry is patched with the **fake provider** (§13.8):
`patch.dict(registry.PROVIDERS, {"fake": FakeProvider}, clear=True)`. Entries are created with
`data={"source": "fake", "cinema_id": "C1"}` and `unique_id="fake_C1"`. The fake is programmed per date
(a `DayShowtimes` or an exception) and records its calls; "no client call" assertions read that record. Use `freezer`
and set `hass.config.set_time_zone(...)` explicitly.

- **Config flow** (100 %, `config-flow-test-coverage`):
  - (D13) with one registered source, `user` goes straight to the `cinema` form (the first result is
    `step_id == "cinema"`). With two fakes (`"fake"`, `"fake2"`), `user` shows the `source` select; choosing
    `fake2` leads to `cinema` and the entry gets `source == "fake2"`;
  - success: entry created, title = stripped name, `data == {"source": "fake", "cinema_id": "C1"}`,
    `unique_id == "fake_C1"` from input `" c1 "` (the fake normalizes like AlloCiné: strip + upper), and the
    validated day is today in Home Assistant's time zone;
  - the canonical id is what is stored: input `"fake:c1"` (an alternative reference form the fake accepts,
    standing in for a pasted URL) → the same data and unique id. Its id already configured →
    `already_configured`. AlloCiné's URL forms themselves are covered by the provider tests (§8.1);
  - same cinema id under two sources → two entries (`fake_C1`, `fake2_C1`), no collision;
  - an empty day is still a success;
  - **(D22)** a blank or whitespace-only name → title `"Fake Cinemas - C1"`
    (`f"{source.name} - {cinema_id}"`), also from the `fake:c1` form; a typed name is stripped and used;
  - `invalid_cinema_id` from the format check (no provider call) and from `CinemaNotFoundError`;
    **(D17) `access_denied` (`SourceAccessDeniedError`), not `cannot_connect`**;
    `cannot_connect` (`SourceConnectionError` and `SourceTimeoutError`); `unknown` (`SourceParseError`).
    Each error case then recovers to `CREATE_ENTRY`. For `access_denied` and `cannot_connect`, `caplog` holds
    one warning containing the cause (the HTTP status for access denied);
  - `already_configured` abort, with no provider call.
- **Setup / unload:**
  - success → 1 device (identifiers `{(DOMAIN, "fake_C1")}`, name, manufacturer = the fake's
    `source.name`, entry type, configuration URL = the fake's `cinema_url`, and none when it returns
    `None`), 7 sensors with unique ids `fake_C1_day_0` … `fake_C1_day_6` and the expected entity ids,
    `runtime_data` set;
  - (D13) an entry whose `source` is not registered → `ConfigEntryState.SETUP_ERROR` (`ConfigEntryError`,
    translated `unknown_source`), with no retry;
  - nothing stored and the first refresh fails → `ConfigEntryState.SETUP_RETRY`;
  - unload → `NOT_LOADED`. After it, neither a midnight tick nor the time of a pending showtime touches
    the entities or raises: the showtime timer is cancelled by `async_shutdown`.
- **Coordinator** (cases updated by D12):
  - it requests 8 dates, in order, starting today in Home Assistant's time zone. Use a time zone where the
    UTC date differs (e.g. `Pacific/Auckland` at 11:30 UTC);
  - a connection error on day 3 → stops (no call for day 4+), `UpdateFailed`, `last_update_success`
    False. **The sensors keep the previous data and stay available**, and the store is unchanged;
  - **(D19)** after a connection or timeout error, the next attempt comes at +30 min, not before (+29 min →
    no call). If it fails again, another at +30 min, with no new log line. After a success, the next
    refresh is 12 h later. Access denied, not found and parse failures are retried only at +12 h (no call
    at +30 min);
  - **(D19) at setup:** usable stale store + connection error → `LOADED`, stored data shown, next attempt at
    +30 min (`update_interval` one-shot from `last_exception.retry_after`), then 12 h after its success.
    Nothing stored + connection error → `SETUP_RETRY`;
  - not found → same as a connection error (previous data kept, translated `UpdateFailed` logged);
  - **(D17) access denied** on day 1 → stops at once (no call for day 2+), `UpdateFailed` with
    `translation_key == "access_denied"` and the status in the placeholders, previous data kept. **One**
    warning with the status. Two more failing refreshes (12 h ticks) add **no** further warning. After a
    successful refresh, a new refusal logs a warning again. No extra refresh is scheduled before the next
    12 h tick;
  - a parse error on one day → that day keeps its previous `CachedDay` (same `fetched_at`); with no
    previous copy that sensor is unavailable; on every day → `UpdateFailed`, previous data kept;
  - **(D20) parse logging:**
    - a refresh with parse failures on two days → one WARNING (first day) and one DEBUG (second);
    - the next refresh with failures → DEBUG only;
    - a clean refresh, then a failure → WARNING again;
    - a connection-aborted refresh between two failing refreshes does not reset the episode: still DEBUG;
  - **(D21)** a refresh that completes while the entry is being unloaded or removed writes no store
    (patch the store save and assert it is not called; after `async_remove`, the key stays absent from
    `hass_storage`);
  - failures that last past `MAX_DATA_AGE` → each sensor becomes unavailable when its `fetched_at + 48 h`
    passes, through the re-render timer, with no client call;
  - recovery at the next tick → fresh data, new `fetched_at`;
  - a refresh every 12 h: `freezer.tick(12h)` + `async_fire_time_changed` → a second round of calls,
    none before.
- **Midnight rollover:** freeze at 23:59:59 local time, check "Today" = day D. Move to 00:00:00 and fire
  the time change: "Today" shows D+1 data and "In 6 days" shows D+7 data, **with no new client call**.
  D+1's showtimes are all in the future, so "Today" shows all of them right after midnight.
- **Past showtimes** (Home Assistant time zone `Europe/Paris`). Today has Film A at 14:00 and 20:00, and
  Film B at 14:00 only. Freeze at 10:00:
  - at 10:00: state 2;
  - at 14:00 and at **14:14** (move + `async_fire_time_changed`): still state 2, and Film B still listed
    with `vf == ["14:00"]`. The grace period applies;
  - at 14:14:59 still unchanged: the timer fires at start + 15 min, not before;
  - at **14:15:00** → state 1, Film A `vf == ["20:00"]`, Film B gone. One timer fire handles both 14:00
    showtimes. **No new client call**;
  - at 20:14 → state 1; at 20:15 → state 0, `films == []`, still available;
  - no timer is pending afterwards, unless later days hold future showtimes; in that case the next one is
    armed at the earliest `starts_at + 15 min`. Check through `async_fire_time_changed` at that time, with
    the tomorrow sensor unchanged before midnight;
  - a refresh at 15:00 returning the full day again (14:00 included) → the 14:00 showtimes stay hidden, and
    the timer is re-armed for 20:15;
  - a failed refresh keeps the existing timer armed. When it fires, the previous data is still shown
    (D12) and the expired showtime drops out as usual;
  - a showtime at 23:50: visible at 23:59:59, and gone from "Today" at 00:00 (the day changes; the grace
    period does not carry over midnight).
- **`showtimes.py` helpers** (plain unit tests): `remaining_films` with `now` at `starts_at` (kept),
  `starts_at + 14 min` (kept), `starts_at + 14 min 59 s` (kept), `starts_at + 15 min` (dropped) and later
  (dropped); it uses `SHOWTIME_GRACE_PERIOD` (patching the constant changes the cut-off); a film left with
  no showtime is removed; future days are untouched.
  `film_attributes` renders in Home Assistant's zone: the same aware 20:00 Paris showtime is `"20:00"` with
  `Europe/Paris`, `"19:00"` with `Europe/London` and `"14:00"` with `America/New_York` (winter dates);
  order follows the instant.
- **Sensor state and attributes:** the count (remaining films only); `date`; `vf` / `vo` / `vost` split
  (`LOCAL` + `DUBBED` in `vf`, subtitled `ORIGINAL` in `vost`, D2), `accessibility` lists (D30, D31); `other` only when `UNKNOWN` is present; an
  empty day → state `0` and available; consistency: the state always equals `len(films)`. Enrichment keys:
  design doc §9.3.
- **Recorder:** with the `recorder_mock` fixture, `films` is absent from the recorded state attributes,
  and `date` and `fetched_at` are present. **(D29)** Also with a C0159-sized day (≈ 127 KB of `films`): no "exceed maximum size"
  warning.
- **Diagnostics:** a snapshot (syrupy) of `get_diagnostics_for_config_entry`, both after a refresh and
  after a restore from the store (`restored_from_store`, `last_refresh`, per-day `fetched_at`).
- **Persistence and restarts (D12):** §12.8.

## 9. Quality scale summary

Bronze: all rules that apply are met (config-flow, unique-config-entry, test-before-configure,
test-before-setup, runtime-data, has-entity-name, entity-unique-id, appropriate-polling,
config-flow-test-coverage, dependency-transparency). Rules that do not apply: action-setup, docs-actions
(no actions), entity-event-setup.

Silver: config-entry-unloading, entity-unavailable, log-when-unavailable, parallel-updates, test-coverage.
reauthentication-flow is exempt (no auth). action-exceptions does not apply.

Gold, met: devices, diagnostics, entity-translations, exception-translations, icon-translations.
Exempt or not applicable: discovery, dynamic-devices, stale-devices, reconfiguration-flow (deferred),
repair-issues (deferred), entity-category / device-class / disabled-by-default (nothing fits). The
`docs-*` rules belong to the README.

## 10. Decisions (confirmed by the user)

- **D1 — Cinema name:** typed by the user in the config flow. No scraping of the cinema page's `<h1>`.
- **D2 — VF / VO / VOST (revised):** `vf` = `DUBBED` + `LOCAL`; `vost` = `ORIGINAL` with classic subtitles; `vo` =
  `ORIGINAL` without (or unknown); `other` = `UNKNOWN`. The labels depend on the cinema: French films are `LOCAL`
  (W7520), `DUBBED` (C0159) or `ORIGINAL` (_La Gradiva_, W0124, in `original_st`). So the AlloCiné provider maps
  **`ORIGINAL` of a film whose `languages` are exactly `["FRENCH"]` to `LOCAL`** (user decision: co-productions
  such as `["FRENCH","ITALIAN"]` are not reclassified), hence `vf`. Classic subtitles = a `*_st` list, or the tag
  `Showtime.Accessibility.Subtitled` (W7520, W0124), or a `Localization.Subtitle.*` tag (C0159: VOST in `original`);
  never an `*_sme` list (SME is separate, D30). Design doc §4.4. (Was: `vo` = every `ORIGINAL`.)
- **D3 — 8 days fetched** for 7 sensors (one buffer day, 16 requests a day per cinema).
- **D4 — Pasted URL:** the id field also accepts an allocine.fr cinema page URL, parsed as in §3.3.
- **D5 — Past showtimes are dropped:** a showtime is no longer shown once its grace period after the start
  has ended (D11). A film with no showtime left drops out of the list and the count. The sensors re-render
  on time with no network call (§4.4).
- **D6 — `HH:MM` in Home Assistant's time zone:** the client parses the source's naive times as aware
  `Europe/Paris`, and the Home Assistant side converts them for display.
- **D7 — Pins:** `allocine-seances==0.0.14` in `[project].dependencies` of `pyproject.toml` and in
  `manifest.json` `requirements`. No pin for `beautifulsoup4`.
- **D8 — Library override:** overriding the private `_get_json_request` is approved, guarded by the
  signature test (§8.1).
- **D9 — URL forms:** only the bare id and the `…/seance/salle_gen_csalle=<ID>.html` URL are accepted
  (with `http`/`https`, an optional `www.`/`m.`, query and fragment ignored). No other URL form.
- **D10 — Date buckets:** showtimes stay grouped by their AlloCiné (French) date. Only the displayed time is
  converted to Home Assistant's time zone, so with a zone far from Paris a showtime can display as an
  early-morning `HH:MM` on its AlloCiné date's sensor. Nothing is re-bucketed.
- **D11 — Grace period:** `SHOWTIME_GRACE_PERIOD = timedelta(minutes=15)` in `const.py`. A showtime stays
  visible while `starts_at + SHOWTIME_GRACE_PERIOD > now`, and the re-render timer is armed at the earliest
  `starts_at + SHOWTIME_GRACE_PERIOD` after now. It does not carry over midnight.
- **D12 — Survive restarts without needless calls:** the last good data is persisted per config entry with
  `homeassistant.helpers.storage.Store`. At setup, fresh stored data is used with no request, and the next
  refresh is scheduled from the stored refresh time. Stale stored data triggers a refresh, and if that
  refresh fails the stored data is served instead of `ConfigEntryNotReady`. Design: §12.
- **D13 — Source abstraction:** the integration depends only on a source-neutral `ShowtimesProvider` (an ABC
  in `client/provider.py`), neutral models and neutral exceptions. AlloCiné is one provider
  (`client/providers/allocine.py`), selected through a static registry by `entry.data["source"]`. Unique
  ids, device identifiers and the store are namespaced by source from v1 (`allocine_W0124`). With a single
  source, the config flow skips the source choice. Design and refactoring delta: §13.
- **D14 — Data age:** `MAX_DATA_AGE = timedelta(hours=48)` per day, as designed in §12.5.
- **D15 — Attribute names:** `vf`, `vo`, `vost` (D26), `other` and `accessibility.{pmr, sme, audio_description}` (D30, D31) are kept for every source. A future source maps
  its own notions onto `ShowtimeVersion` and `Showtime.subtitled` (§13.3), which map onto these keys.
- **D16 — Global refresh settings:** `UPDATE_INTERVAL` (12 h) and `DAYS_FETCHED` (8) stay global constants
  in `const.py`. `SourceInfo` does not carry an interval or a horizon.
- **D17 — Honest identity, canonical URL, refusals reported:**
  - the AlloCiné override sends `User-Agent: ha-movie-showtimes/0.1` (constant `USER_AGENT`) and nothing
    else meant to look like a browser: no evasion of any kind;
  - it requests the trailing-slash URL, so there is no 301 per call;
  - HTTP 403 / 429 → `SourceAccessDeniedError` (a subclass of `SourceConnectionError`). The flow error is
    `access_denied`. `UpdateFailed` uses `access_denied` with the status, logged once per refusal episode;
  - the generic connection path also logs its cause in the flow.

  Risks: §2 "Risks and known limitations".

- **D18 — Age-limit semantics:** a day is usable while `now < fetched_at + MAX_DATA_AGE` (strict). The
  sensor, `async_initialize`, the partial-refresh merge and the re-render timer share one helper
  (`is_day_usable` / `day_data_expiry`, §3.5). The timer armed at the expiry therefore turns the sensor
  unavailable at exactly 48 h. It fixes the `<=` vs timer mismatch.
- **D19 — Early retry after a transient connection error:** `RETRY_AFTER_CONNECTION_ERROR = timedelta(minutes=30)`
  in `const.py`. A `SourceConnectionError` or `SourceTimeoutError` raises `UpdateFailed(retry_after=1800)`,
  so the next attempt is 30 min later, repeated until a success, then 12 h again.
  - It does not apply to `SourceAccessDeniedError` (caught first), `CinemaNotFoundError` or parse
    failures: those wait 12 h.
  - At setup HA ignores `retry_after`. With usable stored data, `async_initialize` applies
    `last_exception.retry_after` as a one-shot `update_interval`. With nothing stored, it is
    `ConfigEntryNotReady` as before.
  - Retries add no log line (§4.3).
- **D20 — Parse failures logged once per episode:** WARNING for the first failing day of a refresh when the
  previous refresh had none, DEBUG otherwise. It is reset by a clean refresh; a refresh aborted by a
  connection error does not reset it (§4.3).
- **D21 — No store write outside `SETUP_IN_PROGRESS` / `LOADED`:** a refresh finishing during unload or
  removal does not recreate the deleted file (§12.4).
- **D22 — Optional name:** a blank name gives the title `f"{SourceInfo.name} - {cinema_id}"` (e.g.
  `AlloCiné - W0124`), also for a pasted URL. `name_required` is removed from the flow and the strings (§4.1).
- **D23 — Past days dropped at restore:** days earlier than today (HA time zone) are removed from the
  restored snapshot before the usability check and before the timer is armed (§12.3). The 48 h rule is
  `showtimes.day_data_expiry` / `showtimes.is_day_usable` (D18), shared by the sensor, the restore, the
  stale-day merge and the timer.

Film enrichment (design: `docs/design/film-enrichment.md`, revision 4; evidence: three real captures, W0124,
C0159 and W7520, design doc §0; D24–D31 are user decisions except where noted):

- **D24 — Enrichment from the same document, no extra request:** each film and showtime carries what the
  showtimes JSON already holds, every free field included (release date, visa, `type`, all true boolean `flags`,
  `userReview.count`, `stats.metric`, `synopsisFull` as is, `comfort` …; list in design doc §1.2), except
  `timeBeforeStart` (unreliable) and `editorialReviews` (dropped). Formats are the source's codes verbatim
  (`DIGITAL`, `IMAX`, `F_3D`, `SCREEN_X`, `PLF`, `E_4DX`), never translated. One booking link per showtime: a
  DESKTOP entry, provider `default` first, then `relay`, then any other (design doc §4.6). Raw `tags` are never
  exposed; accessibility is derived (D30, D31). No `get_movies`, `get_cinema`, film page or `nextDate`: the
  request count is unchanged.
- **D25 — Our own pagination instead of `get_showtime`:** the provider requests
  `URLs.showtime_url(id, date, n)` through our `_get_json_request` override for `n` in `1 … totalPages`
  (`pagination.page` is a string), checks each page number, caps at 20 pages, keeps no state on the instance, and
  parses `results[].movie` and the six showtime lists itself, de-duplicated by `internalId`. Same canonical URL,
  same honest `User-Agent` (D17), no evasion. `URLs.showtime_url` gets a signature guard (design doc §4.2).
  Verified on 3-page (C0159) and 2-page (W7520) real days. A `monotonic()` deadline (`call_timeout`) is checked
  before every page, the first included (`SourceTimeoutError`), because the executor thread outlives the `asyncio`
  timeout.
- **D26 — `vost` key and a separate classic-subtitles axis** (D2 revised): `ShowtimeVersion` keeps its four values;
  `Showtime.subtitled` (classic subtitles only) is independent; the mapping to `vf` / `vo` / `vost` / `other` is on
  the HA side (design doc §4.4, §6.2). _(Architect's choice of structure, on the user's VO / VOST decision.)_
- **D27 — Store: film catalogue, purge by construction, no migration:** film details are stored once in a
  catalogue keyed by film id, shared by the days, which reference the id only. At every save the catalogue is
  rebuilt from the films of the kept days (past and too-old days removed first), so it never grows; refetched
  details replace older ones; a failed day keeps its copy and its films. At load, a reference without an entry
  gives a film without details (debug), an unreferenced entry is ignored. Nothing is released, so the schema
  changes with **no version bump and no migration code**: an older dev store is rejected as malformed and
  refetched (design doc §5.2).
- **D28 — Enrichment is optional and never fails a day:** every new model field has a default (the fake provider
  and other sources change nothing); an unreadable enrichment or accessibility field becomes `None` / `()` with a
  debug line and **never** raises `SourceParseError`. Only the v1 required fields (title, showtimes, `startsAt`,
  pagination) can fail a day. Unexpected type → one DEBUG line; `null` / absent → silent; per-showtime keys logged
  once per day (design doc, implementation notes).
- **D29 — Attribute size:** no cap (user decision). Every new key lives inside `films` (already unrecorded); heavy
  keys (`synopsis`, `synopsis_full`, `cast`, `credits`, `related_tags`, the per-showtime list with booking links)
  sit under each film's `details`; nothing new at the sensor's top level. The recorder is not affected (§5.3,
  design doc §7; measured up to ≈ 127 KB of `films` per sensor).
- **D30 — Accessibility: PMR and SME** (user decision, reversing the first exclusion). Per film,
  `accessibility.pmr` and `accessibility.sme` list the `HH:MM` of the matching showtimes (always present, possibly
  empty), per showtime `pmr` / `sme` flags. PMR = `service` contains `DISABLED_ACCESS` or the tag
  `Theater.Service.DisabledAccess` (they agree on all 434 showtimes seen); `Showtime.Accessibility.Accessible` is
  not PMR and is not used. SME = the `*_sme` lists only: never seen filled, so tested on invented data only.
- **D31 — Audio description** (user decision): a third list `accessibility.audio_description` (per showtime
  `audio_description`) from the tag `Showtime.Accessibility.Greta` (W7520: 16 showtimes, 6 films). "Greta = audio
  description" is an **assumption**, not confirmed by AlloCiné. The `relay` URL's `code=` (`AUDIO`, `SME`,
  `GRETA`) is not used: redundant at W7520, unreliable at C0159 (design doc §4.7).

**Phase 1 supersedes D35, D39-D41: card restarted from the reference copy; D32 delivery and D33 binding stay.**
Lovelace card (design: `docs/design/lovelace-card.md`, revision 3; delivery, one cinema per card, local search + day
selector, i18n, the fork of the reference card and per-line field choice are user decisions; the rest are the
architect's choices on them). Revision 3 status of each entry: D32, D33, D36, D37, D38 **kept**; D34 **kept**
(reference look); D35 **partly superseded** by D40 / D41.

- **D32 — Card served and registered by the integration:** one ES module,
  `custom_components/movie_showtimes/frontend/movie-showtimes-card.js`, served at
  `/movie_showtimes/movie-showtimes-card.js` (`StaticPathConfig`, cache headers on) and loaded on every frontend
  page with `frontend.add_extra_js_url(hass, url + "?v=<sha256[:8] of the file>")`. No Lovelace resource, so it
  works with storage and `resource_mode: yaml` dashboards alike and leaves nothing to clean up. Registered once per
  run from `async_setup` (+ `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`), never from
  `async_setup_entry`. `manifest.json` gets `"after_dependencies": ["frontend", "http"]`, **not** `dependencies`
  (CI has no `home-assistant-frontend` package; without those components the card is skipped with a debug line and
  the sensors work). `hacs.json`: only `"homeassistant": "2026.10.0"` added; category unchanged.
- **D33 — One cinema per card, bound by device:** `device_id` from a device selector filtered on
  `movie_showtimes` (YAML may give `entity`, any of the cinema's sensors, instead). The 7 day sensors are resolved in
  the browser from `hass.entities` by `device_id`, `platform` and `translation_key` (`today`, `tomorrow`,
  `day_N`), never by entity id or unique id, with no request. A Python test pins those translation keys.
- **D34 — Day selector and search, local only:** chips over the resolved sensors, selection kept by date (stays on
  the chosen day across midnight, falls back to today when it is past). The search is a substring AND match,
  case- and accent-insensitive, over `title`, `original_title`, `genres`, `directors`, `details.cast`; no request,
  render debounced by 100 ms, nothing persisted. (Revision 3: drawn with the reference's search bar markup and CSS;
  the reference's own matching and catalogue search are not kept.)
- **D35 — Field catalogue** (kept): the catalogue (24 keys: `title` … `url`) is taken from the real `films[]`
  attributes; an absent value renders nothing; unknown field keys are dropped with a warning. Source HTML
  (`synopsis_full`) is turned into text, never injected; links only `http(s)`. _Superseded in revision 3:_ the
  `rows: [{fields, label?, icon?}]` model (→ D40) and `show_poster` (→ D41).
- **D36 — The card has no clock and re-renders by identity:** past showtimes and the midnight rollover come from the
  sensors (D5, D11, §4.4); the card renders the state as it is, compares its sensors' state objects by identity
  (no serialisation of the ≈ 127 KB `films`), and handles unavailable sensors, closed days (valid data) and a
  missing cinema with translated messages.
- **D37 — Card strings in the module:** `en` and `fr` dictionaries with identical keys, language from
  `hass.locale.language` (base-language then English fallback); times shown verbatim (`HH:MM`, HA time zone, D6);
  source values never translated.
- **D38 — JS tests with Node's built-in runner, run from pytest:** no npm dependency, no `package.json`; the
  module's pure functions are exported and tested (`tests/card/*.mjs`), the DOM classes are guarded so the module
  loads in Node. `tests/card/test_card_js.py` runs `node --check`, `node --test` and a backend/card contract on a
  snapshot of real sensor states; it skips locally without Node ≥ 22 and fails in CI. Template gaps (workflow path
  filters ignore `.js` / `.mjs`; `scripts/lint` Prettier globs omit JS) are flagged for an upstream change.
  (Revision 3: the contract and the exports it uses keep their names and shapes; `card.test.mjs` adapted and a
  source-hygiene test added: no request API, `innerHTML` only from upper-case constants, no BetaSeries leftovers.)
  In revision 3 the card's layout bullet of D36 (getCardSize / grid, own CSS) is replaced by the reference's
  formulas and stylesheet (D39); the identity re-render, no clock and messages stay.
- **D39 — Fork of the reference card** (user decision): the file is the reference
  `bastgau/ha-betaseries` `card/upcoming-media-card.js` (MIT, itself from `custom-cards/upcoming-media-card`, MIT),
  forked once and not tracked afterwards; its look, layout options (`max`, `collapse`, `overflow`, `overflow_fit`,
  `max_columns`) and appearance options (`corner_radius`, `line_size`, `line_color`, `accent_color`, `border_color`,
  `flag_color`, `flag`, `enable_transparency`, `box_shadows`, `text_shadows`, `disable_hyperlinks`) are kept; every
  BetaSeries part (watched, add / remove, catalogue, `device_betaseries`), trailers, filters, dates / clock and
  `$token` templates are removed. **Kept on the user's request (revision 3.1):** tooltips (`enable_tooltips`,
  `tooltip_delay`, default 500 ms: the synopsis, a node of the card's own shadow root, text only, cleaned up on
  re-render and disconnect) and sorting (`sort_by` over `title` default / `first_showtime` / `runtime` /
  `user_rating` / `press_rating`, `sort_ascending` default `true`, a film with no value last whatever the direction). Rendered into a shadow root with static `mst-` classes, a
  constant stylesheet fed by `--mst-*` custom properties set with `style.setProperty` (never CSS built from config),
  DOM built with `textContent` (the reference's `innerHTML` of decoded source text is not kept). Element names stay
  `movie-showtimes-card` / `movie-showtimes-card-editor`. Both MIT notices and the forked commit are in the JS
  file's header (the only part shipped); README "Credits". The file is Prettier-formatted and passes the same
  minimal ESLint config, with only the browser globals it uses added.
- **D40 — Lines, configurable one by one** (user decision; replaces revision 2's rows and the reference's
  `title_text` / `line1_text` … `line4_text`): `lines: [{fields: [...], size?, color?}]` (bare lists accepted), any
  number; line 0 has the reference's title treatment; size `large` 18 px / `medium` 14 px / `small` 12 px, default
  by position as the reference (0 large, 1 medium, then `line_size` or small); colour: line, `line_color`, style
  default. Inline fields joined by " · " and ellipsised; block fields wrap. A line with nothing to render is not
  drawn. Default lines = title / runtime · genres · certificate / showtimes. Edited with an object selector
  (fields, size, colour) in an expandable "Lines" section.
- **D41 — `image_style`: `none` (default), `poster`, `fanart`:** keeps the user's "posters opt-in" decision (the only
  outside request the card can cause, the browser loading posters from AlloCiné's CDN). `none` is the reference's
  poster item without its image column (frame, colours, flag, lines kept), not an empty poster column; `fanart` uses
  the poster cropped (there is no backdrop in the data). Films without a poster fall back to `none`.

## 11. Open questions for the user

D1–D23: none left. Film enrichment: the remaining questions (Q2, Q8–Q11, Q13–Q16, Q18) are in
`docs/design/film-enrichment.md` §11. Answered by the user: Q1 (editorial reviews dropped), Q3 (every free field),
Q4 (codes), Q5 (exactly `["FRENCH"]`), Q6 (one DESKTOP link), Q7 (accessibility in scope, SME apart from `vost`),
Greta (D31), Q17 (fixtures indented).

Lovelace card (D32–D41): nothing blocking. Decided by the user: fork the reference card (D39), lines configurable
one by one (D40), 24 h times only, search fields as D34, posters opt-in (kept as `image_style: none` by default, D41:
the one default worth confirming). Listed in `docs/design/lovelace-card.md` §12.

## 12. Persistence and restarts (D12) — implementation delta

This section is the whole D12 change. The developer can apply it on top of the design above. Every other
place it touches is tagged **(D12)** in the text: §3 (module tree, `const.py`, `CachedDay`,
`ShowtimesData`, coordinator signature, `async_initialize`, `async_remove_entry`), §4.3, §4.4 (timer),
§4.5, §5.3 (availability, `fetched_at`), §6, §7, §8.2 (updated cases), §10.

### 12.1 Goal

A Home Assistant restart, or a reload of the entry, must not cost requests to allocine.fr when the data
in hand is still fresh. A restart while allocine.fr is down must not lose good data. Both follow from
persisting the last good data and treating it as the source of truth until the normal 12 h refresh is due.

### 12.2 The store (`store.py`)

```python
class ShowtimesStore(Store[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        # super().__init__(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}",
        #                  minor_version=STORAGE_MINOR_VERSION, atomic_writes=True)

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def async_load_snapshot(self, source: SourceInfo, cinema_id: str) -> StoredSnapshot | None: ...  # (D13) source
    async def async_save_snapshot(self, source: SourceInfo, cinema_id: str, snapshot: StoredSnapshot) -> None: ...

@dataclass(frozen=True, slots=True, kw_only=True)
class StoredSnapshot:
    last_refresh: datetime                 # aware UTC
    days: dict[date, CachedDay]

def snapshot_to_dict(source_id: str, cinema_id: str, snapshot: StoredSnapshot) -> dict[str, Any]: ...
def snapshot_from_dict(
    raw: Mapping[str, Any], *, source_id: str, cinema_id: str, source_tz: tzinfo   # (D13) was paris_tz
) -> StoredSnapshot:
    """Raises ValueError on any missing key, wrong type, bad value or broken invariant."""
```

- **One store per config entry.** Key `movie_showtimes.<entry_id>`, so the file is
  `<config>/.storage/movie_showtimes.<entry_id>`. The key uses the entry id, not the cinema id, so it goes
  away with the entry and never collides. Atomic writes, so a power cut cannot leave a half-written file.
  The store is not private: it holds no secrets.
- **Version:** `STORAGE_VERSION = 1`, `STORAGE_MINOR_VERSION = 1`.
- **(D27) The format below is the v1 core. It changes directly, with no version bump and no migration
  (nothing released):** a required top-level `films` catalogue keyed by film id, and per film `ref`, per
  showtime the optional enrichment and accessibility keys. Rebuilt from the kept days at every save (purge), tolerant of a
  reference without an entry. Full format, purge order and load rules: design doc §5.2. Function
  `unify_film_details` (same module) is called by the coordinator before saving (design doc §5.1).
- **Format, version 1** (inside Store's own `{"version", "minor_version", "key", "data"}` envelope):

  ```json
  {
    "source": "allocine",
    "cinema_id": "W0124",
    "last_refresh": "2026-11-10T06:00:12.345678+00:00",
    "days": [
      {
        "date": "2026-11-10",
        "fetched_at": "2026-11-10T06:00:12.345678+00:00",
        "films": [
          {
            "title": "Film A",
            "showtimes": [
              { "starts_at": "2026-11-10T14:00:00+01:00", "version": "dubbed" }
            ]
          }
        ]
      }
    ]
  }
  ```

- **Serialising:**
  - dates as `date.isoformat()`;
  - aware datetimes as `datetime.isoformat()`, so the offset is always written. `fetched_at` and
    `last_refresh` come from `dt_util.utcnow()` and are written in UTC (`+00:00`). `starts_at` keeps its
    Paris offset (`+01:00` in winter, `+02:00` in summer);
  - `version` as `ShowtimeVersion.value`;
  - days as a list sorted by date, because JSON keys are strings and a list is explicit. Films and
    showtimes keep their model order.

  Only days with `date >= today` (HA time zone) are written.

- **Restoring** (`snapshot_from_dict`), strict:
  - `source` **(D13)** and `cinema_id` must equal the entry's;
  - `date.fromisoformat` for dates;
  - `datetime.fromisoformat` for datetimes. A naive datetime → `ValueError`;
  - `fetched_at` and `last_refresh` → `.astimezone(UTC)`;
  - `starts_at` → `.astimezone(source_tz)`, which brings back the source's `ZoneInfo` that the provider's
    models promise (`Europe/Paris` for AlloCiné);
  - `ShowtimeVersion(value)`, so an unknown value is a `ValueError`;
  - a film with no showtimes, or an empty title → `ValueError`.

  Any `KeyError` or `TypeError` is re-raised as `ValueError`. `source_tz` comes from
  `await dt_util.async_get_time_zone(provider.source.time_zone)`, which is async-safe; building a `ZoneInfo`
  on the loop may read tzdata. The store never names AlloCiné (D13). **Any error rejects the whole snapshot.** It is a cache, and refetching costs 8
  requests, so partial recovery is not worth its code.

- **Migration (`_async_migrate_func`):** (unchanged; D27 deliberately does not use it, since nothing is released.
  After the first release, a schema change follows these rules.)
  - same major, older minor → return `old_data` unchanged. Rule for future minors: only add optional keys,
    and the reader ignores unknown keys;
  - older major → return `{}`, which the loader treats as nothing stored. Store then saves the migrated
    `{}`, and the next successful refresh overwrites it;
  - newer major (a downgrade of the integration) → Home Assistant raises `UnsupportedStorageVersionError`
    before calling the migration. `async_load_snapshot` catches it.
- **`async_load_snapshot`** returns `None` (and logs a warning, except for "no file") in each of these cases:
  - no file;
  - `{}`;
  - a `HomeAssistantError` from `async_load`, which includes `UnsupportedStorageVersionError`;
  - an `OSError`;
  - a `ValueError` from `snapshot_from_dict`.

  A file that is not valid JSON is handled by Home Assistant itself (HA 2026.10.1, `storage.py`): it
  renames the file `….corrupt.<time>`, raises its own `storage_corruption` repair issue and returns `None`.
  For us that is "nothing stored".

- **`async_save_snapshot`** is `await self.async_save(snapshot_to_dict(…))`. Store logs write errors
  itself and does not raise them, so a failed write never fails a refresh.
- **Removal:** `async_remove_entry` → `await ShowtimesStore(hass, entry.entry_id).async_remove()`
  (§3.5). An unload alone (disable, reload, restart) keeps the file. That is the point.

### 12.3 Setup (`MovieShowtimesCoordinator.async_initialize`)

```python
async def async_initialize(self) -> None:
    now = dt_util.utcnow()
    today = dt_util.now().date()
    snapshot = await self._store.async_load_snapshot(self._provider.source, self.cinema_id)
    if snapshot is not None:   # (D23) drop past days first, so neither the check nor the timer sees them
        snapshot = StoredSnapshot(last_refresh=snapshot.last_refresh,
                                  days={d: c for d, c in snapshot.days.items() if d >= today})
    usable = snapshot is not None and any(is_day_usable(c, now) for c in snapshot.days.values())   # (D18)
    if usable:
        self.async_set_updated_data(snapshot.days)   # no listeners yet: no scheduling, no render
        self.last_refresh = snapshot.last_refresh
        self.restored_from_store = True
        self._async_schedule_next_showtime(self.data)
        age = now - snapshot.last_refresh
        if timedelta(0) <= age < UPDATE_INTERVAL:   # fresh
            self.update_interval = UPDATE_INTERVAL - age   # one-shot, see §12.6
            return                                         # NO request to allocine.fr
    try:
        await self.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        if not usable:
            raise                                  # nothing usable stored → setup retry, as before
        if isinstance(self.last_exception, UpdateFailed) and self.last_exception.retry_after is not None:
            # (D19) HA ignores retry_after during the first refresh: apply it as a one-shot interval
            self.update_interval = timedelta(seconds=self.last_exception.retry_after)
        _LOGGER.warning(...)                       # "%s is unreachable, showing the showtimes fetched at %s"
```

| Store at setup                                                                            | Requests                | Result                                                                                                                          |
| ----------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| fresh: `0 ≤ age < 12 h`, at least one usable day                                          | **none**                | Loaded with the stored data. Next refresh at `last_refresh + 12 h`.                                                             |
| stale or partly usable, refresh succeeds                                                  | 8                       | Loaded with fresh data, store rewritten.                                                                                        |
| usable but stale, refresh fails                                                           | until the first failure | Loaded with the stored data (warning logged). Next attempt in 30 min after a connection or timeout error (D19), otherwise 12 h. |
| nothing usable (none, invalid, all days past or older than `MAX_DATA_AGE`), refresh fails | until the first failure | `ConfigEntryNotReady` → `SETUP_RETRY`.                                                                                          |

- If `age < 0`, the clock has gone back, and the snapshot is treated as stale (refresh).
- A failing first refresh leaves `self.data` alone (the `DataUpdateCoordinator` behaviour), so the
  restored snapshot stays in place when the exception is caught.
- `async_set_updated_data` sets `last_update_success = True`, which is right: the restored data is good
  data. After a failed stale refresh it is `False`. The sensors do not depend on it (§5.3).

### 12.4 Saving, and partial or failed refreshes

- **When:** at the end of every successful `_async_update_data`, which means every day was fetched or
  some days failed to parse but not all. It sets `last_refresh = now`, builds the result, and
  `await self._store.async_save_snapshot(...)` before returning. That is two writes a day, each a few KB.
  **(D21) Only while `config_entry.state` is `SETUP_IN_PROGRESS` or `LOADED`.** A refresh that finishes
  while the entry is unloading or being removed must not write, otherwise it would recreate the file that
  `async_remove_entry` has just deleted.
- **Partial result:** the successful days get `CachedDay(showtimes, fetched_at=now)`. A day that failed to
  parse keeps its previous `CachedDay` from `self.data` (from memory, which equals the store), **with its
  old `fetched_at`**, if it is in range and `is_day_usable(cached, now)` (D18). Otherwise it is absent. So
  a partial result never removes a good day from the store, and never makes an old day look fresh. The
  saved snapshot is exactly the in-memory result. **(D27)** The merged result then goes through
  `unify_film_details`, so a kept day's films take the freshly fetched details of the same film; memory and
  store still hold the same data.
- **Failed refresh** (`UpdateFailed`: connection, timeout, not found, every day unparsable): nothing is
  written. Memory and store keep the last good snapshot, and the sensors keep showing it (§12.5).
- The only data ever written is data that is also served. The store and the memory never diverge.

### 12.5 How stale data may be shown

The data is keyed by real date, so being old does not make it wrong in itself. The checks happen at
render time:

- **Past days** fall away by themselves: a sensor only reads its own date.
- **Today's past showtimes** are filtered against the current time (D5/D11). A setup at 14:20 does not
  show the 14:00 showtime.
- **Coverage:** a day absent from the data makes **its sensor unavailable, not `0`**. For example, a
  snapshot fetched on day D covers D … D+7. On D+1 all 7 sensors are covered, thanks to the buffer day. On
  D+2, "In 6 days" (D+8) is unavailable.
- **Age:** a day is shown only while `now < fetched_at + MAX_DATA_AGE` (48 h, decisions D14 and D18:
  strict, through `is_day_usable`, §3.5). Cinema
  programmes are published about a week ahead and change little, mostly on Wednesdays with new releases,
  so data up to two days old is still right in practice. Beyond that, unavailable is more honest. The
  re-render timer includes `day_data_expiry(cached)`, the same instant from which `is_day_usable` is
  `False`. When it fires, the sensor turns unavailable, on time and with no request.
- **Same rule everywhere:** after a restart, after a failed refresh during the day, or both. Hence
  `available` ignores `last_update_success` (§5.3). Otherwise a restart during an outage would show data
  while the same outage without a restart would hide it.
- **What the user sees:** the sensors as usual, plus the `fetched_at` attribute on each sensor (the age of
  that day's data). Diagnostics add `last_refresh`, `restored_from_store` and `data_age_seconds`. The
  coordinator still logs once when refreshes start failing and once when they recover. No repair issue:
  the data either shows correctly or the sensor is unavailable.

### 12.6 Scheduling the next refresh from the stored time

`DataUpdateCoordinator` schedules its next refresh `update_interval` after the moment the first listener
subscribes (`async_add_listener` → `_schedule_refresh`, HA 2026.10.1). On the fresh path,
`async_initialize` therefore sets the public `self.update_interval = UPDATE_INTERVAL - age` before the
platforms are forwarded. The first sensor's subscription then schedules the refresh at
`last_refresh + 12 h`. The **first statement** of `_async_update_data` is
`self.update_interval = UPDATE_INTERVAL`, so every later schedule is 12 h again, whether that refresh
succeeds or fails. A restart therefore never shifts the twice-a-day rhythm and never adds a refresh.

### 12.7 Nothing time-dependent lives only in memory

| Time-dependent thing           | Survives a restart because                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------------ |
| next refresh                   | derived from the persisted `last_refresh` (§12.6)                                          |
| midnight rollover              | the listener is registered again in every `async_setup_entry` (§4.4)                       |
| showtime / age re-render timer | armed again from `data` in `async_initialize` (restore) or at the end of the setup refresh |
| which showtimes are past       | computed from `now` at each render                                                         |
| availability by age            | computed from the persisted per-day `fetched_at` and `now`                                 |

A restart at any moment therefore gives the same sensor output as no restart.

### 12.8 Tests (integration scope; `store.py` is on the Home Assistant side)

Use a `MockConfigEntry` with a fixed `entry_id`. Pre-fill the store with
`hass_storage[f"movie_showtimes.{entry_id}"] = {"version": 1, "minor_version": 1, "key": …, "data": …}`,
and read it back from `hass_storage` after writes. Use `freezer` with `Europe/Paris`.

- **Fresh** (stored 2 h ago, covering D … D+7): setup → `LOADED`, **`async_get_day` never called**,
  sensors show the stored data, `fetched_at` = stored. At restart + 9 h 59 min, still no call. At
  restart + 10 h (= `last_refresh + 12 h`) + `async_fire_time_changed`: 8 calls. The following refresh
  comes 12 h after that.
- **Stale** (stored 13 h ago): 8 calls at setup, sensors show the new data, store rewritten with the new
  `last_refresh`.
- **Stale + allocine.fr down** (connection error): `LOADED`, not `SETUP_RETRY`. Stored data shown,
  warning logged, one call only (stop at first failure). The next attempt is 30 min later (D19), and
  12 h after that if it succeeds. **(D23)** a store whose only usable days are in the past (e.g. fetched
  yesterday, all dates < today) → treated as nothing usable; the past days are never restored.
- **Too old + down** (every stored day older than 48 h, or all days in the past): `SETUP_RETRY`.
- **Nothing stored + down:** `SETUP_RETRY`.
- **Store written after a successful refresh:** `hass_storage` holds the exact JSON. Check dates,
  `source`, `fetched_at` / `last_refresh` in `+00:00`, `starts_at` in `+01:00` (winter) and `+02:00` (summer), and
  the version values. Only days ≥ today are written. **Round trip:** reload the entry, and the restored
  `DayShowtimes` equal the originals with `starts_at.tzinfo == ZoneInfo("Europe/Paris")`, with no call.
- **Partial refresh:** stored D+3, then a refresh where D+3 fails to parse → D+3 keeps the stored copy
  and its old `fetched_at`, in memory and in the store. The other days are fresh.
- **Failed refresh** during the day: the store content is unchanged, and the sensors are still available.
- **Store removed with the entry:** `hass.config_entries.async_remove(entry_id)` → the key is gone from
  `hass_storage`. Removing with no file raises nothing. Unload or reload keeps the store.
- **Invalid store** → treated as nothing stored (refresh at setup, no crash), parametrized:
  - missing `days`;
  - a bad date;
  - a naive datetime;
  - an unknown `version` value;
  - another `cinema_id`, or another `source` (D13), or no `source`;
  - a film with no showtimes;
  - `data == {}`.

  An undecodable JSON file is Home Assistant's own path (rename and repair, tested upstream), and
  `hass_storage` cannot represent it.

- **Versions:**
  - an older minor (`minor_version: 0`) → loaded as is;
  - an older major (`version: 0`) → nothing stored;
  - a newer major (`version: 2`) → `UnsupportedStorageVersionError` caught, nothing stored, and the next
    save writes version 1.
- **Grace period at setup:** a fresh store with a 14:00 and a 14:10 showtime today, setup at **14:20**. The
  14:00 one is not shown. The 14:10 one is shown until 14:25 (the timer is armed from the restored data),
  then dropped, with no call.
- **Coverage:** a fresh store without D+4 → "In 4 days" unavailable (not `0`), the others available.
- **Age expiry after a restore** (D18 regression test): stored 40 h ago + down → shown. At +7 h 59 min 59 s,
  still available. At exactly +8 h (age 48 h), moved there with `async_fire_time_changed` only, so that the
  timer is the only trigger: **unavailable**, with no call and no timer left armed for that day.
  `is_day_usable` unit tests: at `expiry - 1 s` → `True`; at `expiry` → `False`.
- **Midnight after a restore:** the rollover works with no call.
- **Clock skew:** `last_refresh` in the future → treated as stale → refresh at setup.
- **`snapshot_to_dict` / `snapshot_from_dict`** (plain unit tests): a round trip, and each rejection
  above raising `ValueError`.
- **(D27) Film catalogue:** film gone from every day removed; film on two days kept while one day remains; a
  failed day keeps its films' details; refetched details replace the old; orphan reference tolerated; unreferenced
  entry ignored; a store without `films` rejected; the store does not grow over 10 refreshes. Details: design doc
  §9.3.

## 13. Source abstraction (D13) — refactoring delta

This section is the whole D13 change, designed from the code already written for D1–D11 (`client/api.py`,
`client/models.py`, `client/exceptions.py`, and the Home Assistant modules that import `AllocineClient`).
Other places it touches are tagged **(D13)**: §3 (tree, note on §3.1–3.3, `const.py`, coordinator,
`__init__.py`), §4.1, §4.2, §4.3, §5.1, §5.2, §6, §7, §8, §12.2, §10, §11. D12 (§12) is written against the
neutral names, so the two deltas can be applied in either order. Applying D13 first is simpler.

### 13.1 Goal and scope

- **In:** the Home Assistant side (`__init__`, `config_flow`, `coordinator`, `entity`, `sensor`,
  `showtimes`, `diagnostics`, `store`) depends only on the neutral API exported by `client/__init__.py`.
  AlloCiné is one provider behind it. Adding a source later means adding a provider module, one registry
  line, its translations and its requirement, plus a config-flow step only if its reference does not fit
  one text field (§13.5). The coordinator and the entities are not touched.
- **v1 ships one provider:** AlloCiné. Its behaviour, D1–D12, is unchanged.
- **Out (deliberately):**
  - several sources for one cinema, and merging or deduplicating showtimes across sources;
  - a cinema search across sources;
  - changing an entry's source after creation (delete and re-add);
  - per-source options, refresh intervals or horizons: the interval and the horizon are global (D16);
  - discovering providers dynamically (entry points or plugins), because the registry is a static dict;
  - per-source entity sets: every source yields the same 7 day sensors.

### 13.2 Package layout (inside the template's single `client/` package)

```
client/
├── __init__.py          re-exports: models, exceptions, ShowtimesProvider, SourceInfo, CinemaInfo,
│                        PROVIDERS, get_provider_class, create_provider, UnknownSourceError.
│                        NOT AllocineProvider: the HA side never names a provider.
├── models.py            Showtime, Film, DayShowtimes, ShowtimeVersion (neutral docstrings)
├── exceptions.py        ShowtimesError hierarchy (§13.3)
├── provider.py          ShowtimesProvider (ABC), SourceInfo, CinemaInfo
├── registry.py          PROVIDERS, get_provider_class, create_provider
└── providers/
    ├── __init__.py      empty (docstring only)
    └── allocine.py      AllocineProvider + everything AlloCiné-specific (§13.4)
```

The rule stands: **nothing under `client/` imports `homeassistant`**. The boundary test (§8.1) walks every
submodule, `providers/` included. `aiohttp` may be imported, only for the `ClientSession` type annotation.
It is in the `test-client` group and ships with Home Assistant.

### 13.3 The abstraction (`provider.py`, `models.py`, `exceptions.py`)

**ABC rather than Protocol.**

- A provider is more than a set of methods: the registry needs class-level metadata (`source: ClassVar[SourceInfo]`).
- An ABC refuses to instantiate a provider with a missing method, at construction rather than at the first refresh.
- It can carry a default implementation (`async_validate_cinema`, `cinema_url`).
- Providers are ours, so nominal subclassing costs nothing. The test fake subclasses it too.

A `Protocol` would only help for foreign classes we cannot subclass, and we have none.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class SourceInfo:
    id: str            # ^[a-z][a-z0-9]*$, no "_" so that f"{id}_{cinema_id}" stays unambiguous; "allocine"
    name: str          # brand, not translated: "AlloCiné" (device manufacturer, messages)
    time_zone: str     # IANA zone of the source's datetimes: "Europe/Paris"
    ref_example: str   # shown in the cinema step's description: "W0124"
    url_example: str   # likewise: "https://www.allocine.fr/seance/salle_gen_csalle=W0124.html" ("" if none)

@dataclass(frozen=True, slots=True, kw_only=True)
class CinemaInfo:
    cinema_id: str     # canonical id
    name: str | None   # the source's name for the cinema if it knows one; None for AlloCiné (D1)

class ShowtimesProvider(ABC):
    source: ClassVar[SourceInfo]

    def __init__(self, *, session: aiohttp.ClientSession | None = None) -> None:
        """session: Home Assistant's shared session, for async HTTP providers; AlloCiné ignores it."""

    @abstractmethod
    def normalize_cinema_ref(self, raw: str) -> str:
        """Pure, no I/O. Return the canonical cinema id from what the user typed (id, URL, …).
        Raises InvalidCinemaRefError. Must be idempotent: normalize(normalize(x)) == normalize(x)."""

    @abstractmethod
    async def async_get_day(self, cinema_id: str, day: date) -> DayShowtimes:
        """One day of showtimes. Never blocks the event loop; enforces its own timeouts.
        day is the source's local date. Raises only ShowtimesError subclasses."""

    async def async_validate_cinema(self, cinema_id: str, day: date) -> CinemaInfo:
        """Check the cinema exists. Default: await self.async_get_day(cinema_id, day), so an empty day is a
        success, then return CinemaInfo(cinema_id=cinema_id, name=None). Raises CinemaNotFoundError, …"""

    def cinema_url(self, cinema_id: str) -> str | None:
        """Public page of the cinema (device configuration_url). Default None."""
```

`CinemaInfo.name` is reserved for a future source that knows cinema names. That source could add a name
confirmation step pre-filled with it (§13.5). The v1 flow ignores it: the name is typed on the same form,
before validation (D1), and AlloCiné returns `None`. It is in the contract now so that adding such a source
does not change the ABC.

**Models (neutral).** `Showtime`, `Film` and `DayShowtimes` keep their fields and invariants. **(D24, D28)**
They gain optional, defaulted fields (`Film.ref`, `Film.details: FilmDetails | None`, `Showtime.subtitled`,
`hard_of_hearing_subtitles`, `disabled_access`, `audio_description`,
`formats`, `preview`, `weekly_outing`, `ticket_url`), so a source that knows none of them, and the fake provider,
change nothing; an unreadable enrichment field is `None` and never a `SourceParseError` (design doc §3, §4.8).
Only the docstrings of the existing fields change:

- `starts_at`: aware, in `source.time_zone`;
- `DayShowtimes.cinema_id`: the provider's canonical id;
- `day`: the source's local date.

`ShowtimeVersion` stays `ORIGINAL`, `DUBBED`, `LOCAL`, `UNKNOWN`, redefined neutrally:

| Value      | Meaning (any source)                                                      | AlloCiné `diffusionVersion` (D2)                      | Attribute (§5.3)                               |
| ---------- | ------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------- |
| `ORIGINAL` | the film's original language, not the source country's (subtitled or not) | `ORIGINAL`, unless `languages == ["FRENCH"]`          | `vost` if `subtitled is True`, else `vo` (D26) |
| `DUBBED`   | dubbed into the source country's language                                 | `DUBBED`                                              | `vf`                                           |
| `LOCAL`    | the film's original language is the source country's                      | `LOCAL`, or `ORIGINAL` with `languages == ["FRENCH"]` | `vf`                                           |
| `UNKNOWN`  | anything the provider cannot map; kept, never dropped                     | anything else                                         | `other`                                        |

`Showtime.subtitled` (`bool | None`) is a separate axis (D26): a source that does not know leaves it `None`, and
an `ORIGINAL` showtime then goes to `vo`.

This is neutral enough. Any cinema listing distinguishes "original language" from "local language". A
source that cannot tell `DUBBED` from `LOCAL` maps both to `DUBBED`, and a source with no version
information maps everything to `UNKNOWN`. Mapping the source's codes is the provider's job, never the HA
side's. The attribute names `vf` / `vo` / `other` are the same for every source (D15).

**Exceptions (neutral).** Every provider must map **all** its failures to these. No library, `requests`
or `aiohttp` exception may cross the provider boundary, and the original is chained as `__cause__`.

```python
class ShowtimesError(Exception): """Base of every client error."""
class SourceConnectionError(ShowtimesError): """The source is unreachable or answered an unexpected status."""
class SourceTimeoutError(SourceConnectionError): """A request or the whole call exceeded its timeout."""
class SourceAccessDeniedError(SourceConnectionError):   # (D17) name as in the implementation
    """The source refused us (HTTP 403 / 429, bot protection or rate limit). Never worked around."""
class CinemaNotFoundError(ShowtimesError): """The source does not know this cinema."""
class SourceParseError(ShowtimesError): """The source's response did not have the expected shape."""
class InvalidCinemaRefError(ShowtimesError): """The reference is malformed (checked locally, no I/O)."""
class UnknownSourceError(ShowtimesError): """No provider is registered under this source id (registry)."""
```

Rename map for the existing code. It is a pure rename; the AlloCiné provider raises the neutral classes
directly, with no AlloCiné subclasses:

| Before (D1–D11 code)                                            | After (D13)               |
| --------------------------------------------------------------- | ------------------------- |
| `AllocineError`                                                 | `ShowtimesError`          |
| `AllocineConnectionError`                                       | `SourceConnectionError`   |
| `AllocineTimeoutError`                                          | `SourceTimeoutError`      |
| `AllocineCinemaNotFoundError`                                   | `CinemaNotFoundError`     |
| `AllocineParseError`                                            | `SourceParseError`        |
| `InvalidCinemaIdError`                                          | `InvalidCinemaRefError`   |
| (new)                                                           | `UnknownSourceError`      |
| (new, D17; was part of `AllocineConnectionError` for 403 / 429) | `SourceAccessDeniedError` |

Catch order on the HA side: `SourceAccessDeniedError` before `SourceConnectionError`, because it is a
subclass.

### 13.4 Registry and the AlloCiné provider

`registry.py`:

```python
PROVIDERS: Final[dict[str, type[ShowtimesProvider]]] = {AllocineProvider.source.id: AllocineProvider}

def get_provider_class(source_id: str) -> type[ShowtimesProvider]:   # raises UnknownSourceError
def create_provider(source_id: str, *, session: aiohttp.ClientSession | None = None) -> ShowtimesProvider:
```

- `PROVIDERS` is a plain dict, ordered: the first entry is the default, used when it is the only one. Its
  key is always `cls.source.id`, and a test enforces that.
- The HA side calls `create_provider(entry.data[CONF_SOURCE], session=async_get_clientsession(hass))` in
  `async_setup_entry` and in the cinema step. It never imports a provider module.
- An unknown id at setup (an entry created by a newer version, then a downgrade) → `ConfigEntryError`
  (translated `unknown_source`): setup error, no retry loop.

`providers/allocine.py`, `class AllocineProvider(ShowtimesProvider)`: the current `client/api.py`, moved and
renamed. **Everything AlloCiné-specific lives here and only here:**

- `source = SourceInfo(id="allocine", name="AlloCiné", time_zone="Europe/Paris", ref_example="W0124", url_example="https://www.allocine.fr/seance/salle_gen_csalle=W0124.html")`;
- the id format and the URL parsing (D4, D9): `normalize_cinema_id` and `_cinema_id_from_url` become the
  method `normalize_cinema_ref`, same rules;
- the `Europe/Paris` conversion (`ALLOCINE_TIME_ZONE` becomes `source.time_zone`);
- `_AllocineAPIWithTimeout` (the `_get_json_request` override, D8) and the `requests` error mapping,
  including `USER_AGENT`, the trailing-slash URL and 403 / 429 → `SourceAccessDeniedError` (D17);
- the timeouts: `DEFAULT_CONNECT_TIMEOUT`, `DEFAULT_READ_TIMEOUT`, `DEFAULT_CALL_TIMEOUT`, kept as
  keyword-only constructor arguments next to `session`;
- the `diffusionVersion` mapping and its once-per-value warning;
- `cinema_url(cinema_id)` → `https://www.allocine.fr/seance/salle_gen_csalle={cinema_id}.html` (moved from
  `const.CINEMA_URL`);
- `async_validate_cinema`: the default from the ABC, which fetches that day. That is today's behaviour.

`manifest.json` `requirements` is the union of every provider's pinned requirements: v1 has only
`allocine-seances==0.0.14`. There is no `loggers` key: no provider library logs through `logging`. A future
provider whose library does log would add its logger name there.

### 13.5 Config flow with sources

- **v1 (one source): the source step is skipped.** Showing a one-option select would be an extra click
  that tells the user nothing. Step `user` routes to `cinema` with the only source. The entry still
  records `source`.
- **With two or more sources:** step `user` shows the `source` select (§4.1). Translations under
  `selector.source.options.<id>`.
- **Adding a source whose reference fits one text field** (an id or a URL): nothing to write in the flow.
  The generic `cinema` step uses `normalize_cinema_ref`, `async_validate_cinema` and the `SourceInfo`
  placeholders.
- **Adding a source that needs a different form** (e.g. pick a city, then a cinema): add its own step
  method(s) in `config_flow.py`, e.g. `async_step_cinema_<id>`, and one line in
  `_CINEMA_STEP: dict[str, str]`, which maps the source id to its first cinema step and defaults to
  `"cinema"`. `user` routes through that table. Those steps end with the same
  `_async_finish(source_id, cinema_id, name)` helper (unique id, abort-if-configured, create entry), so the
  AlloCiné path and the shared parts are not edited.
- Unique id: `f"{source_id}_{cinema_id}"`, set before any network call, as before.

### 13.6 Identifiers and versions, decided now

| Thing                    | Value from v1                                                             | Before D13 (code)   |
| ------------------------ | ------------------------------------------------------------------------- | ------------------- |
| config entry `unique_id` | `allocine_W0124`                                                          | `W0124`             |
| config entry `data`      | `{"source": "allocine", "cinema_id": "W0124"}`                            | `{"cinema_id": …}`  |
| config entry version     | `VERSION = 1`, `MINOR_VERSION = 1`                                        | `VERSION = 1`       |
| device identifier        | `(DOMAIN, "allocine_W0124")`                                              | `(DOMAIN, "W0124")` |
| sensor unique ids        | `allocine_W0124_day_0` … `_day_6`                                         | `W0124_day_0` …     |
| store key                | `movie_showtimes.<entry_id>` (unchanged)                                  | —                   |
| store content            | includes `"source"` and is checked on load (§12.2), `STORAGE_VERSION = 1` | —                   |

- **No migration code:** nothing has been released (`manifest.json` version `0.0.0`), so v1 starts with
  the namespaced ids. Developers who already created entries under `./config` while testing D1–D11 delete
  and re-add them. That is the only cost, and it is why this is decided now: changing ids after a release
  would need `async_migrate_entry` plus entity and device registry migrations.
- The entity ids users see (`sensor.<device>_today`) do not change: they come from the names, not from
  the unique ids.
- A later change to the meaning of `data` bumps `MINOR_VERSION` (compatible) or `VERSION` (incompatible),
  with `async_migrate_entry`.

### 13.7 Files to change (checklist for ha-developer)

| File                                                           | Action                                                                                                                                                                                                                      |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `client/exceptions.py`                                         | Rename the classes per §13.3; neutral docstrings; add `UnknownSourceError`.                                                                                                                                                 |
| `client/models.py`                                             | Neutral docstrings (§13.3); fields unchanged.                                                                                                                                                                               |
| `client/provider.py`                                           | **New:** `ShowtimesProvider`, `SourceInfo`, `CinemaInfo`.                                                                                                                                                                   |
| `client/registry.py`                                           | **New:** `PROVIDERS`, `get_provider_class`, `create_provider`.                                                                                                                                                              |
| `client/providers/__init__.py`                                 | **New** (docstring only).                                                                                                                                                                                                   |
| `client/api.py` → `client/providers/allocine.py`               | **Move** (`git mv`). `AllocineClient` → `AllocineProvider(ShowtimesProvider)` with `source`; `normalize_cinema_id` → method `normalize_cinema_ref`; add `cinema_url`; constructor gains `session=None`; neutral exceptions. |
| `client/__init__.py`                                           | Export the neutral API and the registry only (§13.2).                                                                                                                                                                       |
| `const.py`                                                     | Add `CONF_SOURCE`. Remove `CINEMA_URL` (moved into the provider).                                                                                                                                                           |
| `config_flow.py`                                               | Steps `user` (source; skipped with one) → `cinema`; `create_provider`; neutral exceptions; unique id `f"{source}_{id}"`; `data` gains `source`; `_CINEMA_STEP` table and `_async_finish` helper.                            |
| `__init__.py`                                                  | `create_provider(entry.data[CONF_SOURCE], session=…)`, `UnknownSourceError` → `ConfigEntryError`. No `AllocineClient` import.                                                                                               |
| `coordinator.py`                                               | `client: AllocineClient` → `provider: ShowtimesProvider`; neutral exceptions; `translation_placeholders={"source": provider.source.name}`; name from `unique_id`.                                                           |
| `entity.py`                                                    | Device identifier `entry.unique_id`, manufacturer `provider.source.name`, `configuration_url=provider.cinema_url(...)` (omitted if `None`).                                                                                 |
| `sensor.py`                                                    | Unique id `f"{entry.unique_id}_{key}"`.                                                                                                                                                                                     |
| `showtimes.py`, `diagnostics.py`                               | Imports from the neutral API; diagnostics add the `source` block.                                                                                                                                                           |
| `store.py` (D12)                                               | Takes `SourceInfo`; stores and checks `source`; `source_tz` from `source.time_zone`.                                                                                                                                        |
| `strings.json`, `translations/en.json`, `translations/fr.json` | Steps `user` / `cinema`, `selector.source.options.allocine`, neutral error texts, `{source}` placeholders, `unknown_source` (§6).                                                                                           |
| `manifest.json`                                                | Unchanged in v1 (requirements are the union of the providers').                                                                                                                                                             |
| tests                                                          | Per §13.8.                                                                                                                                                                                                                  |

### 13.8 Test plan (D13)

**Client scope (`tests/movie_showtimes/client/`).** The client scope must still reach 95 % on its own.

- `provider_contract.py`: a **reusable contract suite**, a base class `ProviderContract` that is not
  collected on its own (no `Test` prefix). A provider's test module subclasses it as
  `class TestAllocineContract(ProviderContract)` and supplies fixtures: `provider`, `valid_ref`, `canonical_id`,
  `invalid_refs`, and `arrange(kind)`. `arrange` makes the next `async_get_day` see one outcome: `ok`,
  `empty`, `not_found`, `access_denied` (D17), `connection`, `timeout`, `malformed`. For AlloCiné it patches
  `requests.get` (`access_denied` = HTTP 403, plus a parametrized 429 in the provider's own tests). The
  suite checks:
  - `source`: `id` matches `^[a-z][a-z0-9]*$`, `name` is not empty, `time_zone` is a valid IANA zone
    (`ZoneInfo(time_zone)`), and `ref_example` normalizes without error;
  - `normalize_cinema_ref`: `valid_ref` → `canonical_id`, it is idempotent, each `invalid_ref` raises
    `InvalidCinemaRefError`, and it does no I/O (any network attempt fails the test);
  - `async_get_day` on `ok`: `cinema_id == canonical_id`, `day` as requested, every `starts_at` aware with
    the `source.time_zone` zone, films sorted by `title.casefold()`, no empty title, no film without
    showtimes, each film's showtimes sorted, every `version` a `ShowtimeVersion`;
  - `empty` → `films == ()` and no exception;
  - errors: `not_found` → `CinemaNotFoundError`; **(D17) `access_denied` → `SourceAccessDeniedError`**;
    `connection` → `SourceConnectionError` (neither `SourceTimeoutError` nor `SourceAccessDeniedError`);
    `timeout` → `SourceTimeoutError`; `malformed` → `SourceParseError`. Each has
    `__cause__` set where there is an underlying error, and **no other exception type escapes**;
  - `async_validate_cinema`: `ok` and `empty` → `CinemaInfo(cinema_id=canonical_id, …)`; `not_found` →
    `CinemaNotFoundError`;
  - `cinema_url` returns `None` or an `https://` URL.
- `providers/test_allocine.py` (+ `providers/fixtures/`): `TestAllocineContract(ProviderContract)`, plus
  everything AlloCiné-specific already in §8.1: URL forms (D4/D9), the library override, the signature
  guard, `movie: null`, pagination, Paris DST, `diffusionVersion` mapping, the asyncio backstop and the
  off-loop check. The current client tests move here.
- `test_registry.py`:
  - every `PROVIDERS` value is a concrete `ShowtimesProvider` subclass (instantiable), and its key equals
    `cls.source.id`;
  - `"allocine"` is registered;
  - `get_provider_class("nope")` and `create_provider("nope")` → `UnknownSourceError`;
  - `create_provider` passes `session` through;
  - **every registered provider has a contract test:** collect `ProviderContract.__subclasses__()` and
    compare their `source_id` class attributes with `PROVIDERS`;
  - the ABC refuses a subclass that misses an abstract method (`TypeError`);
  - the default `async_validate_cinema` and `cinema_url` behave as documented, tested through a minimal
    subclass.
- `test_fake_contract.py`: the fake provider (below) also passes `ProviderContract`, so the HA tests run
  against a fake that behaves like a real provider.
- The boundary test (§8.1) covers `provider.py`, `registry.py` and `providers/*`.

**Integration scope (`tests/` without the client path).**

- `tests/fake_provider.py`: `class FakeProvider(ShowtimesProvider)` with
  - `source = SourceInfo(id="fake", name="Fake Cinemas", time_zone="Europe/Paris", ref_example="C1", url_example="")`;
  - `normalize_cinema_ref`: strip + upper, accepts `fake:<id>`, rejects anything not `^[A-Z0-9]{1,10}$`;
  - per-date programming: `fake.days[date] = DayShowtimes | ShowtimesError`, with a default empty day;
  - a `calls: list[tuple[str, date]]` log and `cinema_url` → `"https://fake.example/C1"`.

  A `FakeProvider2` subclass with `id="fake2"` and `cinema_url` → `None` covers the multi-source flow
  and the missing configuration URL.

- Fixture: `patch.dict(registry.PROVIDERS, {"fake": FakeProvider}, clear=True)`, autouse in the
  integration `conftest.py`. The HA tests therefore never run AlloCiné code, and never need AlloCiné
  fixtures.
- Cases (in §8.2 and §12.8, updated): source step skipped with one source and shown with two;
  namespaced unique ids, device identifier and sensor unique ids; same cinema id under two sources → two
  entries; unknown source at setup → `SETUP_ERROR`; manufacturer and configuration URL from the provider
  (and none when `cinema_url` is `None`); exception messages carry the source name; the store records and
  checks `source`; diagnostics include the `source` block.

## Appendix A. Source data available (AlloCiné)

This is based on a real response the user captured for cinema `W0124` (`/tmp/lib/r.json`, 2026-11-12, **one
film**, _La Gradiva_). The structure is verified for that one film only. It is the same JSON endpoint
`get_showtime` and `get_movies` use (`…/_/showtimes/theater-<id>/d-<date>/p-<n>/`): one JSON document per
page, 15 films per page, and no HTML involved. Reading more of it therefore costs no extra request.

The override (§3.3) does receive the full document. Exploiting it without hidden state, however, means
replacing `get_showtime` with our own pagination (D25): stashing documents on the instance while the library's
loop runs would be shared between threads, since a call abandoned by the 60 s `asyncio` backstop keeps its
thread running and a manual refresh can start another call on the same instance. **What is now used (D24) and
how:** `docs/design/film-enrichment.md`. This appendix records what the document holds.

**Response level**

- `results`: one item per film, `{movie, showtimes}`;
- `pagination`: `{page, totalPages, itemsPerPage (= 15), totalItems}`. **`page` is a string (`"1"`)**,
  `totalPages` an int;
- `error`: **`false`** in the sample (`true` with `message: "no.showtime.error"` on an empty day, §2);
- `message`, `messageParam`, `nextDate`: `null` in the sample. On an empty day `messageParam` is
  `{"day", "page"}`. `nextDate` was `null` in all 3 responses seen; its role is unverified and it is not used
  (design doc Q2);
- `params` (the filters of the request, all `null` but `page: 1`), `data` (`null`), `facets` (the filter values
  available, e.g. `showtimes.projection` → `DIGITAL` / "Numérique", `showtimes.version_detail` → `LOCAL`,
  `DUBBED`, `ORIGINAL_ST`, `ORIGINAL`, `showtimes.service` → `DISABLED_ACCESS`);
- **no cinema name or address anywhere**, which confirms D1.

**Per film (`results[].movie`)** — the whole object weighs **11.6 KB** for one film (13.6 KB for the document).

| Field                                                                                   | Notes                                                                                                            |
| --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `title`, `originalTitle`                                                                |                                                                                                                  |
| `type`, `internalId`, `id`                                                              | `type: "FEATURE_FILM"`; `internalId` an int (`318225`, the film page id); `id` an opaque base64 id               |
| `runtime`                                                                               | a **string**, e.g. `"2h 25min"`, to be parsed                                                                    |
| `synopsis`, `synopsisFull`, `synopsis_json`                                             | the same text: plain, HTML (`<p class="bo-p">`), and a JSON body                                                 |
| `genres[]`                                                                              | `{id, translate, tag}`, e.g. `translate: "Drame"`, `tag: "DRAMA"`                                                |
| `languages`                                                                             | codes, e.g. `["FRENCH"]`                                                                                         |
| `countries[]`                                                                           | `{id, name, localizedName}`, e.g. `name: "Italy"`, `localizedName: "Italie"`                                     |
| `data.productionYear`                                                                   | under **`data`** (with `seo`, `rules`)                                                                           |
| `poster`                                                                                | `{id, internalId, url, path}`                                                                                    |
| `stats`                                                                                 | `userRating` and `pressReview` `{score, count}`, `userReview.count`, `wantToSeeCount`, `metric.{hits, sessions}` |
| `releases[]`                                                                            | `{releaseDate.{date, precision}, name, certificate.{code, label}, visaNumber, …}`: **`certificate` is here**     |
| `credits[]`                                                                             | `{person.{firstName, lastName, internalId}, position.{name, department}, rank}`; only the director in the sample |
| `cast`                                                                                  | `{edges[].node.actor, nodes[]}` (`nodes` duplicates `edges`); **truncated to 3 actors by AlloCiné**              |
| `flags` (`hasTrailer`, `isPlayingNow`, …), `customFlags` (`isPremiere`, `weeklyOuting`) |                                                                                                                  |
| `relatedTags[]`                                                                         | 10 tags, **~7 KB**: each `{name, scope, data.seo{…}, tags.list}`, the `seo` blob being most of it                |
| `editorialReviews`                                                                      | `[]` in the sample: shape unknown                                                                                |

**Per showtime.** Showtimes are grouped in six lists under `results[].showtimes`: `original`,
`original_st`, `original_sme`, `multiple`, `multiple_st`, `multiple_sme`. The library merges them and
de-duplicates them by `internalId`; since D25 our parser does, keeping which list each came from. In the sample
only `original_st` is non-empty.

| Field                                       | Notes                                                                                                                                   |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `internalId`                                | int                                                                                                                                     |
| `startsAt`                                  | naive local (Paris) time                                                                                                                |
| `diffusionVersion`                          | `ORIGINAL` / `DUBBED` / `LOCAL`. **A French film can be `ORIGINAL`** (_La Gradiva_, in `original_st`): D2 revised                       |
| `tags`                                      | e.g. `Showtime.Accessibility.Subtitled`, `Localization.Version.Original`, `Format.Projection.Digital`, `Theater.Service.DisabledAccess` |
| `projection`, `service`                     | lists of codes: `["DIGITAL"]`, `["DISABLED_ACCESS"]`                                                                                    |
| `experience`, `comfort`, `picture`, `sound` | **`null`** in the sample (W7520 has `experience`: `SCREEN_X`, `PLF`, `E_4DX`)                                                           |
| `data.ticketing[]`                          | `{provider, type, urls[]}`: booking links (`provider: "relay"`, `type: "DESKTOP"`; the URL contains a raw space)                        |
| `isPreview`, `isWeeklyMovieOuting`          | booleans                                                                                                                                |
| `timeBeforeStart`                           | **not reliable** (`PT0H0M0S` for a showtime hours away). Not used                                                                       |

**Two full real days (C0159 2026-11-14, W7520 2026-11-11)** — captured later, outside the repository; details,
counts and examples in the design doc §0, §4.4–§4.7, §6.1:

- C0159 (UGC): 3 pages (`"1"`…`"3"`), 36 films, 161 showtimes. VOST in `original` with tag
  `Localization.Subtitle.French`; every VF (French films included) `DUBBED` in `multiple`; ticketing `relay` +
  `default` (ugc.fr); formats `DIGITAL` only; PMR on 145.
- W7520 (Pathé): 2 pages, 26 films, 66 showtimes. VOST in `original_st` with tag `Showtime.Accessibility.Subtitled`;
  VF `DUBBED` (34) and `LOCAL` (13, French films) in `multiple`; ticketing `en` + `relay` + `default` (pathe.fr);
  formats `IMAX`, `F_3D`, experience `SCREEN_X`, `PLF`, `E_4DX`; PMR on 48; tag `Showtime.Accessibility.Greta` on 16.
- Both: `service` and `Theater.Service.DisabledAccess` always agree; `Showtime.Accessibility.Accessible` does not
  match PMR; `*_sme` always empty; no `movie: null`; `"0h 00min"` runtimes; `releases[]` of up to 54 items
  (_Dune_); `editorialReviews` always `[]`; a movie object of 4–35 KB.

**Observations (taken up by D24–D31)**

- The v1 `vo` group mixed original-version showtimes with and without subtitles. The subtitle information is in
  `tags` (`Showtime.Accessibility.Subtitled`) and in the list the showtime came from (`original_st`), which the
  library's merge lost. D25 / D26 read both.
- **Size.** Raw, the heavy parts are `relatedTags` (~7 KB, mostly `seo`), `cast` (1.3 KB), `releases`, `flags`,
  the synopsis variants, and `ticketing`. Once parsed into our models (names only for tags and people, plain
  synopsis only), a film is about 1.5 KB. The sensor attribute keeps them inside `films` (unrecorded) and under
  each film's `details` (D29); the store keeps each film once, in a catalogue shared across days (D27).
- Additions go into the neutral models (§13.3) as optional fields (D28). Because nothing is released, the store
  schema changes without a version bump (D27); after a release, an addition would follow the minor-version rule
  of §12.2.

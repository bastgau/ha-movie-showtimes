# Film enrichment, VO / VOST and accessibility (D2 revised, D24–D31)

Status: **implemented** (revision 5 describes the code in `client/providers/allocine.py`; client tests 403,
integration tests 212, 99 % coverage each, no xfail). Pinned Home Assistant `2026.11.2`, `allocine-seances==0.0.14`.
Builds on `docs/architecture.md` (§2, §3.3, §5.3, §12, §13, Appendix A); that document points here for
everything below instead of repeating it.

Revision 3. Revision 2 recorded the user's answers to the first questions (editorial reviews dropped; every other
free field added; formats as codes; French rule only for `languages == ["FRENCH"]`; one DESKTOP booking link;
accessibility in scope, SME separate from `vost`). Revision 3 re-checks every rule against two complete real days
(below) and changes the subtitle detection, the PMR definition, the booking-link choice and the release choice
accordingly. Revision 4 adds a third accessibility list, `audio_description`, from the tag
`Showtime.Accessibility.Greta` (user decision, D31).

## Implementation notes (revision 5, after implementation and review)

- **Logging rule (D28).** A value of an unexpected type → **one** DEBUG line; `null` or absent → silent. Showtime-level
  fields: at most one line per key and per day. A credit without `person` is silent; a `credits` item that is not an
  object is skipped without a line (Q18). This replaces every other wording below (§4.5, §4.6, §8, §9.2).
- **Pagination deadline (D25).** `async_get_day` computes `deadline = time.monotonic() + call_timeout` and passes it to
  `fetch_showtime_pages(..., deadline=...)`, which checks it **before every page, the first included** →
  `SourceTimeoutError`. Reason: the executor thread survives the 60 s `asyncio` timeout; without the check an abandoned
  thread would go on requesting the remaining pages.
- **`_film_ref`** checks `internalId` without converting to `int` (a string of more than 4 300 digits would raise in
  `int()` and fail the day) and runs under the enrichment safety net.
- **URLs** (`url`, `poster_url`, `ticket_url`): scheme http(s) with a host; rejected if they start with a space or
  contain a control character `[\x00-\x1f\x7f-\x9f]`. A trailing space and inner spaces are **accepted**: real `relay`
  URLs end with a space (C0159: 70 + 82 + 9 on the three pages; W7520: 50 + 16). The value is returned unchanged.
- **Same `ref` on two pages:** first title and details kept; if the first occurrence has `details=None`, the next
  occurrence's details are taken.
- **Fixtures:** in `tests/movie_showtimes/client/providers/fixtures/`, indented (Q17 settled: no `.prettierignore`);
  `showtimes_W0124.json` renamed `showtimes_synthetic.json`.

## 0. Evidence: three real captures

All three were fetched outside the repository with the honest `User-Agent` (D17). Nothing raw is copied into the
repository; the fixtures derived from them are described in §9.1.

| Capture                                  | Cinema / day        | Pages, films, showtimes                                                        | Conventions seen                                                                                                                                                                                                                                                                                                  |
| ---------------------------------------- | ------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/tmp/lib/r.json`                        | `W0124`, 2026-11-12 | 1 page (`"page": "1"`), 1 film, 1 showtime                                     | _La Gradiva_, `languages ["FRENCH"]`, `ORIGINAL` in **`original_st`**, tag `Showtime.Accessibility.Subtitled`; one ticketing entry (`relay`). The only real case of the French rule.                                                                                                                              |
| `/tmp/c0159/p1–p3.json` (a UGC cinema)   | `C0159`, 2026-11-14 | 3 pages (`"1"`, `"2"`, `"3"`), 36 films, 161 showtimes (raw 280 + 266 + 79 KB) | VOST in **`original`** (64, `ORIGINAL`) with tag **`Localization.Subtitle.French`**, never `*_st`, never the `Subtitled` tag. VF in `multiple` (97, all `DUBBED`, **French films included**, tag `Localization.Version.French`). No `LOCAL`. Two ticketing entries (`relay`, `default`). Formats: `DIGITAL` only. |
| `/tmp/w7520/p1–p2.json` (a Pathé cinema) | `W7520`, 2026-11-11 | 2 pages (`"1"`, `"2"`), 26 films, 66 showtimes (raw 281 + 145 KB)              | VOST in **`original_st`** (19, `ORIGINAL`) with tag `Showtime.Accessibility.Subtitled`. VF in `multiple`: 34 `DUBBED` + **13 `LOCAL`** (French films, tag `Localization.Language.French`). Three ticketing entries (`en`, `relay`, `default`). Real formats: `IMAX`, `F_3D`, `SCREEN_X`, `PLF`, `E_4DX`.          |

Facts that hold in all three (434 showtimes, 63 films): no `"movie": null`, no empty day, no duplicate showtime
`internalId`, no film on two pages, `editorialReviews` always `[]`, `timeBeforeStart` always `PT0H0M0S`,
`picture` / `sound` / `comfort` always `null`, no `*_sme` list ever non-empty, no `multiple_st`, no tag that names
subtitles for the deaf and hard of hearing, no `isPreview: true`.

## 1. Goal and scope

Show, for each film of a day sensor, everything that the showtimes JSON document **already received** carries,
split the original-version showtimes into `vo` (no classic subtitles) and `vost` (classic subtitles), and list
the showtimes accessible to people with reduced mobility (PMR), those with subtitles for the deaf and hard of
hearing (SME) and those with audio description (Greta, D31).

### 1.1 Fixed constraints (user decisions)

- **No extra request (D24).** No cinema page, no `get_cinema`, no film page, no `nextDate` follow-up, no
  `get_movies`. A refresh still makes one request per page per day (≈ 16 a day per cinema in the one-page case;
  C0159 has 3 pages a day, W7520 2), exactly as today.
- Everything readable for free in that document is added (§1.2), except `timeBeforeStart` (unreliable),
  `editorialReviews` (user decision) and the duplicates and internal ids listed in §1.3.
- **Accessibility (D30)** is derived from `service` and the showtime lists; the raw `tags` are never exposed.
- Nothing is in production: **no Store migration, no version bump, no code to read older data** (D27).
- No size cap on the attributes, but every new key lives inside `films`, which is already unrecorded (D29).

### 1.2 In scope: the fields and their source

Paths are relative to one item of `results[]` (film level) or to one showtime of
`results[].showtimes.<list>[]` (showtime level). "Model" is the neutral field (§3). "Attribute" is the key in
the sensor's `films[]` items (§6). Every one of them is optional: missing or unreadable → `None` / `()`, never
an error (D28).

**Film level**

| Data                    | JSON source (verified in the captures)                                                             | Model (`FilmDetails` unless noted) | Attribute                            |
| ----------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------ |
| film id                 | `movie.internalId` (int)                                                                           | `Film.ref: str \| None`            | `film_id`                            |
| film page URL           | **built**: `https://www.allocine.fr/film/fichefilm_gen_cfilm=<internalId>.html`                    | `url`                              | `url`                                |
| film type               | `movie.type` (code, `"FEATURE_FILM"`)                                                              | `film_type`                        | `film_type`                          |
| original title          | `movie.originalTitle`                                                                              | `original_title`                   | `original_title`                     |
| production year         | `movie.data.productionYear` (int, under `data`)                                                    | `year`                             | `year`                               |
| release date            | `releases[]`, the chosen release's `releaseDate.date` (§4.6)                                       | `release_date`                     | `release_date`                       |
| visa number             | the chosen release's `visaNumber` (`"155420"`; also `"2026005757"` in W7520)                       | `visa_number`                      | `visa_number`                        |
| certificate             | the chosen release's `certificate.label` (fallback `.code`)                                        | `certificate`                      | `certificate`                        |
| runtime                 | `movie.runtime`, a string `"2h 25min"` → minutes (§4.5)                                            | `runtime`                          | `runtime`                            |
| genres                  | `movie.genres[].translate`                                                                         | `genres`                           | `genres`                             |
| countries               | `movie.countries[].localizedName` (fallback `.name`)                                               | `countries`                        | `countries`                          |
| languages               | `movie.languages[]` (codes: `FRENCH`, `ENGLISH`, `JAPANESE`, `HINDI`, `["ENGLISH","KOREAN"]` …)    | `languages`                        | `languages`                          |
| directors               | `movie.credits[]` where `position.name == "DIRECTOR"`                                              | `directors`                        | `directors`                          |
| poster                  | `movie.poster.url`                                                                                 | `poster_url`                       | `poster`                             |
| user rating             | `movie.stats.userRating.{score,count}` (both `null` for _Peppa fête Noël_, W7520)                  | `user_rating: Rating`              | `user_rating`, `user_rating_count`   |
| user reviews            | `movie.stats.userReview.count`                                                                     | `user_review_count`                | `user_review_count`                  |
| press rating            | `movie.stats.pressReview.{score,count}` (`pressReview: null` happens)                              | `press_rating: Rating`             | `press_rating`, `press_rating_count` |
| want-to-see count       | `movie.stats.wantToSeeCount`                                                                       | `want_to_see_count`                | `want_to_see_count`                  |
| page views              | `movie.stats.metric.{hits,sessions}`                                                               | `hits`, `sessions`                 | `hits`, `sessions`                   |
| premiere                | `movie.customFlags.isPremiere`                                                                     | `premiere`                         | `premiere`                           |
| weekly outing (release) | `movie.customFlags.weeklyOuting`                                                                   | `weekly_outing`                    | `weekly_outing`                      |
| has a trailer           | `movie.flags.hasTrailer`                                                                           | `has_trailer`                      | `has_trailer`                        |
| other flags             | every **boolean** entry of `movie.flags` that is `true`, by its source name (§4.6)                 | `flags: tuple[str, ...]`           | `flags`                              |
| synopsis (plain text)   | `movie.synopsis` (can be `""`: _Ramayana_, W7520)                                                  | `synopsis`                         | `details.synopsis`                   |
| full synopsis (as is)   | `movie.synopsisFull`, **verbatim, HTML not cleaned** (`<p class="bo-p">…</p>`)                     | `synopsis_full`                    | `details.synopsis_full`              |
| cast                    | `movie.cast.edges[].node`: `actor`, else `originalVoiceActor`, else `voiceActor` (§4.6); 3 at most | `cast`                             | `details.cast`                       |
| credits                 | `movie.credits[].{person.{firstName,lastName}, position.name}`                                     | `credits: tuple[Credit, ...]`      | `details.credits`                    |
| related tags            | `movie.relatedTags[].name` (the tag's `data.seo` blob is dropped)                                  | `related_tags`                     | `details.related_tags`               |

**Showtime level**

| Data                    | JSON source                                                                                                                    | Model (`Showtime`)                | Attribute                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- | -------------------------------------------------------------------------- |
| start                   | `startsAt` (naive Paris) — **required**, as today                                                                              | `starts_at`                       | `vf`/`vo`/`vost`/`other` lists; `details.showtimes[].time`, `.starts_at`   |
| version                 | `diffusionVersion` (+ the French rule, §4.4) — as today                                                                        | `version`                         | `details.showtimes[].version` (`vf` / `vo` / `vost` / `other`)             |
| classic subtitles       | list `original_st` / `multiple_st` **or** tag `Showtime.Accessibility.Subtitled` **or** a tag `Localization.Subtitle.*` (§4.4) | `subtitled: bool \| None`         | `details.showtimes[].subtitled`                                            |
| SME subtitles (D30)     | list `original_sme` / `multiple_sme` only — never seen filled (§4.7, Q10)                                                      | `hard_of_hearing_subtitles`       | `accessibility.sme`; `details.showtimes[].sme`                             |
| PMR access (D30)        | `service` contains `"DISABLED_ACCESS"` **or** tag `Theater.Service.DisabledAccess` (§4.7)                                      | `disabled_access: bool \| None`   | `accessibility.pmr`; `details.showtimes[].pmr`                             |
| formats                 | `projection`, `picture`, `sound`, `experience`, `comfort` (lists of codes, or `null`), codes verbatim                          | `formats: ShowtimeFormats`        | `details.showtimes[].projection` … `.comfort`                              |
| preview                 | `isPreview`                                                                                                                    | `preview`                         | `details.showtimes[].preview`                                              |
| weekly outing showtime  | `isWeeklyMovieOuting`                                                                                                          | `weekly_outing`                   | `details.showtimes[].weekly_outing`                                        |
| audio description (D31) | tag `Showtime.Accessibility.Greta` (W7520: 16 showtimes, 6 films) — **assumed** audio description (§4.7)                       | `audio_description: bool \| None` | `accessibility.audio_description`; `details.showtimes[].audio_description` |
| booking link            | `data.ticketing[]`, `type == "DESKTOP"`, provider `default` first (§4.6)                                                       | `ticket_url`                      | `details.showtimes[].ticket_url`                                           |

Format codes are exposed **as the source gives them** (user decision Q4), irregular names included. Seen:
projection `DIGITAL`, `IMAX`, `F_3D`; experience `PLF`, `E_4DX`, `SCREEN_X`. For reference only (not used), the
`facets` of W7520 label them `Numérique`, `IMAX`, `3D`, `PLF`, `4DX`, `ScreenX`, and `DISABLED_ACCESS` as `Accès
handicapés`. A showtime can carry several codes (`["F_3D", "IMAX"]`, `["SCREEN_X", "PLF"]`, `["E_4DX", "PLF"]`).

### 1.3 Out of scope

| Left out                                                                                                                                                                                       | Why                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Any request beyond the showtimes pages (`get_movies`, `get_cinema`, film page …)                                                                                                               | User decision D24.                                                                         |
| `editorialReviews`                                                                                                                                                                             | User decision (empty in every capture). Not read, not logged.                              |
| `timeBeforeStart`                                                                                                                                                                              | Unreliable (`PT0H0M0S` on all 228 showtimes of the two full days).                         |
| `nextDate`                                                                                                                                                                                     | Role unverified (`null` in every response seen). Not read (Q2).                            |
| Raw showtime `tags`                                                                                                                                                                            | Never exposed: subtitles, version, formats and PMR are exposed through the derived fields. |
| Tag `Showtime.Accessibility.Accessible`                                                                                                                                                        | Meaning unknown; not PMR (§4.7). Not used (Q14).                                           |
| The `relay` URL's `code=` string (`SME; AUDIO; GRETA; PMR; 2D; VO;`)                                                                                                                           | Checked against the tags (§4.7): unreliable at C0159, redundant at W7520. Not used.        |
| Ticketing entries other than the chosen one                                                                                                                                                    | User decision: one DESKTOP link per showtime.                                              |
| Non-boolean `flags` entries (`isClubApproved: []`, `hasClubNews: []`)                                                                                                                          | Not flags; meaning unknown.                                                                |
| Duplicates: `synopsis_json`, `cast.nodes`                                                                                                                                                      | Same content as `synopsis` / `cast.edges`.                                                 |
| Internal ids and SEO: `movie.id` (base64), `poster.{id,internalId,path}`, person / genre / country ids, `genres[].tag`, `data.seo`, `data.rules`, `relatedTags[].{data,tags,scope,internalId}` | Technical, no meaning for a user.                                                          |
| Release extras: `releases[].{name, releaseDate.precision, advice, companyLimitation, releaseTags}`, the releases not chosen                                                                    | Technical; see Q11 (precision) and Q16 (`ReRelease`).                                      |
| `facets`, localising codes                                                                                                                                                                     | User decision: codes as given.                                                             |
| A size cap on attributes                                                                                                                                                                       | User decision. §7 gives the measured cost.                                                 |

## 2. Why our own pagination (D25)

The override `_AllocineAPIWithTimeout._get_json_request` already receives each full JSON document. Today the
library's `get_showtime` calls it and keeps only `title`, `startsAt` and `diffusionVersion`. Exploiting the rest
**without hidden state** means replacing `get_showtime` with our own loop:

- Stashing the documents on the instance (e.g. `self._last_documents`) while `get_showtime` runs is not safe.
  The 60 s `asyncio` backstop (§2 of the architecture, "cannot cancel the worker thread") abandons a thread
  that keeps running; a manual refresh (`homeassistant.update_entity`, a reload) can start a second day call on
  the same instance in another executor thread. Two threads would write the same attribute. The provider must
  keep **no per-call state on the instance**.
- `get_movies` is not an alternative: calling it as well would **double** the load, and it is fragile
  (`UnboundLocalError` when `releases` is empty, `KeyError` when `poster` or `flags` is missing, a bare `except:`
  around the credits).
- The library loop also has a latent infinite loop: it sets `page` from the response, so a response that keeps
  answering `"page": "1"` with `totalPages: 3` makes it request `p-2` for ever. Ours iterates a bounded range.

So the provider no longer calls `get_showtime`. It still uses only the library's public URL builder
(`URLs.showtime_url`) and our override of `_get_json_request` (D8): same canonical trailing-slash URL, same
honest `User-Agent` (D17), same timeouts, same error mapping, no new header, no retry, no evasion. The number of
requests per day is the number of pages, as before (3 for C0159 on 2026-11-14, 2 for W7520 on 2026-11-11).

## 3. Models (`client/models.py`) — all new fields optional (D28)

Every new field has a default, so `tests/fake_provider.py`, its helpers and any other source keep compiling and
behaving unchanged. All dataclasses stay `frozen=True, slots=True, kw_only=True` and hold only tuples, so equality
stays cheap and exact.

```python
class ShowtimeVersion(StrEnum):            # unchanged values; docstrings below
    ORIGINAL = "original"   # the film's original language, which is not the source country's
    DUBBED = "dubbed"       # dubbed into the source country's language (AlloCiné also uses it for French films, C0159)
    LOCAL = "local"         # the film's original language is the source country's (AlloCiné: LOCAL, W7520; or
                            #   ORIGINAL of a film whose languages are exactly ["FRENCH"], r.json, §4.4)
    UNKNOWN = "unknown"

@dataclass(frozen=True, slots=True, kw_only=True)
class ShowtimeFormats:
    projection: tuple[str, ...] = ()       # source codes verbatim: ("DIGITAL",), ("F_3D", "IMAX")
    picture: tuple[str, ...] = ()
    sound: tuple[str, ...] = ()
    experience: tuple[str, ...] = ()       # ("SCREEN_X", "PLF"), ("E_4DX", "PLF")
    comfort: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True, kw_only=True)
class Showtime:
    starts_at: datetime                            # unchanged
    version: ShowtimeVersion                       # unchanged
    subtitled: bool | None = None                  # CLASSIC subtitles only (not SME); None = the source does not say
    hard_of_hearing_subtitles: bool | None = None  # (D30) SME: subtitles for the deaf and hard of hearing
    disabled_access: bool | None = None            # (D30) PMR: accessible to people with reduced mobility
    audio_description: bool | None = None          # (D31) tag Showtime.Accessibility.Greta (assumed audio description)
    formats: ShowtimeFormats | None = None         # None = nothing known (never an all-empty ShowtimeFormats)
    preview: bool | None = None
    weekly_outing: bool | None = None
    ticket_url: str | None = None                  # http(s) only

@dataclass(frozen=True, slots=True, kw_only=True)
class Rating:
    score: float                           # as the source gives it (AlloCiné: 0–5)
    count: int | None = None

@dataclass(frozen=True, slots=True, kw_only=True)
class Credit:
    name: str                              # "Denis Villeneuve"
    role: str                              # the source's code, "DIRECTOR"

@dataclass(frozen=True, slots=True, kw_only=True)
class FilmDetails:
    """What the source says about the film itself. Identical for every day (§5.1)."""
    url: str | None = None
    film_type: str | None = None           # source code, "FEATURE_FILM"
    original_title: str | None = None
    year: int | None = None
    release_date: str | None = None        # verbatim, "2026-11-11"
    visa_number: str | None = None
    runtime: int | None = None             # minutes, > 0
    genres: tuple[str, ...] = ()
    certificate: str | None = None
    countries: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    directors: tuple[str, ...] = ()
    poster_url: str | None = None          # http(s) only
    synopsis: str | None = None
    synopsis_full: str | None = None       # verbatim, may contain HTML
    cast: tuple[str, ...] = ()
    credits: tuple[Credit, ...] = ()
    related_tags: tuple[str, ...] = ()
    user_rating: Rating | None = None
    user_review_count: int | None = None
    press_rating: Rating | None = None
    want_to_see_count: int | None = None
    hits: int | None = None
    sessions: int | None = None
    premiere: bool | None = None
    weekly_outing: bool | None = None
    has_trailer: bool | None = None
    flags: tuple[str, ...] = ()            # source names of the true boolean flags, "isPlayingNow", …

@dataclass(frozen=True, slots=True, kw_only=True)
class Film:
    title: str                             # unchanged
    showtimes: tuple[Showtime, ...]        # unchanged
    ref: str | None = None                 # the source's film id ("133392"); None if unknown
    details: FilmDetails | None = None     # None = no enrichment at all

# DayShowtimes: unchanged.
```

`client/__init__.py` also exports `ShowtimeFormats`, `Rating`, `Credit`, `FilmDetails`.

Invariants (the contract suite checks them, §9.2): `ref` is `None` or a non-empty string; strings in tuples are
non-empty and stripped; `runtime > 0`; `url`, `poster_url`, `ticket_url` start with `http://` or `https://`;
`formats` is `None` rather than five empty tuples; `details` is `None` rather than an all-default `FilmDetails`.

`ShowtimeVersion` keeps its four values: subtitles and accessibility are separate axes (`subtitled`,
`hard_of_hearing_subtitles`, `disabled_access`), because a dubbed or local showtime can carry them too (_La
Gradiva_: French film, `original_st`, PMR). The mapping to the `vf` / `vo` / `vost` / `other` keys and to
`accessibility` stays on the Home Assistant side (§6.2), neutral for every source (D26, D30, extending D15).

## 4. Parsing (`client/providers/allocine.py`)

### 4.1 Constants and signatures

```python
_SHOWTIME_LISTS: Final = ("original", "original_st", "original_sme", "multiple", "multiple_st", "multiple_sme")
_CLASSIC_SUBTITLE_LISTS: Final = frozenset({"original_st", "multiple_st"})
_SME_LISTS: Final = frozenset({"original_sme", "multiple_sme"})
_SUBTITLED_TAG: Final = "Showtime.Accessibility.Subtitled"        # W7520, r.json
_SUBTITLE_LANGUAGE_TAG_PREFIX: Final = "Localization.Subtitle."  # C0159: "Localization.Subtitle.French"
_DISABLED_ACCESS_SERVICE: Final = "DISABLED_ACCESS"
_DISABLED_ACCESS_TAG: Final = "Theater.Service.DisabledAccess"
_AUDIO_DESCRIPTION_TAG: Final = "Showtime.Accessibility.Greta"   # W7520; assumption, see §4.7
_FRENCH_ONLY: Final = ["FRENCH"]
_DIRECTOR: Final = "DIRECTOR"
_DESKTOP: Final = "DESKTOP"
_TICKET_PROVIDER_ORDER: Final = ("default", "relay")             # then any other DESKTOP provider, in order
_MAX_PAGES: Final = 20                    # 300 films a day; C0159 has 36 films on 3 pages
_FILM_URL: Final = "https://www.allocine.fr/film/fichefilm_gen_cfilm={ref}.html"
_RUNTIME_PATTERN: Final = re.compile(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*min)?\s*", re.ASCII)

class _AllocineAPIWithTimeout(allocineAPI):
    def _get_json_request(self, path: str, url_params: dict[str, Any] | None = None) -> dict[str, Any]: ...
        # unchanged (D8, D17), except: it no longer filters `"movie": null` results (moved to the parser, §4.3)

    def fetch_showtime_pages(self, cinema_id: str, date_str: str) -> list[dict[str, Any]]:
        """Every page of one day, in order. Local variables only: no state on the instance."""
    # fetch_showtimes (the get_showtime wrapper) is deleted.

def parse_runtime(raw: object) -> int | None: ...          # module-level, pure, unit-tested (§4.5)

class AllocineProvider(ShowtimesProvider):
    def _fetch_day_sync(self, cinema_id: str, day: date) -> DayShowtimes: ...
        # pages = self._api.fetch_showtime_pages(cinema_id, day.isoformat()); return self._convert_day(..., pages)
        # exception mapping unchanged (§3.3 of the architecture)
    def _convert_day(self, cinema_id: str, day: date, pages: list[dict[str, Any]]) -> DayShowtimes: ...
    def _convert_result(self, item: object, time_zone: ZoneInfo) -> Film | None: ...
    def _convert_showtime(self, entry: object, *, list_key: str, french_only: bool,
                          title: str, time_zone: ZoneInfo) -> Showtime: ...
    def _film_details(self, movie: dict[str, Any], ref: str | None) -> FilmDetails | None: ...
    def _showtime_extras(self, entry: dict[str, Any], list_key: str) -> dict[str, Any]: ...   # subtitles, PMR, …
```

Exact private names follow the implementation; the behaviour below does not.

### 4.2 Pagination (`fetch_showtime_pages`)

```
first = self._get_json_request(URLs.showtime_url(cinema_id, date_str, 1))
total = _page_number(first["pagination"]["totalPages"])
if total > _MAX_PAGES → SourceParseError("implausible pagination")        (no further request)
check _page_number(first["pagination"]["page"]) == 1
pages = [first]
for n in range(2, total + 1):
    doc = self._get_json_request(URLs.showtime_url(cinema_id, date_str, n))
    check _page_number(doc["pagination"]["page"]) == n                      (else SourceParseError)
    pages.append(doc)
return pages
```

- `_page_number` accepts an `int` (not a `bool`) or a decimal string: **`pagination.page` is a string**
  (`"1"`, `"2"`, `"3"` in all three captures), `totalPages` an int. Anything else, a negative value, or
  `pagination` missing or not an object → `SourceParseError`.
- `totalPages == 0` (empty day: `error: true`, `message: "no.showtime.error"`, `results: []`) → the single first
  page is returned, and the day is empty (valid data). The request count is exactly the library's: one per page.
- The URL is `URLs.showtime_url(...)`; the override appends the trailing slash (D17). The page check makes a
  server that repeats page 1 an error instead of a loop.
- `error` / `message` are not interpreted, as today: an empty `results` is an empty day whatever the message.

**Signature guard for `URLs.showtime_url` (client test, next to the `_get_json_request` one, §8.1 of the
architecture).** It is a public static method of the pinned library; a bump that changes it must fail a test:

- `inspect.getattr_static(URLs, "showtime_url")` is a `staticmethod`;
- `list(inspect.signature(URLs.showtime_url).parameters)` == `["id_cinema", "date_str", "page"]`, each
  `POSITIONAL_OR_KEYWORD` with no default (compare names, kinds and defaults, not `Signature` objects);
- `URLs.showtime_url("C0159", "2026-11-14", 3) == "https://www.allocine.fr/_/showtimes/theater-C0159/d-2026-11-14/p-3"`
  exactly (pins the format; the override's slash is tested separately);
- `allocineAPI.get_showtime` and `allocineAPI.get_movies` are never called by a day fetch (patch both to raise).

### 4.3 Results, the six lists, de-duplication

For each page, in order, for each item of `results` (missing or not a list → `SourceParseError`):

1. Not an object → `SourceParseError`. `"movie": null` (non-film event, never seen in the three captures but
   known from the library's code) → skipped, one debug line with the count per day.
2. **Required, as today** (→ `SourceParseError`, the day is then left out per D20): `movie` is an object;
   `movie.title` a non-blank string; `showtimes` an object; every showtime entry an object with a valid
   `startsAt`. Nothing else is required.
3. `ref = str(movie.internalId)` when it is an `int` > 0 (not `bool`) or a string of digits; else `None` + debug.
4. Showtime lists: the six known keys **in the order of `_SHOWTIME_LISTS`**, then any other key of `showtimes`
   whose value is a list, in document order (debug once per unknown key and day). A `null` list counts as empty.
   A known key holding something else than a list or `null` → `SourceParseError` (the shape changed). The six
   keys are present (mostly as `[]`) on every result of the captures.
5. **De-duplication by showtime `internalId`, per film**, as the library did: the first occurrence wins, except
   the four flags `subtitled`, `hard_of_hearing_subtitles`, `disabled_access` and `audio_description`, each the OR of every
   occurrence (`True` if any is `True`; else `False` if any is `False`; else `None`). An entry with no usable
   `internalId` is kept, never merged. (No duplicate was seen in the captures; the rule is the library's.)
6. **Same film twice in a day** (same `ref`, e.g. on two pages): one `Film`; showtimes merged with step 5's rule;
   `title` and `details` from the first occurrence; debug line. Films with `ref is None` are never merged.
7. A film left with no showtime is dropped (as today). Films sorted by `title.casefold()`, showtimes by
   `starts_at` (as today). Two showtimes at the same minute are both kept (_Ramayana_ has two at 13:45 in two
   rooms, W7520).

### 4.4 Versions and classic subtitles: VF / VO / VOST and the French rule (D2 revised, D26)

**Three conventions coexist, depending on the cinema** (§0):

| Capture | VOST showtimes                                                                  | VF showtimes of French films                                | VF of dubbed films             |
| ------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------ |
| r.json  | (French film) `original_st`, `ORIGINAL`, tag `Showtime.Accessibility.Subtitled` | `ORIGINAL` in `original_st` (_La Gradiva_)                  | —                              |
| C0159   | `original`, `ORIGINAL`, tag **`Localization.Subtitle.French`**                  | `multiple`, **`DUBBED`**, tag `Localization.Version.French` | `multiple`, `DUBBED`, same tag |
| W7520   | **`original_st`**, `ORIGINAL`, tag **`Showtime.Accessibility.Subtitled`**       | `multiple`, **`LOCAL`**, tag `Localization.Language.French` | `multiple`, `DUBBED`           |

So neither the list nor one tag alone identifies subtitles, and neither `LOCAL` nor `DUBBED` alone identifies a
French film. The rules below accept every convention seen.

**Version.** `french_only` is true when the raw `movie.languages` is a list equal to **exactly** `["FRENCH"]`
(user decision; `["ENGLISH","KOREAN"]` or a French co-production are not reclassified). The rule applies to
`ORIGINAL` showtimes only: dubbed showtimes of English films keep `DUBBED`, and French films labelled `DUBBED`
(C0159) or `LOCAL` (W7520) are already VF.

| `diffusionVersion` | `french_only`                          | `version`                                   | Real case                                |
| ------------------ | -------------------------------------- | ------------------------------------------- | ---------------------------------------- |
| `LOCAL`            | any                                    | `LOCAL`                                     | W7520, 13 showtimes (_Mochy_, _Karma_ …) |
| `DUBBED`           | any                                    | `DUBBED`                                    | C0159 97, W7520 34                       |
| `ORIGINAL`         | true                                   | **`LOCAL`**                                 | r.json only (_La Gradiva_)               |
| `ORIGINAL`         | false (other languages, or unreadable) | `ORIGINAL`                                  | C0159 64, W7520 19                       |
| anything else      | any                                    | `UNKNOWN` (one warning per value, as today) | none                                     |

The French rule is exercised by r.json only: in C0159 and W7520 every `["FRENCH"]` film is `DUBBED` or `LOCAL`.

**Classic subtitles (`subtitled`).** `True` when **any** of:

- the entry came from `original_st` or `multiple_st` (W7520, r.json);
- its `tags` contain `Showtime.Accessibility.Subtitled` (W7520, r.json);
- its `tags` contain a tag starting with `Localization.Subtitle.` (C0159: `Localization.Subtitle.French`).

Otherwise `False` when the entry came from `original` or `multiple` (C0159's VF, W7520's VF), `None` from an
unknown list key. **Entries from `original_sme` / `multiple_sme` are never `subtitled`**, whatever their tags:
those subtitles are SME (§4.7), and the user wants `vost` to mean classic subtitles only.

Home Assistant side (§6.2): `vf` = `DUBBED` + `LOCAL` (subtitled or not); `vost` = `ORIGINAL` with
`subtitled is True`; `vo` = `ORIGINAL` otherwise (`False` or `None`), including an `ORIGINAL` showtime that only
has SME subtitles (it is listed in `accessibility.sme`); `other` = `UNKNOWN`. With the three captures: C0159
64 `vost`, 97 `vf`, 0 `vo`; W7520 19 `vost`, 47 `vf`, 0 `vo`; r.json 1 `vf`. **No real `vo` showtime has been
seen**; it is covered by an invented fixture (§9.1).

An unreadable `languages` only disables the French rule (debug), it never fails the day.

### 4.5 Runtime

`parse_runtime(raw)`: a `str` that fully matches `_RUNTIME_PATTERN` with at least one group → `h * 60 + min`;
the result must be > 0. Everything else → `None`, with a debug line except for `None` / absent.

| Input                        | Result                       | Real case                                                                                       |
| ---------------------------- | ---------------------------- | ----------------------------------------------------------------------------------------------- |
| `"2h 25min"`                 | 145                          | _La Gradiva_                                                                                    |
| `"3h 15min"`                 | 195                          | _Ramayana_ (W7520)                                                                              |
| `"2h 01min"`, `"2h 00min"`   | 121, 120                     | C0159, W7520 (zero-padded minutes)                                                              |
| `"0h 49min"`                 | 49                           | _Peppa fête Noël_ (W7520)                                                                       |
| **`"0h 00min"`**             | **`None`**                   | **real**: _Ce qui nous mène à toi_, _Les Yeux Verts_ (C0159), _Kraken_ (W7520): unknown runtime |
| `"2h25min"`, `" 2h  25min "` | 145                          | invented                                                                                        |
| `"45min"`, `"2h"`            | 45, 120                      | invented                                                                                        |
| absent, `None`, `""`         | `None`                       | invented                                                                                        |
| `"1h30"`, `"145"`, `"abc"`   | `None` (debug)               | invented                                                                                        |
| `145` (int), `2.5`, `[]`     | `None` (debug: unknown unit) | invented                                                                                        |

### 4.6 Other extractors (each returns `None` / `()` on any mismatch, debug line)

- Strings: `str`, stripped, non-empty (`synopsis: ""` → `None`). Tuples of strings: a list; non-string or blank
  items skipped; order kept; duplicates removed.
- `url`: built only when `ref` is set. `poster_url`, `ticket_url`: kept **verbatim** when `urlsplit` gives scheme
  `http`/`https` and a host; anything else (`javascript:`, relative) → `None`. We never re-encode a URL (the
  `relay` URLs contain raw spaces: `…&code=VO; SUBTITLE`).
- **`ticket_url`** (user decision: one DESKTOP link). Every showtime of the two full days has several DESKTOP
  entries, so "DESKTOP" alone does not choose:

  | Provider  | What the URL is (seen)                                                                                                                         | C0159 | W7520 | r.json |
  | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ----- | ------ |
  | `default` | the cinema chain's own booking page, in French: `https://www.ugc.fr/reservationSeances.html?id=…`, `https://s.pathe.fr/fr/<session>/booking?…` | 161   | 66    | —      |
  | `relay`   | AlloCiné's redirector `https://relay.mvtx.us/ticketing/dbz?code_theater=…&perft=20:30&code=VO; SUBTITLE`, with raw spaces                      | 161   | 66    | 1      |
  | `en`      | the same Pathé page in English: `https://s.pathe.fr/en/<session>/booking?…`                                                                    | —     | 66    | —      |

  Rule: among the entries with `type == "DESKTOP"`, take the first one whose `provider` is `default`, else
  `relay`, else any other DESKTOP provider in document order; its first valid http(s) URL; if that entry has
  none, try the next candidate. No DESKTOP entry, no `ticketing`, or no valid URL → `ticket_url = None`, no error.
  Reasons: `default` is the direct booking page, in French, a well-formed URL; `relay` is a redirect that goes
  through a third party and is not well formed; `en` duplicates `default` in English. r.json (only `relay`) shows
  the fallback. Q13 asks the user to confirm.

- **Releases.** `releases[]` can hold one item (most films) or 54 (_Dune_: `Released`, `ReRelease`, `Vod`, `Svod`,
  `BluRay` …). The certificate, date and visa must come from the **same** release:
  1. the chosen release is the first item with a non-empty `visaNumber` (the cinema exploitation visa; for _Dune_
     the `ReRelease` of 2026-11-11, visa `155420`, "Tout public");
  2. from it: `visa_number` (string; an `int` is converted with `str`), `release_date` (`releaseDate.date`
     verbatim), `certificate` (`label`, else `code`);
  3. if no item has a visa (_Ramayana_, W7520), each of the three is taken from the first item that has it
     (`release_date` `2026-11-06`, `certificate` "Tout public avec avertissement", `visa_number` `None`).
     `releases` empty or missing → all `None` (the case that crashes `get_movies`). Real counts: certificate present
     for 35 of 36 films in C0159 (not _Comment braquer une banque_) and 24 of 26 in W7520 (not _Comment braquer une
     banque_, _Peppa fête Noël_).
- `film_type`: `movie.type`, a non-empty string, verbatim code.
- `year`: `data.productionYear`, an `int` in 1870…2100.
- Ratings: `score` an `int`/`float` (not `bool`) in 0…5 → `Rating(score=float(score), count=…)`; `count` an
  `int` ≥ 0 or `None`. No score (`{"score": null, "count": null}`, _Peppa_) or `pressReview: null` → `None`.
- Counters (`user_review_count` ← `stats.userReview.count`, `want_to_see_count`, `hits` ← `stats.metric.hits`,
  `sessions` ← `stats.metric.sessions`): an `int` ≥ 0 (not `bool`); `null` → `None`.
- Names: `f"{firstName} {lastName}".strip()` from whichever parts are strings; empty → skipped.
- `credits`: one `Credit` per readable item with a `position.name`; `directors` = their names for `DIRECTOR`.
- `cast`: for each `cast.edges[].node`, in the order received: the name of `actor`, else of
  `originalVoiceActor`, else of `voiceActor`; a node with none is skipped. Animated films have `actor: null` and
  the original voice in `originalVoiceActor` (_Le Corset_: Gary Clichy; 4 films in C0159, 5 in W7520). AlloCiné
  sends 3 at most; `nodes` duplicates `edges` and is ignored.
- `related_tags`: `relatedTags[].name` only (can be `[]`: _Comment braquer une banque_, _Ramayana_). The raw array
  is ~7 KB for 10 tags because of each tag's `data.seo` blob; the names are ~300 bytes.
- Booleans (`premiere`, `weekly_outing`, `has_trailer`, `preview`, …): only real `bool` values; anything else
  `None`.
- `flags`: the keys of `movie.flags` whose value is exactly `True`, in document order, verbatim (camelCase source
  names, e.g. `hasNews`, `hasShowtime`, `hasTheaterRelease`, `isPlayingNow`, `hasTrailer`, `tvRelease`).
  Non-boolean entries are ignored; `has_trailer` stays a field of its own as well.
- `synopsis_full`: the string as received, HTML included, only stripped of surrounding whitespace. Not cleaned,
  sanitised or converted. It is usable as is in a Markdown card (which renders and sanitises basic HTML); in
  plain-text uses the tags show. It is not redundant: _Ramayana_ (W7520) has `synopsis: ""` and only a full
  synopsis, and C0159's `synopsis` is often a shortened version.
- `formats`: each of `projection`, `picture`, `sound`, `experience`, `comfort` a list of codes (`null` → `()`); all
  five empty → `formats = None`.
- `details`: `None` when every field came out empty (§3 invariant).

### 4.7 Accessibility: PMR, SME (D30) and audio description (D31)

Derived per showtime; the raw `tags` and `service` are not exposed.

**PMR (`disabled_access`).** What the captures show (434 showtimes):

| Capture | `service: ["DISABLED_ACCESS"]` | tag `Theater.Service.DisabledAccess` | tag `Showtime.Accessibility.Accessible` |
| ------- | ------------------------------ | ------------------------------------ | --------------------------------------- |
| r.json  | 1 / 1                          | 1, on the same showtime              | 0                                       |
| C0159   | 145 / 161 (16 `null`)          | 145, exactly the same showtimes      | 133, all among the 145                  |
| W7520   | 48 / 66 (18 `null`)            | 48, exactly the same showtimes       | **66, all of them**                     |

So `service` and the `Theater.Service.DisabledAccess` tag always agree, and `Showtime.Accessibility.Accessible`
is something else (it is on non-PMR showtimes in W7520, and missing from PMR ones in C0159: _Scrooge_, _15/18_).
PMR varies within a film (_Ramayana_: 3 of 6 showtimes, W7520) and per film (_Moulin_, _L'Affaire Marie-Claire_,
_Digger_ have none, C0159): it is a property of the room, so it is kept per showtime.

Definition: `disabled_access = True` when `service` is a list containing `"DISABLED_ACCESS"` **or** `tags`
contains `"Theater.Service.DisabledAccess"`; `False` when the `service` key is present as a list without it or as
`null` (AlloCiné's empty list, as for the formats) and the tag is absent; `None` when the key is missing or has
another type and the tag is absent. `Showtime.Accessibility.Accessible` is **not** used (Q14).

**SME (`hard_of_hearing_subtitles`).** No capture has an SME showtime: the `original_sme` / `multiple_sme` lists
are present but always `[]`, and no tag names subtitles for the deaf and hard of hearing. What is known is only
that these lists exist. So: `True` when the entry came from `original_sme` or `multiple_sme`; `False` when it came
from one of the four other known lists; `None` for an unknown key.
No tag is read (we do not guess one). Until AlloCiné is seen to signal SME, `accessibility.sme` is always
empty on real data, and the SME path is tested on an invented fixture only.

**Audio description (`audio_description`, D31, user decision).** `True` when `tags` contains
`Showtime.Accessibility.Greta`; `False` when `tags` is a list without it; `None` when `tags` is missing or not
a list. Seen only in W7520: 16 showtimes of 6 films (_Clayface_ ×6, _L'île des souvenirs_ ×4, _Malfaisante_ ×3,
_Ducobu et le fantôme de Saint-Potache_, _Karma_, _Les Misérables_ ×1), independent of PMR (10 of the 16 are PMR);
none in C0159 or r.json. **"Greta = audio description" is an assumption** (Greta is the name of a smartphone app
used in French cinemas for audio description and also SME subtitles); no official AlloCiné source confirms it.
The field name says what we believe it means; if AlloCiné turns out to use the tag for SME, only this mapping
changes (Q15).

**The `relay` URL's `code=` string is not used**, for any of the three. Checked against the tags: at W7520 it
contains `GRETA` exactly on the 16 Greta-tagged showtimes and never `AUDIO` or `SME` (redundant with the tag);
at C0159 it contains `SME` on 131/161, `AUDIO` on 137/161 and `GRETA` on 45/161 showtimes, with no
corresponding tag, i.e. the chain's booking codes, too broad to be per-showtime facts (unreliable). It is also a
third-party URL's query string, the most fragile place to read from. Tags stay the only source; **SME therefore
remains undetectable on real data** (Q10).

De-duplication merges the three accessibility flags with OR (§4.3 step 5). None can fail a day (§4.8).

### 4.8 Never fail a day because of enrichment (D28)

`_film_details` and `_showtime_extras` are built from `isinstance` checks and never raise on data. As a safety
net, each is wrapped: `except (KeyError, TypeError, ValueError, AttributeError, IndexError)` → that object's
enrichment is `None` (film) or default (showtime), one debug line naming the film. **No enrichment path raises
`SourceParseError`**: otherwise one odd field would invalidate the whole day (D20) and hide its showtimes. Only
§4.3's required fields can fail a day, exactly as before this change. Logging is debug only (not warning), since
nothing visible breaks.

## 5. Data flow

### 5.1 Film data is the same for every day: where it is merged

AlloCiné repeats the full `movie` object in every day's document (and across cinemas: _Dune_, _Comment braquer
une banque_, _Scrooge_ … appear in both C0159 and W7520 with the same film data; each entry has its own store, so
nothing is shared across entries). Three merges, each in one place:

1. **Within a day** (pages, duplicates): in the provider, §4.3 step 6.
2. **Across the days of the coordinator's data**: `store.unify_film_details(days) -> tuple[dict[date, CachedDay], dict[str, FilmDetails]]`,
   a pure function in `store.py`. For each `ref`, the details of the film on the day with the **latest
   `fetched_at`** win (tie: earliest date). Every `Film` with that `ref` then carries that same object
   (`dataclasses.replace` only where it differs, so unchanged days keep their identity). It returns the unified
   days and the catalogue. The coordinator calls it at the end of `_async_update_data`, on the merged result
   (fresh days + kept days, §12.4 of the architecture), **before** saving and returning: memory and store stay
   identical (§12.4 invariant), and a refetched film replaces the old details on the days kept from earlier.
3. **In the store file**: the catalogue holds each film's details once (§5.2).

Films with `ref is None` (fake provider, a source without film ids) are not unified; their `details`, if any, stay
on the film. Showtime-level data (subtitles, PMR, SME, formats, booking link) belongs to the day and is never
unified.

### 5.2 Store: film catalogue, purge by construction (D27)

`STORAGE_VERSION` stays `1`, `STORAGE_MINOR_VERSION` stays `1`: nothing has been released (D27). The schema simply
changes. Example from W7520, 2026-11-11, one film (_Dune_), long values shortened with `…`:

```json
{
  "source": "allocine",
  "cinema_id": "W7520",
  "last_refresh": "2026-11-11T06:00:12.345678+00:00",
  "films": {
    "133392": {
      "url": "https://www.allocine.fr/film/fichefilm_gen_cfilm=133392.html",
      "film_type": "FEATURE_FILM",
      "original_title": "Dune",
      "year": 2021,
      "release_date": "2026-11-11",
      "visa_number": "155420",
      "runtime": 156,
      "genres": ["Science Fiction", "Drame"],
      "certificate": "Tout public",
      "countries": ["U.S.A."],
      "languages": ["ENGLISH"],
      "directors": ["Denis Villeneuve"],
      "poster_url": "https://fr.web.img6.acsta.net/pictures/21/08/10/12/20/4633954.jpg",
      "synopsis": "L'histoire de Paul Atreides, voué à connaître un destin hors du commun …",
      "synopsis_full": "<p class=\"bo-p\">L'histoire de Paul Atreides, jeune homme aussi doué que brillant, …</p>",
      "cast": ["Timothée Chalamet", "Rebecca Ferguson", "Oscar Isaac"],
      "credits": [{ "name": "Denis Villeneuve", "role": "DIRECTOR" }],
      "related_tags": ["Empereur / Impératrice", "Planètes", "…"],
      "user_rating": { "score": 4.23, "count": 35815 },
      "user_review_count": 2441,
      "press_rating": { "score": 3.95, "count": 40 },
      "want_to_see_count": 15595,
      "hits": 10451762,
      "sessions": 4761277,
      "premiere": false,
      "weekly_outing": true,
      "has_trailer": true,
      "flags": ["hasDvdRelease", "hasNews", "…", "tvRelease", "hasTrailer"]
    }
  },
  "days": [
    {
      "date": "2026-11-11",
      "fetched_at": "2026-11-11T06:00:12.345678+00:00",
      "films": [
        {
          "title": "Dune",
          "ref": "133392",
          "showtimes": [
            {
              "starts_at": "2026-11-11T17:30:00+01:00",
              "version": "dubbed",
              "subtitled": false,
              "hard_of_hearing_subtitles": false,
              "disabled_access": false,
              "audio_description": false,
              "formats": {
                "projection": ["DIGITAL"],
                "experience": ["E_4DX", "PLF"]
              },
              "preview": false,
              "weekly_outing": true,
              "ticket_url": "https://s.pathe.fr/fr/V3168S188133/booking?utm_source=allocine&…"
            },
            {
              "starts_at": "2026-11-11T17:45:00+01:00",
              "version": "original",
              "subtitled": true,
              "hard_of_hearing_subtitles": false,
              "disabled_access": false,
              "audio_description": false,
              "formats": { "projection": ["IMAX"] },
              "preview": false,
              "weekly_outing": true,
              "ticket_url": "https://s.pathe.fr/fr/V3168S188130/booking?utm_source=allocine&…"
            }
          ]
        }
      ]
    }
  ]
}
```

- Keys are the model's field names. `None`, empty tuples and `formats: None` are **omitted**; `false` is written.
  A film without `ref` but with `details` writes them inline as `"details": {…}` (same shape as a catalogue entry).
- **Purge, at every save, in this order** (`snapshot_to_dict`):
  1. Only the days kept by the coordinator are given: fresh days and failed days whose previous copy is still
     usable (`is_day_usable`, D18); then `snapshot_to_dict` writes only `date >= today` (unchanged). Past and
     too-old days are gone.
  2. **The catalogue is rebuilt from scratch** from the refs of the films of the written days (every film has at
     least one showtime, so "referenced by a film" = "referenced by a showtime"). Nothing else is ever in it, so
     it cannot accumulate: a film that left every kept day leaves the catalogue at the same save.
  3. A refetched film's details replace the old ones (unification, §5.1).
  4. A day that failed to parse keeps its previous copy (§12.4), so its films and their details stay.
- **Load** (`snapshot_from_dict`, still strict on structure):
  - the `films` object is **required** (an object, possibly empty); a missing one rejects the snapshot like any
    malformed store. That is how a store written before this change is handled: one warning, nothing restored, one
    refresh. No reading code for the old format (D27);
  - a catalogue entry that is not an object, or a field of the wrong type → `ValueError`: the whole snapshot is
    rejected, as for every other malformed value (we wrote it; partial recovery is not worth its code, §12.2);
  - a day film whose `ref` is **absent from the catalogue** → loaded with `details=None`, **one debug line**; it
    does not fail the load (the film shows without enrichment until the next refresh);
  - a catalogue entry **referenced by no film** → ignored (debug);
  - `ref` present but not a non-empty string → `ValueError`.
  - Per-showtime keys optional: absent → model default. `version` strict as today.
- Restored `Film`s with the same `ref` share one `FilmDetails` object (built once from the catalogue).

### 5.3 Restart

Unchanged (D12): a fresh store restores days + catalogue with no request; a stale one refreshes. Details come back
with the films, so the attributes after a restart equal those before it. Measured on the captures, the parsed film
data is ~1.1 KB per film (C0159: 36 films ≈ 39 KB of details, W7520: 26 films ≈ 27 KB) and the showtimes ~0.3 KB
each; with the catalogue, a week of a 36-film cinema is roughly 40 KB of films + 8 × 50 KB of showtimes, written
twice a day.

### 5.4 Coordinator and `always_update=False`

Request count unchanged: 8 `async_get_day` calls per refresh, each one request per page. The only new call is
`unify_film_details` (§5.1).

`always_update=False` makes the coordinator skip the listener update when the new `data` equals the old. **It
already never skipped after a successful refresh**: each `CachedDay.fetched_at` is the refresh time, so the data
always differs. Ratings and counters that move between fetches (`hits` and `sessions` change at every fetch,
rating and review counts often: _La Gradiva_ 1 610 ratings on 2026-11-12 in r.json, 1 615 in C0159) therefore
change nothing: the entities were already re-rendered after every successful refresh, and `fetched_at` already
changed the attributes. The recorder is not affected (§7).

### 5.5 Rendering

`remaining_films` uses `dataclasses.replace(film, showtimes=kept)`: `ref` and `details` are carried along with
no change. The sensor builds `films` with `film_attributes(film)` from the remaining films, as today.

## 6. Attributes (`showtimes.film_attributes`, `const.py`)

### 6.1 Shape

The sensor's top level is unchanged: `date`, `fetched_at`, `films`. Each item of `films`:

- **always present**: `title`, `vf`, `vo`, `vost` (lists of `HH:MM`, possibly empty), **`accessibility` with
  `pmr`, `sme` and `audio_description`** (lists of `HH:MM`, possibly empty), and `details` with `details.showtimes` (never empty:
  a remaining film has at least one showtime). Always present so that a template can write
  `film.accessibility.pmr` or `film.vost` without testing for the key;
- `other`: only when the film has `UNKNOWN` showtimes (unchanged rule);
- every other key: **omitted when `None` or empty**; booleans are written when known, `false` included.

`accessibility.pmr` lists the remaining showtimes with `disabled_access is True`; `accessibility.sme` those with
`hard_of_hearing_subtitles is True`, `accessibility.audio_description` those with `audio_description is True`. An empty list means "none known": the per-showtime `pmr` / `sme` keys tell
`false` (said by the source) from absent (unknown). Two showtimes at the same minute give the same `HH:MM` twice.

**Real examples**, Home Assistant in `Europe/Paris`, rendered before the first showtime of the day. They are the
output of the rules above applied to the captures (computed outside the repository). `synopsis_full` values are
shortened with `…` here only; in the attribute they are complete.

From **C0159, 2026-11-14**:

1. _Comment braquer une banque_: VOST in `original` with `Localization.Subtitle.French`; no certificate, no press
   rating, no related tags (keys omitted).

```json
{
  "title": "Comment braquer une banque",
  "vf": [],
  "vo": [],
  "vost": ["08:55", "11:25", "14:00", "16:40", "19:20", "21:55"],
  "accessibility": {
    "pmr": ["08:55", "11:25", "14:00", "16:40", "19:20", "21:55"],
    "sme": [],
    "audio_description": []
  },
  "film_id": "1000020289",
  "url": "https://www.allocine.fr/film/fichefilm_gen_cfilm=1000020289.html",
  "poster": "https://fr.web.img4.acsta.net/img/12/bb/12bb4f199e78e6b5d5d1bcbcbe702acb.jpg",
  "film_type": "FEATURE_FILM",
  "original_title": "How To Rob A Bank",
  "year": 2026,
  "release_date": "2026-11-11",
  "visa_number": "168593",
  "runtime": 121,
  "genres": ["Action", "Thriller", "Policier"],
  "countries": ["U.S.A."],
  "languages": ["ENGLISH"],
  "directors": ["David Leitch"],
  "user_rating": 2.79,
  "user_rating_count": 7,
  "user_review_count": 5,
  "want_to_see_count": 416,
  "hits": 35758,
  "sessions": 24958,
  "premiere": false,
  "weekly_outing": true,
  "has_trailer": true,
  "flags": [
    "hasNews",
    "hasPreview",
    "hasShowtime",
    "hasTheaterRelease",
    "isPlayingNow",
    "hasTrailer"
  ],
  "details": {
    "synopsis": "Une équipe de braqueurs filme ses hold-up en direct et devient viral. Mais leur célébrité grandissante attire l'attention d'un agent du FBI et d'une ingénieure informatique déterminés à les arrêter. Alors que cet improbable duo se rapproche dangereusement d’eux, le gang décide de tout miser sur le braquage le plus ambitieux de leur carrière.",
    "synopsis_full": "<p class=\"bo-p\">Une équipe de braqueurs filme ses hold-up en direct et devient viral. …</p>",
    "cast": ["Nicholas Hoult", "Pete Davidson", "Zoë Kravitz"],
    "credits": [{ "name": "David Leitch", "role": "DIRECTOR" }],
    "showtimes": [
      {
        "time": "08:55",
        "starts_at": "2026-11-14T08:55:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854687&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "11:25",
        "starts_at": "2026-11-14T11:25:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854694&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "14:00",
        "starts_at": "2026-11-14T14:00:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854680&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "16:40",
        "starts_at": "2026-11-14T16:40:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854661&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "19:20",
        "starts_at": "2026-11-14T19:20:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854668&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "21:55",
        "starts_at": "2026-11-14T21:55:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854675&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      }
    ]
  }
}
```

2. _Le Corset_: a French animated film, VF only (`DUBBED` in `multiple`), cast from `originalVoiceActor`.

```json
{
  "title": "Le Corset",
  "vf": ["09:10", "11:20", "13:30", "15:40", "17:50", "20:05"],
  "vo": [],
  "vost": [],
  "accessibility": {
    "pmr": ["09:10", "11:20", "13:30", "15:40", "17:50", "20:05"],
    "sme": [],
    "audio_description": []
  },
  "film_id": "321790",
  "url": "https://www.allocine.fr/film/fichefilm_gen_cfilm=321790.html",
  "poster": "https://fr.web.img3.acsta.net/img/a7/96/a796a67caa5bdab1508d9207abaf5284.jpg",
  "film_type": "FEATURE_FILM",
  "original_title": "Le Corset",
  "year": 2026,
  "release_date": "2026-10-14",
  "visa_number": "159399",
  "runtime": 91,
  "genres": ["Animation", "Famille"],
  "certificate": "Tout public",
  "countries": ["France", "Belgique"],
  "languages": ["FRENCH"],
  "directors": ["Louis Clichy"],
  "user_rating": 4.38,
  "user_rating_count": 1756,
  "user_review_count": 259,
  "press_rating": 4.28,
  "press_rating_count": 39,
  "want_to_see_count": 1924,
  "hits": 649703,
  "sessions": 329678,
  "premiere": false,
  "weekly_outing": false,
  "has_trailer": true,
  "flags": [
    "hasNews",
    "hasShowtime",
    "hasTheaterRelease",
    "hasTrivia",
    "hasAwards",
    "isLesIndes",
    "isPlayingNow",
    "hasTrailer"
  ],
  "details": {
    "synopsis": "Dans une ferme au cœur de la Beauce, Christophe, 11 ans, règle ses pas sur ceux de son père. Mais à l’école, à la maison, sur le tracteur, Christophe penche... et tombe. Il est obligé de porter un corset pour filer droit.",
    "synopsis_full": "<p class=\"bo-p\">Dans une ferme au cœur de la Beauce, … Il découvre la musique et fait la rencontre de Clara, avec qui tout semble devenir possible.</p>",
    "cast": ["Gary Clichy", "Rod Paradot", "Brune Moulin"],
    "credits": [{ "name": "Louis Clichy", "role": "DIRECTOR" }],
    "related_tags": [
      "CANNES_2026",
      "Premier amour",
      "Parcours initiatique",
      "Animation à la française",
      "AFCAE : Label Jeune Public",
      "Enfance / Enfant",
      "À partir de 6 ans",
      "Art et essai"
    ],
    "showtimes": [
      {
        "time": "09:10",
        "starts_at": "2026-11-14T09:10:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": false,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171855013&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "11:20",
        "starts_at": "2026-11-14T11:20:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": false,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171855021&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "13:30",
        "starts_at": "2026-11-14T13:30:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": false,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171855027&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "15:40",
        "starts_at": "2026-11-14T15:40:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": false,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171855034&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "17:50",
        "starts_at": "2026-11-14T17:50:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": false,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854977&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      },
      {
        "time": "20:05",
        "starts_at": "2026-11-14T20:05:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": false,
        "ticket_url": "https://www.ugc.fr/reservationSeances.html?id=330171854984&part=all&mtm_source=allocine&mtm_medium=affiliate&mtm_campaign=site_allocine"
      }
    ]
  }
}
```

From **W7520, 2026-11-11**:

3. _Dune_: VOST in IMAX (`original_st`, `Showtime.Accessibility.Subtitled`) and VF in 4DX + PLF; release chosen
   among 54 (the `ReRelease` with a visa); neither showtime is PMR (`service: null`).

```json
{
  "title": "Dune",
  "vf": ["17:30"],
  "vo": [],
  "vost": ["17:45"],
  "accessibility": { "pmr": [], "sme": [], "audio_description": [] },
  "film_id": "133392",
  "url": "https://www.allocine.fr/film/fichefilm_gen_cfilm=133392.html",
  "poster": "https://fr.web.img6.acsta.net/pictures/21/08/10/12/20/4633954.jpg",
  "film_type": "FEATURE_FILM",
  "original_title": "Dune",
  "year": 2021,
  "release_date": "2026-11-11",
  "visa_number": "155420",
  "runtime": 156,
  "genres": ["Science Fiction", "Drame"],
  "certificate": "Tout public",
  "countries": ["U.S.A."],
  "languages": ["ENGLISH"],
  "directors": ["Denis Villeneuve"],
  "user_rating": 4.23,
  "user_rating_count": 35815,
  "user_review_count": 2441,
  "press_rating": 3.95,
  "press_rating_count": 40,
  "want_to_see_count": 15595,
  "hits": 10451762,
  "sessions": 4761277,
  "premiere": false,
  "weekly_outing": true,
  "has_trailer": true,
  "flags": [
    "hasDvdRelease",
    "hasNews",
    "hasOnlineProduct",
    "hasOnlineRelease",
    "hasPhysicalProduct",
    "hasShowtime",
    "hasTheaterRelease",
    "hasTrivia",
    "hasAwards",
    "isLesIndes",
    "isPlayingNow",
    "tvRelease",
    "hasTrailer"
  ],
  "details": {
    "synopsis": "L'histoire de Paul Atreides, voué à connaître un destin hors du commun qui le dépasse totalement. Car s'il veut préserver l'avenir de sa famille et de son peuple, il devra se rendre sur la planète la plus dangereuse de l'univers.",
    "synopsis_full": "<p class=\"bo-p\">L'histoire de Paul Atreides, jeune homme aussi doué que brillant, … seuls ceux qui parviennent à dominer leur peur pourront survivre…</p>",
    "cast": ["Timothée Chalamet", "Rebecca Ferguson", "Oscar Isaac"],
    "credits": [{ "name": "Denis Villeneuve", "role": "DIRECTOR" }],
    "related_tags": [
      "Empereur / Impératrice",
      "Planètes",
      "Trahison",
      "Vengeance",
      "Anticipation / Futur / Avenir proche",
      "Espace / Astronaute / Cosmonaute",
      "Effets spéciaux / Trucages",
      "Alien / Extraterrestre",
      "Adaptation de roman",
      "Blockbusters / Superproductions",
      "Désert",
      "Space-Opera",
      "Monstre et monstre marin",
      "Parcours initiatique",
      "Écologie / Environnement",
      "Forces du bien contre les forces du mal",
      "Bataille / Champ de bataille",
      "Art et essai"
    ],
    "showtimes": [
      {
        "time": "17:30",
        "starts_at": "2026-11-11T17:30:00+01:00",
        "version": "vf",
        "subtitled": false,
        "sme": false,
        "pmr": false,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "experience": ["E_4DX", "PLF"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S188133/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      },
      {
        "time": "17:45",
        "starts_at": "2026-11-11T17:45:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": false,
        "audio_description": false,
        "projection": ["IMAX"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S188130/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      }
    ]
  }
}
```

4. _Ramayana : L'avènement d'une légende_: Hindi VOST in 3D, 3D + IMAX, ScreenX + PLF and digital; two showtimes
   at 13:45; PMR on 3 of 6; `synopsis: ""` (omitted) but a full synopsis; no visa (per-field release fallback); no
   press rating.

```json
{
  "title": "Ramayana : L'avènement d'une légende",
  "vf": [],
  "vo": [],
  "vost": ["13:15", "13:45", "13:45", "16:00", "20:15", "20:45"],
  "accessibility": {
    "pmr": ["13:45", "16:00", "20:45"],
    "sme": [],
    "audio_description": []
  },
  "film_id": "1000026918",
  "url": "https://www.allocine.fr/film/fichefilm_gen_cfilm=1000026918.html",
  "poster": "https://fr.web.img6.acsta.net/img/9f/94/9f9441504c3da3a4469548e15ba9cb3d.jpg",
  "film_type": "FEATURE_FILM",
  "original_title": "Ramayana: Rise Of A Legend",
  "year": 2026,
  "release_date": "2026-11-06",
  "runtime": 195,
  "genres": ["Action", "Aventure", "Fantastique"],
  "certificate": "Tout public avec avertissement",
  "countries": ["Inde"],
  "languages": ["HINDI"],
  "directors": ["Nitesh Tiwari"],
  "user_rating": 3.92,
  "user_rating_count": 78,
  "user_review_count": 18,
  "want_to_see_count": 255,
  "hits": 146711,
  "sessions": 71452,
  "premiere": false,
  "weekly_outing": true,
  "has_trailer": true,
  "flags": [
    "hasNews",
    "hasShowtime",
    "hasTheaterRelease",
    "isPlayingNow",
    "hasTrailer"
  ],
  "details": {
    "synopsis_full": "<p class=\"bo-p\">Dans l’Inde antique, le destin du jeune prince Rama bascule lorsqu’il est contraint à l’exil, peu après son mariage avec la princesse Sita. …</p>",
    "cast": ["Ranbir Kapoor", "Sai Pallavi", "Yash"],
    "credits": [{ "name": "Nitesh Tiwari", "role": "DIRECTOR" }],
    "showtimes": [
      {
        "time": "13:15",
        "starts_at": "2026-11-11T13:15:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": false,
        "audio_description": false,
        "projection": ["F_3D"],
        "experience": ["SCREEN_X", "PLF"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S189369/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      },
      {
        "time": "13:45",
        "starts_at": "2026-11-11T13:45:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": false,
        "audio_description": false,
        "projection": ["F_3D", "IMAX"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S189347/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      },
      {
        "time": "13:45",
        "starts_at": "2026-11-11T13:45:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S189372/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      },
      {
        "time": "16:00",
        "starts_at": "2026-11-11T16:00:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S189346/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      },
      {
        "time": "20:15",
        "starts_at": "2026-11-11T20:15:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": false,
        "audio_description": false,
        "projection": ["F_3D"],
        "experience": ["SCREEN_X", "PLF"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S189345/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      },
      {
        "time": "20:45",
        "starts_at": "2026-11-11T20:45:00+01:00",
        "version": "vost",
        "subtitled": true,
        "sme": false,
        "pmr": true,
        "audio_description": false,
        "projection": ["DIGITAL"],
        "preview": false,
        "weekly_outing": true,
        "ticket_url": "https://s.pathe.fr/fr/V3168S189368/booking?utm_source=allocine&utm_medium=allocine&utm_campaign=partenaire-allocine&partenaire=allocine"
      }
    ]
  }
}
```

A film from a source without enrichment (the fake provider) gives exactly:

```json
{
  "title": "Film A",
  "vf": ["15:00"],
  "vo": [],
  "vost": [],
  "accessibility": { "pmr": [], "sme": [], "audio_description": [] },
  "details": {
    "showtimes": [
      {
        "time": "15:00",
        "starts_at": "2026-11-12T15:00:00+01:00",
        "version": "vf"
      }
    ]
  }
}
```

Light keys (first level of a film) are short scalars or short lists. **Heavy ones are all under `details`**:
`synopsis`, `synopsis_full`, `cast` and `credits`, `related_tags` (up to 18 names, _Dune_), and `showtimes` with
their `ticket_url` (~120–330 B each).

### 6.2 How it is produced

```python
def attribute_version(showtime: Showtime) -> str:
    """"vf" (DUBBED, LOCAL), "vost" (ORIGINAL and subtitled is True), "vo" (ORIGINAL otherwise), "other" (UNKNOWN)."""

def film_attributes(film: Film) -> dict[str, Any]:
    """The film item above. Showtimes sorted by instant; each rendered once with
    local = dt_util.as_local(showtime.starts_at): time = local.strftime("%H:%M"), starts_at = local.isoformat()."""
```

- `HH:MM` and `starts_at` are in **Home Assistant's** time zone (D6), computed once per showtime; the same `time`
  goes into the version list, into `accessibility.pmr` / `.sme` and into `details.showtimes[]`, so they cannot
  disagree.
- `vf` / `vo` / `vost` / `other` are derived from `attribute_version`; `accessibility.pmr` from
  `disabled_access is True`, `accessibility.sme` from `hard_of_hearing_subtitles is True`, `accessibility.audio_description` from `audio_description is True`; all in instant order.
- Film-level keys come from `film.ref` and `film.details` (`poster` ← `poster_url`, `user_rating` /
  `user_rating_count` ← `user_rating.score` / `.count`, same for press). Per-showtime `projection` … `comfort`
  come from `formats`, `pmr` from `disabled_access`, `sme` from `hard_of_hearing_subtitles`.
- Names live in `const.py` as `ATTR_*` constants (`ATTR_VOST = "vost"`, `ATTR_ACCESSIBILITY = "accessibility"`,
  `ATTR_PMR = "pmr"`, `ATTR_SME = "sme"`, `ATTR_AUDIO_DESCRIPTION = "audio_description"`, `ATTR_DETAILS = "details"`, …): snake_case, stable, never translated.
  Changing one later is a breaking change for templates.

### 6.3 Templates (README material)

`state_attr('sensor.x_today', 'films') | selectattr('vost') | map(attribute='title') | list` lists the films
with a VOST showtime; `selectattr('accessibility.pmr')` those with a PMR-accessible one;
`film.details.showtimes | selectattr('version', 'eq', 'vost') | selectattr('projection', 'contains', 'IMAX')`
gives the IMAX VOST showtimes and their booking links.

## 7. Recorder and size (D29)

- The recorder (HA 2026.10.1, `db_schema.py` `StateAttributes.shared_attrs_bytes_from_event`) removes the
  entity's `_unrecorded_attributes` **by top-level key** before encoding, then drops the whole attribute set if
  it is over `MAX_STATE_ATTRS_BYTES` (16 384). `films` is in `_unrecorded_attributes` (unchanged), and every new key
  (`accessibility` included) is nested inside `films`, so the recorded attributes stay `date`, `fetched_at`
  (+ `friendly_name`; the icon comes from icon translations, not an attribute), a few dozen bytes. **The recorder
  is not touched**, however big the films get. No new top-level attribute is allowed (review point).
- The sensor is not a `RestoreEntity`: nothing goes into `core.restore_state`.
- What does grow: the state machine in memory and what is sent to the frontend. **Measured** by applying the rules
  to the captures (whole day, before the first showtime):

  | Day               | Films / showtimes | `films` attribute | light keys | details w/o showtimes | `details.showtimes` |
  | ----------------- | ----------------- | ----------------- | ---------- | --------------------- | ------------------- |
  | C0159, 2026-11-14 | 36 / 161          | **≈ 127 KB**      | 35 KB      | 39 KB                 | 53 KB               |
  | W7520, 2026-11-11 | 26 / 66           | **≈ 73 KB**       | 24 KB      | 27 KB                 | 22 KB               |

  So up to ~0.9 MB across the 7 sensors of a busy cinema (the user accepts it, no cap). On every re-render where
  `films` changes (each showtime expiry on "Today", each refresh), `subscribe_entities` sends the whole new `films`
  value of that sensor to every open frontend. The 6 sensors whose output is unchanged write the same state and
  send nothing.

- Store: §5.3.

## 8. Errors

| Situation                                                                  | Result                                                    |
| -------------------------------------------------------------------------- | --------------------------------------------------------- |
| any enrichment or accessibility field missing, `null`, wrong type          | field `None` / `()`, debug line; day OK (D28)             |
| `movie.internalId` unusable                                                | `ref=None`, no `url`, no catalogue entry, no merge; debug |
| `languages` unreadable                                                     | French rule not applied; debug                            |
| no DESKTOP ticketing entry / no valid URL                                  | `ticket_url = None`, nothing logged above debug           |
| `pagination` missing, `page` / `totalPages` not a number, page mismatch    | `SourceParseError` (day left out, D20)                    |
| `totalPages > 20`                                                          | `SourceParseError`, no further request                    |
| `results` not a list, item not an object, title / `showtimes` / `startsAt` | `SourceParseError` (unchanged)                            |
| a known showtime list neither a list nor `null`                            | `SourceParseError`                                        |
| store: no `films` catalogue (old dev file), malformed entry                | snapshot rejected, warning, refresh (unchanged path)      |
| store: ref without catalogue entry / unreferenced entry                    | film without details, debug / entry ignored, debug        |

HTTP errors, timeouts and their mapping are unchanged (D17, D19). No new translation key.

## 9. Test plan (each scope ≥ 95 % on its own)

### 9.1 Fixtures

Target directory: `tests/movie_showtimes/client/providers/fixtures/`. **Real fixtures are trimmed only by removing
keys** (never by removing array items or editing values); each test module that uses one says in its docstring
where it comes from. Keys removed from the real captures:

- top level: `facets`, `params`, `data`;
- everywhere: `__typename`, `seo`;
- `movie`: `id`, `synopsis_json`, `editorialReviews`, `cast.nodes`, `poster.{id, internalId, path}`,
  `data.rules`, `genres[].{id, tag}`, `countries[].id`, `credits[].person.internalId`,
  `credits[].position.department`, the `internalId` of cast people, `relatedTags[].{data, tags, internalId, scope}`,
  `releases[].{releaseTags, advice, companyLimitation}`;
- showtimes: `timeBeforeStart`.

Everything the parser reads stays, including `releases[]` complete (_Dune_'s 54 items: the release choice is
tested on them), the non-boolean `flags`, `service`, `tags` and every `ticketing` entry.

| Fixture                                                                                                           | Real or invented  | Content, expected size after trimming                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ----------------------------------------------------------------------------------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `allocine_C0159_2026-11-14_p1.json`, `_p2.json`, `_p3.json`                                                       | **real**, trimmed | C0159, the full day: 3 pages, 36 films, 161 showtimes. VOST via `original` + `Localization.Subtitle.French`; French films `DUBBED`; `relay` + `default` ticketing; PMR on 145; two `"0h 00min"`; a film without certificate. **≈ 127 + 107 + 25 KB minified (≈ 259 KB), ≈ 226 + 187 + 43 KB with 2-space indentation (≈ 456 KB).**                                                                                                                                                                                                                                                                                        |
| `allocine_W7520_2026-11-11_p1.json`, `_p2.json`                                                                   | **real**, trimmed | W7520, the full day: 2 pages, 26 films, 66 showtimes. VOST via `original_st` + `Showtime.Accessibility.Subtitled`; `LOCAL`; IMAX / 3D / ScreenX / PLF / 4DX; `en` + `relay` + `default` ticketing; PMR on 48; `Accessible` on 66 (ignored); `Greta` on 16 (→ `audio_description`); null ratings (_Peppa_); a release without visa. **≈ 110 + 48 KB minified (≈ 157 KB), ≈ 197 + 84 KB indented (≈ 281 KB).**                                                                                                                                                                                                              |
| `allocine_W0124_2026-11-12.json`                                                                                  | **real**, trimmed | From `/tmp/lib/r.json`: _La Gradiva_ alone. The only real `ORIGINAL` of a `["FRENCH"]` film (→ `LOCAL`) and the only real `relay`-only ticketing (fallback). ≈ 4 KB.                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `showtimes_empty_real_shape.json`                                                                                 | reconstructed     | The observed empty day: `error: true`, `message: "no.showtime.error"`, `messageParam: {"day", "page"}`, `totalPages: 0`, `results: []`. Replaces the synthetic `showtimes_empty.json`.                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `showtimes_versions.json`                                                                                         | **invented**      | What no capture has: a showtime in both `original` and `original_st` (→ one, subtitled); **SME**: entries in `original_sme` and `multiple_sme` (→ SME, not `vost`), one also in `original_st` (→ `vost` and SME), an `_sme` entry with the `Subtitled` tag (→ still not subtitled); a plain **`vo`** (`ORIGINAL` in `original`, no subtitle tag); a co-production `["FRENCH","ITALIAN"]` `ORIGINAL`; an unknown `diffusionVersion`; an unknown list key with and without a subtitle tag; a `null` list; `"movie": null`; a film whose lists are all empty; `service` missing and `service: "DISABLED_ACCESS"` (a string). |
| `showtimes_paged_p1.json` / `_p2.json`                                                                            | **invented**      | The same film (same `internalId`) on both pages, to test the merge; `page` as an int on p2.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `showtimes_enrichment_broken.json`                                                                                | **invented**      | One film per broken field (§9.2 list), each with a valid showtime.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| existing `showtimes_W0124.json`, `_two_pages_*`, `_original`, `_summer`, `_aware`, `_bad_datetime`, `_null_movie` | **invented**      | Synthetic (lists `dubbed` / `local` that AlloCiné does not have). Keep the useful ones (DST, aware dates, bad datetime), rename `showtimes_W0124.json` → `showtimes_synthetic.json`, and say "synthetic" in each test that uses them.                                                                                                                                                                                                                                                                                                                                                                                     |

The real fixtures add ≈ 420 KB minified (≈ 740 KB indented) to the repository. They are stored indented (Q17 settled).

### 9.2 Client scope (`tests/movie_showtimes/client/`)

- **Pagination on the real fixtures.** C0159: exactly **3** `requests.get` calls, in order, to
  `…/theater-C0159/d-2026-11-14/p-1/`, `…/p-2/`, `…/p-3/`; pages `"1"`, `"2"`, `"3"` accepted as strings; result:
  36 films, 161 showtimes. W7520: exactly **2** calls (`p-1/`, `p-2/`), 26 films, 66 showtimes. Both: the
  `User-Agent` and no other header on every call; `get_showtime` / `get_movies` never called.
- **Pagination edge cases (invented):** one request for `totalPages` 1 and for 0; page mismatch (p2 answering
  `"1"`), `pagination` missing, `totalPages` `"x"` / `-1` / `True` → `SourceParseError`; `totalPages: 21` →
  `SourceParseError` after exactly one request; the `URLs.showtime_url` guard (§4.2); the existing
  `_get_json_request` guard kept.
- **No hidden state:** two `_fetch_day_sync` calls run concurrently in two threads on one provider (a barrier
  inside the patched `requests.get`, C0159 for one and W7520 for the other) each return their own day.
- **Golden counts on the real fixtures:**

  | Check                                 | C0159 (2026-11-14)                                         | W7520 (2026-11-11)                                                                                                      |
  | ------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
  | versions                              | `ORIGINAL` 64, `DUBBED` 97, `LOCAL` 0                      | `ORIGINAL` 19, `DUBBED` 34, `LOCAL` 13                                                                                  |
  | `subtitled is True`                   | 64 (all from the `Localization.Subtitle.French` tag)       | 19 (all from `original_st` and the `Subtitled` tag)                                                                     |
  | `disabled_access` True / False / None | 145 / 16 / 0                                               | 48 / 18 / 0                                                                                                             |
  | `hard_of_hearing_subtitles is True`   | 0                                                          | 0                                                                                                                       |
  | `audio_description is True`           | 0                                                          | 16 (6 films)                                                                                                            |
  | `ticket_url`                          | 161, all `https://www.ugc.fr/…` (provider `default`)       | 66, all `https://s.pathe.fr/fr/…` (provider `default`, not `en`)                                                        |
  | formats                               | `("DIGITAL",)` × 161, no other kind                        | IMAX 3, F_3D 3 (one `("F_3D", "IMAX")`), SCREEN_X 3, PLF 6, E_4DX 3                                                     |
  | `runtime is None`                     | 2 (`"0h 00min"`)                                           | 1 (`"0h 00min"`, _Kraken_); _Ramayana_ 195; _Peppa_ 49                                                                  |
  | `certificate is None`                 | 1 (_Comment braquer une banque_)                           | 2 (_Comment braquer une banque_, _Peppa fête Noël_)                                                                     |
  | cast from `originalVoiceActor`        | 4 films (_Le Corset_ → "Gary Clichy" first)                | 5 films                                                                                                                 |
  | other                                 | _Dune_: release `2026-11-11`, visa `155420`, "Tout public" | _Ramayana_: no visa, `release_date` `2026-11-06`, `synopsis` `None`, `synopsis_full` set; _Peppa_: `user_rating` `None` |

  Plus a full golden `Film` for the four examples of §6.1 (written out in the test).

- **r.json golden:** _La Gradiva_ `version=LOCAL` (French rule), `subtitled=True`, `disabled_access=True`,
  `ticket_url` = the `relay` URL verbatim (fallback, raw spaces kept).
- **Lists and de-duplication (invented):** unknown key read; `null` list empty; a known key with a string →
  `SourceParseError`; duplicates across `original` / `original_st` and `original_st` / `original_sme` (OR rules);
  an entry without `internalId` kept; the same film on two pages merged, first details kept; `movie: null` skipped.
- **Versions and subtitles:** the §4.4 tables; each of the three subtitle signals alone sets `subtitled` (list
  `original_st` from W7520, tag `Subtitled` alone on `original` (invented), tag `Localization.Subtitle.French` from
  C0159, and an invented `Localization.Subtitle.English`); an `_sme` entry with a subtitle tag → `False`;
  `["FRENCH","ITALIAN"]` and `["FRENCH","FRENCH"]` + `ORIGINAL` → stay `ORIGINAL`; English films `DUBBED` stay
  `DUBBED` (C0159, W7520); `languages` missing / `null` / a string → rule off.
- **Accessibility:** PMR from `service`, from the tag alone (invented), `False` for `service: null` (real, 16 + 18),
  `None` when `service` is missing (invented); `Showtime.Accessibility.Accessible` without PMR → `False` (real,
  W7520) and PMR without `Accessible` → `True` (real, C0159 _Scrooge_); Greta → `audio_description` on exactly 16 showtimes (real, W7520), `False` on all C0159 showtimes, `None` for `tags: null` (invented); the relay `code=` never changes a flag (real C0159: `SME`/`AUDIO` in the code, flags `False`). **SME only on the
  invented `showtimes_versions.json`**, labelled as such.
- **Booking link:** real: `default` chosen over `relay` (C0159) and over `en` and `relay` (W7520), `relay` used when
  alone (r.json); invented: no DESKTOP entry → `None`; only an `en` entry → used; `default` with `urls: []` → next
  candidate; a relative URL skipped; no `ticketing` key → `None`; never an exception.
- **`parse_runtime`:** the §4.5 table.
- **Releases and flags:** the release-choice rule on _Dune_ (real), _Ramayana_ (real, no visa) and an invented
  `visaNumber` int; `releases: []` → all `None`; non-boolean `flags` ignored (real).
- **Enrichment never fails the day**, parametrized over: `runtime` int; `genres` not a list; a genre without
  `translate`; `stats` `null`; `userRating.score` `"4"` / `True` / `7`; `metric.hits` `-1` / `"777"`; `poster`
  `null` and `poster.url` `"javascript:alert(1)"`; `certificate: null`; `type` `42`; `data` `null`;
  `productionYear` `"2026"`; `synopsisFull` `{}`; `cast` missing and `edges` `null`; a credit without `person`;
  `relatedTags` a dict; `customFlags` `null`; `flags` missing and a list; `projection` a string; `comfort` `{}`;
  `service` `42`; `tags` `null`; `internalId` missing and `"abc"`. Each → the day parses, the showtime is there, the
  field is `None` / `()`, a DEBUG record, **no WARNING, no exception**. Plus: a `_film_details` that raises
  (patched) → `details=None`, day OK.
- **Still fatal:** `results` missing, title blank, `showtimes` `null`, `startsAt` missing → `SourceParseError`.
- **`editorialReviews` ignored:** a non-empty value changes nothing in the model and logs nothing.
- **Contract suite (`provider_contract.py`)**, added checks on `ok`: `ref` `None` or non-empty; `details` `None` or
  a `FilmDetails` that is not all-default; URLs `http(s)`; `runtime > 0`; `formats` not all-empty; the three
  showtime flags `bool | None`. For AlloCiné, `arrange("ok")` serves the C0159 pages. The fake passes unchanged.
- **Models:** defaults (a `Film(title=…, showtimes=…)` has `ref=None`, `details=None`; a `Showtime` without the new
  fields compares equal to one built with explicit `None`s); hashable.
- Boundary test unchanged (no `homeassistant` import).

### 9.3 Integration scope (`tests/` without the client; fake provider)

`tests/fake_provider.py`: the class is unchanged; `make_film` gains optional `ref=` and `details=`, and a showtime
helper takes the optional `subtitled`, `hard_of_hearing_subtitles`, `disabled_access`, `formats`, `ticket_url`, ….
The integration tests never read the client fixtures: the films of §6.1 are written out as models.

- **`film_attributes` / `attribute_version`** (unit): the exact dicts of the four §6.1 examples (with complete
  synopses) built from their `Film`s; a film without details → exactly the minimal shape; `None` / empty omitted,
  `false` kept; `LOCAL`+subtitled → `vf`; `ORIGINAL` + `True` → `vost`; `ORIGINAL` + `False` / `None` → `vo`;
  `ORIGINAL` with SME only → `vo` and in `accessibility.sme`; Greta → in `accessibility.audio_description`; PMR `True` → in `accessibility.pmr`, `False` /
  `None` → not; per-showtime `pmr` / `sme` omitted when `None`, written when `False`; two showtimes at the same
  minute → the time twice; `UNKNOWN` → `other` only then; `time` and `starts_at` in `Europe/Paris`,
  `Europe/London`, `America/New_York`; `time` identical in the version list, in `accessibility` and in
  `details.showtimes`; instant order.
- **Sensor:** expired showtimes are gone from `vf` / `vo` / `vost`, from `accessibility.pmr` / `.sme` **and** from
  `details.showtimes`; the film keeps its details after `remaining_films`; state == `len(films)`.
- **Recorder (`recorder_mock`):** with a day the size of C0159 (36 films, 161 showtimes, ≈ 127 KB of `films`) on
  every sensor, the recorded attributes are exactly `{date, fetched_at, friendly_name}` and `caplog` has no
  "exceed maximum size" warning.
- **Store, unit (`snapshot_to_dict` / `snapshot_from_dict` / `unify_film_details`):**
  - round trip with details (every field of §3, `synopsis_full` with HTML and quotes), formats with several codes,
    the four showtime flags, ticket URL; restored films of one `ref` share one `FilmDetails`;
  - omitted keys (`None`, `()`) are absent from the JSON, `false` present; a film without `ref` keeps inline
    `details` through a round trip;
  - **film gone from every day is removed:** days D and D+1 with films X and Y, then a snapshot where X is on no day
    → the catalogue has only Y;
  - **film on two days kept while one day remains:** X on D and D+1; save on D+1 (D is past) → X still in the
    catalogue; save when X is on no kept day → gone;
  - **failed day keeps its films:** D+3 fails to parse and keeps its previous copy with film Z (on no fresh day) →
    Z's details are in the catalogue;
  - **refetched details replace the old:** X on kept old D+3 (1 610 ratings) and on fresh D (1 615) → catalogue
    and every in-memory film X have 1 615 (`unify_film_details`, latest `fetched_at` wins; tie → earliest date);
  - **orphan reference tolerated:** a day film with `ref` `"999"` absent from `films` → loads, `details=None`, one
    DEBUG record, no warning;
  - **unreferenced entry ignored:** an extra catalogue key → loads, not in any film;
  - rejected (whole snapshot, `ValueError`): no `films` key (old format), `films` a list, an entry a string,
    `runtime` `"x"`, `ref` `123` (not a string), `subtitled` `"yes"`, `disabled_access` `1`.
- **Store, integration:** **does not grow:** 10 refreshes (`freezer.tick(12 h)`) where the fake rotates films
  (each refresh drops one film and adds a new one) → after each, the catalogue keys equal the set of refs in the
  stored days, and the JSON size stays under a bound computed from the first refresh (+ one film's worth); memory
  equals `snapshot_from_dict(hass_storage[…])` after each refresh, including after a partial refresh.
- **Restart:** a fresh store with details → no provider call, attributes equal to before the restart.
- **Coordinator:** still 8 calls per refresh; `unify_film_details` applied before the save.
- **Diagnostics:** snapshot updated (§10 step 7).
- Existing tests that assert the exact attribute dict (`{"title", "vf", "vo"}`) are updated to include `vost`,
  `accessibility` and `details.showtimes`.

## 10. Implementation order (ha-developer)

Each step keeps `scripts/test client` and `scripts/test integration` green.

1. **Models** (§3) + exports. No behaviour change; existing tests pass untouched.
2. **Real fixtures** (§9.1): derive the C0159, W7520 and W0124 fixtures from the captures by removing keys only
   (a throwaway script outside the repository; the raw files stay out of it). Stored indented (Q17 settled).
3. **Pagination** (§4.2): `fetch_showtime_pages`, delete `fetch_showtimes`, move the `movie: null` filter into the
   parser, keep the old flattening behaviour otherwise. The `URLs.showtime_url` guard; the 3-page (C0159) and
   2-page (W7520) request tests; the "never calls `get_showtime` / `get_movies`" test.
4. **Lists, de-duplication, classic subtitles (three signals), French rule** (§4.3, §4.4); `showtimes_versions.json`.
5. **Accessibility** (§4.7): PMR (service or tag), SME (lists only), audio description (Greta tag), OR merge.
6. **Enrichment** (§4.5, §4.6, §4.8): `parse_runtime`, the release choice, the booking-link choice, the cast
   fallback, extractors, `FilmDetails`, D28 safety net, broken-fields fixture. Golden counts. Contract-suite checks.
7. **Attributes** (§6): `const.py` names, `attribute_version`, `film_attributes` (with `accessibility`); attribute
   tests; recorder test.
8. **Store and coordinator** (§5.1, §5.2): schema, `unify_film_details`, catalogue rebuild, tolerant refs; call
   from `_async_update_data`. Store tests. Then **diagnostics**: per film `ref`, per showtime `subtitled`,
   `hard_of_hearing_subtitles`, `disabled_access`, `audio_description`, and a top-level `films` catalogue (as in the store). Snapshot.
9. **README:** the attribute reference (§6.1), the template examples (§6.3), "no extra request".

`CLAUDE.md` is updated by the user (lines listed in the architect's report).

## 11. Open questions

Answered by the user: Q1 (editorial reviews: dropped), Q3 (every free field: added), Q4 (codes, verbatim, also the
irregular `F_3D`, `E_4DX`, `SCREEN_X`), Q5 (exactly `["FRENCH"]`), Q6 (one DESKTOP link), Q7 (accessibility in
scope, SME separate from `vost`), and the Greta tag (a third list, `audio_description`, D31). Q12 (PMR per showtime) is settled by the captures: PMR varies within a film.

Still open:

- **Q2 — `nextDate`:** `null` in every response seen. Not used.
- **Q8 — `multiple*` lists:** `multiple` holds every VF showtime in C0159 and W7520 (`DUBBED` and `LOCAL`);
  `multiple_st` / `multiple_sme` were never seen filled. They are read like the others.
- **Q9 — `error: true` with another message than `no.showtime.error`:** read as an empty day if `results` is empty.
  Never observed.
- **Q10 — How AlloCiné signals SME is not known yet.** In the three captures (434 showtimes) the `*_sme` lists are
  always empty and no tag names subtitles for the deaf and hard of hearing. SME is read from the `*_sme` lists only,
  so on today's real data `accessibility.sme` is always empty; the relay URL's `code=` does not help (§4.7). A capture of a cinema that advertises "ST-SME"
  showtimes would tell which signal to read.
- **Q11 — Release-date precision:** always `"day"` in the captures. For `month` / `year` the `date` format is
  unknown; it is passed on verbatim. Drop a non-`day` date instead?
- **Q13 — Which booking link:** proposed order `default` (the chain's own French booking page: ugc.fr, pathe.fr/fr)
  → `relay` (AlloCiné's redirector, with raw spaces) → any other DESKTOP provider (`en` = the English Pathé page).
  Confirm, or prefer `relay`?
- **Q14 — `Showtime.Accessibility.Accessible`:** on 66/66 showtimes in W7520 (PMR or not) and 133/161 in C0159 (all
  PMR, but not all PMR showtimes). It is not PMR; its meaning is unknown, so it is not exposed. Expose it as a raw
  flag, or leave it out?
- **Q15 — Greta = audio description is an assumption** (D31). If AlloCiné documents the tag otherwise (e.g. SME),
  only the mapping changes. A cinema page listing "audiodescription" next to the same showtimes would confirm it.
- **Q16 — Re-releases:** for _Dune_ the chosen release is a `ReRelease` (2026-11-11), while the original release
  was 2021. The release name (`releases[].name`: `Released`, `ReRelease`) is not exposed. Add a `release_type`
  (or a `rerelease` boolean)?
- **Q18 (minor) — log rule for `credits`:** a non-object `credits` item is skipped silently, while other unexpected
  types log one DEBUG line. Make it homogeneous (one DEBUG line) or keep it silent?

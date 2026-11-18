"""Pure helpers that turn the client's data into what the sensors show, at a given time.

No I/O. Times are rendered in Home Assistant's time zone.
"""

from dataclasses import replace
from datetime import datetime
from typing import Any, cast

from homeassistant.util import dt as dt_util

from .client import DayShowtimes, Film, Showtime, ShowtimeVersion
from .const import (
    ATTR_ACCESSIBILITY,
    ATTR_AUDIO_DESCRIPTION,
    ATTR_CAST,
    ATTR_CERTIFICATE,
    ATTR_COMFORT,
    ATTR_COUNTRIES,
    ATTR_CREDITS,
    ATTR_DETAILS,
    ATTR_DIRECTORS,
    ATTR_EXPERIENCE,
    ATTR_FILM_ID,
    ATTR_FILM_TYPE,
    ATTR_FLAGS,
    ATTR_GENRES,
    ATTR_HAS_TRAILER,
    ATTR_HITS,
    ATTR_LANGUAGES,
    ATTR_NAME,
    ATTR_ORIGINAL_TITLE,
    ATTR_OTHER,
    ATTR_PICTURE,
    ATTR_PMR,
    ATTR_POSTER,
    ATTR_PREMIERE,
    ATTR_PRESS_RATING,
    ATTR_PRESS_RATING_COUNT,
    ATTR_PREVIEW,
    ATTR_PROJECTION,
    ATTR_RELATED_TAGS,
    ATTR_RELEASE_DATE,
    ATTR_ROLE,
    ATTR_RUNTIME,
    ATTR_SESSIONS,
    ATTR_SHOWTIMES,
    ATTR_SME,
    ATTR_SOUND,
    ATTR_STARTS_AT,
    ATTR_SUBTITLED,
    ATTR_SYNOPSIS,
    ATTR_SYNOPSIS_FULL,
    ATTR_TICKET_URL,
    ATTR_TIME,
    ATTR_TITLE,
    ATTR_URL,
    ATTR_USER_RATING,
    ATTR_USER_RATING_COUNT,
    ATTR_USER_REVIEW_COUNT,
    ATTR_VERSION,
    ATTR_VF,
    ATTR_VISA_NUMBER,
    ATTR_VO,
    ATTR_VOST,
    ATTR_WANT_TO_SEE_COUNT,
    ATTR_WEEKLY_OUTING,
    ATTR_YEAR,
    MAX_DATA_AGE,
    SHOWTIME_GRACE_PERIOD,
)
from .store import CachedDay

_VF_VERSIONS = frozenset({ShowtimeVersion.DUBBED, ShowtimeVersion.LOCAL})


def showtime_expiry(showtime: Showtime) -> datetime:
    """Return the instant a showtime stops being shown: its start plus the grace period.

    Args:
        showtime (Showtime): The showtime.

    Returns:
        datetime: ``starts_at + SHOWTIME_GRACE_PERIOD``, aware.

    """
    return showtime.starts_at + SHOWTIME_GRACE_PERIOD


def day_data_expiry(cached: CachedDay) -> datetime:
    """Return the instant a day's data stops being usable: when it was fetched plus the maximum age.

    Args:
        cached (CachedDay): The cached day.

    Returns:
        datetime: ``fetched_at + MAX_DATA_AGE``, aware.

    """
    return cached.fetched_at + MAX_DATA_AGE


def is_day_usable(cached: CachedDay, now: datetime) -> bool:
    """Return whether a day's data is still young enough to be shown at ``now``.

    Args:
        cached (CachedDay): The cached day.
        now (datetime): The current time, aware.

    Returns:
        bool: ``True`` while ``now`` is strictly before the expiry.

    """
    return now < day_data_expiry(cached)


def remaining_films(day: DayShowtimes, now: datetime) -> tuple[Film, ...]:
    """Return the films of a day with only their showtimes not yet expired at ``now``.

    A showtime is kept while ``starts_at + SHOWTIME_GRACE_PERIOD > now``. A film left with no showtime is dropped.

    Args:
        day (DayShowtimes): The day, as fetched.
        now (datetime): The current time, aware.

    Returns:
        tuple[Film, ...]: The remaining films, in the day's order.

    """
    films: list[Film] = []
    for film in day.films:
        kept = tuple(showtime for showtime in film.showtimes if showtime_expiry(showtime) > now)
        if not kept:
            continue
        films.append(film if len(kept) == len(film.showtimes) else replace(film, showtimes=kept))
    return tuple(films)


def attribute_version(showtime: Showtime) -> str:
    """Return the attribute version of a showtime.

    Args:
        showtime (Showtime): The showtime.

    Returns:
        str: ``vf`` (dubbed or local), ``vost`` (original with classic subtitles), ``vo`` (original otherwise) or
        ``other`` (unknown).

    """
    if showtime.version in _VF_VERSIONS:
        return ATTR_VF
    if showtime.version is ShowtimeVersion.ORIGINAL:
        return ATTR_VOST if showtime.subtitled is True else ATTR_VO
    return ATTR_OTHER


def _put(target: dict[str, Any], key: str, value: object) -> None:
    """Set ``key`` unless ``value`` is ``None`` or an empty tuple; ``False`` and ``0`` are kept.

    Args:
        target (dict[str, Any]): The dictionary to fill.
        key (str): The key.
        value (object): The value; a tuple is written as a list.

    """
    if value is None or value == ():
        return
    target[key] = list(cast("tuple[Any, ...]", value)) if isinstance(value, tuple) else value


def _showtime_attributes(showtime: Showtime, local: datetime) -> dict[str, Any]:
    """Return one item of ``details.showtimes``.

    Args:
        showtime (Showtime): The showtime.
        local (datetime): Its start in Home Assistant's time zone.

    Returns:
        dict[str, Any]: ``time``, ``starts_at``, ``version`` and every known optional key.

    """
    item: dict[str, Any] = {
        ATTR_TIME: local.strftime("%H:%M"),
        ATTR_STARTS_AT: local.isoformat(),
        ATTR_VERSION: attribute_version(showtime),
    }
    _put(item, ATTR_SUBTITLED, showtime.subtitled)
    _put(item, ATTR_SME, showtime.hard_of_hearing_subtitles)
    _put(item, ATTR_PMR, showtime.disabled_access)
    _put(item, ATTR_AUDIO_DESCRIPTION, showtime.audio_description)
    if (formats := showtime.formats) is not None:
        _put(item, ATTR_PROJECTION, formats.projection)
        _put(item, ATTR_PICTURE, formats.picture)
        _put(item, ATTR_SOUND, formats.sound)
        _put(item, ATTR_EXPERIENCE, formats.experience)
        _put(item, ATTR_COMFORT, formats.comfort)
    _put(item, ATTR_PREVIEW, showtime.preview)
    _put(item, ATTR_WEEKLY_OUTING, showtime.weekly_outing)
    _put(item, ATTR_TICKET_URL, showtime.ticket_url)
    return item


def _details_attributes(film: Film, attributes: dict[str, Any]) -> dict[str, Any]:
    """Add the film-level keys to ``attributes`` and return the heavy ones of ``details`` (showtimes excluded).

    Args:
        film (Film): The film.
        attributes (dict[str, Any]): The film item, filled in place.

    Returns:
        dict[str, Any]: The ``details`` keys other than ``showtimes``.

    """
    _put(attributes, ATTR_FILM_ID, film.ref)
    heavy: dict[str, Any] = {}
    details = film.details
    if details is None:
        return heavy
    _put(attributes, ATTR_URL, details.url)
    _put(attributes, ATTR_POSTER, details.poster_url)
    _put(attributes, ATTR_FILM_TYPE, details.film_type)
    _put(attributes, ATTR_ORIGINAL_TITLE, details.original_title)
    _put(attributes, ATTR_YEAR, details.year)
    _put(attributes, ATTR_RELEASE_DATE, details.release_date)
    _put(attributes, ATTR_VISA_NUMBER, details.visa_number)
    _put(attributes, ATTR_RUNTIME, details.runtime)
    _put(attributes, ATTR_GENRES, details.genres)
    _put(attributes, ATTR_CERTIFICATE, details.certificate)
    _put(attributes, ATTR_COUNTRIES, details.countries)
    _put(attributes, ATTR_LANGUAGES, details.languages)
    _put(attributes, ATTR_DIRECTORS, details.directors)
    if (user_rating := details.user_rating) is not None:
        _put(attributes, ATTR_USER_RATING, user_rating.score)
        _put(attributes, ATTR_USER_RATING_COUNT, user_rating.count)
    _put(attributes, ATTR_USER_REVIEW_COUNT, details.user_review_count)
    if (press_rating := details.press_rating) is not None:
        _put(attributes, ATTR_PRESS_RATING, press_rating.score)
        _put(attributes, ATTR_PRESS_RATING_COUNT, press_rating.count)
    _put(attributes, ATTR_WANT_TO_SEE_COUNT, details.want_to_see_count)
    _put(attributes, ATTR_HITS, details.hits)
    _put(attributes, ATTR_SESSIONS, details.sessions)
    _put(attributes, ATTR_PREMIERE, details.premiere)
    _put(attributes, ATTR_WEEKLY_OUTING, details.weekly_outing)
    _put(attributes, ATTR_HAS_TRAILER, details.has_trailer)
    _put(attributes, ATTR_FLAGS, details.flags)

    _put(heavy, ATTR_SYNOPSIS, details.synopsis)
    _put(heavy, ATTR_SYNOPSIS_FULL, details.synopsis_full)
    _put(heavy, ATTR_CAST, details.cast)
    _put(
        heavy,
        ATTR_CREDITS,
        tuple({ATTR_NAME: credit.name, ATTR_ROLE: credit.role} for credit in details.credits),
    )
    _put(heavy, ATTR_RELATED_TAGS, details.related_tags)
    return heavy


def film_attributes(film: Film) -> dict[str, Any]:
    """Return a film as an item of the sensor's ``films`` attribute.

    Always present: ``title``, ``vf``, ``vo``, ``vost`` (``HH:MM`` lists), ``accessibility`` (``pmr``, ``sme``,
    ``audio_description`` lists) and ``details.showtimes``. ``other`` is added only for showtimes of an unknown
    version; every other key only when known. Each showtime is rendered once, in Home Assistant's time zone, so its
    ``HH:MM`` is the same in every list. Showtimes are sorted by instant.

    Args:
        film (Film): The film.

    Returns:
        dict[str, Any]: The film item.

    """
    versions: dict[str, list[str]] = {ATTR_VF: [], ATTR_VO: [], ATTR_VOST: [], ATTR_OTHER: []}
    accessibility: dict[str, list[str]] = {ATTR_PMR: [], ATTR_SME: [], ATTR_AUDIO_DESCRIPTION: []}
    showtimes: list[dict[str, Any]] = []
    for showtime in sorted(film.showtimes, key=lambda showtime: showtime.starts_at):
        item = _showtime_attributes(showtime, dt_util.as_local(showtime.starts_at))
        text: str = item[ATTR_TIME]
        versions[item[ATTR_VERSION]].append(text)
        if showtime.disabled_access is True:
            accessibility[ATTR_PMR].append(text)
        if showtime.hard_of_hearing_subtitles is True:
            accessibility[ATTR_SME].append(text)
        if showtime.audio_description is True:
            accessibility[ATTR_AUDIO_DESCRIPTION].append(text)
        showtimes.append(item)

    attributes: dict[str, Any] = {
        ATTR_TITLE: film.title,
        ATTR_VF: versions[ATTR_VF],
        ATTR_VO: versions[ATTR_VO],
        ATTR_VOST: versions[ATTR_VOST],
    }
    if versions[ATTR_OTHER]:
        attributes[ATTR_OTHER] = versions[ATTR_OTHER]
    attributes[ATTR_ACCESSIBILITY] = accessibility
    heavy = _details_attributes(film, attributes)
    attributes[ATTR_DETAILS] = {**heavy, ATTR_SHOWTIMES: showtimes}
    return attributes

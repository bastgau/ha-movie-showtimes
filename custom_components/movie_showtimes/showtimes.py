"""Pure helpers that turn the client's data into what the sensors show, at a given time.

No I/O. Times are rendered in Home Assistant's time zone.
"""

from dataclasses import replace
from datetime import datetime

from homeassistant.util import dt as dt_util

from .client import DayShowtimes, Film, Showtime, ShowtimeVersion
from .const import ATTR_OTHER, ATTR_TITLE, ATTR_VF, ATTR_VO, MAX_DATA_AGE, SHOWTIME_GRACE_PERIOD
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


def film_attributes(film: Film) -> dict[str, list[str] | str]:
    """Return a film as a sensor attribute: its title and its ``HH:MM`` times split by version.

    ``vf`` holds the dubbed and French showtimes, ``vo`` the original ones; both are always present. ``other``
    is added only when the film has showtimes of an unknown version. Times are in Home Assistant's time zone,
    sorted by instant.

    Args:
        film (Film): The film.

    Returns:
        dict[str, list[str] | str]: ``{"title", "vf", "vo"[, "other"]}``.

    """
    vf: list[str] = []
    vo: list[str] = []
    other: list[str] = []
    for showtime in sorted(film.showtimes, key=lambda showtime: showtime.starts_at):
        text = dt_util.as_local(showtime.starts_at).strftime("%H:%M")
        if showtime.version in _VF_VERSIONS:
            vf.append(text)
        elif showtime.version is ShowtimeVersion.ORIGINAL:
            vo.append(text)
        else:
            other.append(text)

    attributes: dict[str, list[str] | str] = {ATTR_TITLE: film.title, ATTR_VF: vf, ATTR_VO: vo}
    if other:
        attributes[ATTR_OTHER] = other
    return attributes

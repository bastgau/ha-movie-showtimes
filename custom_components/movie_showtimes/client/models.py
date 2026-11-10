"""Typed, source-neutral models returned by the providers.

They are frozen and only hold tuples, so two fetches of the same data compare equal.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class ShowtimeVersion(StrEnum):
    """The language version of a showtime, as mapped by the provider from its source's own codes."""

    ORIGINAL = "original"
    """Shown in the film's original language, subtitled or not (VO)."""

    DUBBED = "dubbed"
    """Dubbed into the source country's language (VF)."""

    LOCAL = "local"
    """The film's original language is the source country's (VF)."""

    UNKNOWN = "unknown"
    """Anything the provider cannot map: kept rather than dropped."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Showtime:
    """One showtime of a film.

    Attributes:
        starts_at (datetime): When it starts, aware, in the source's time zone.
        version (ShowtimeVersion): Its language version.

    """

    starts_at: datetime
    version: ShowtimeVersion


@dataclass(frozen=True, slots=True, kw_only=True)
class Film:
    """A film and its showtimes on one day.

    Attributes:
        title (str): The film's title, never empty.
        showtimes (tuple[Showtime, ...]): Its showtimes, sorted by start, never empty.

    """

    title: str
    showtimes: tuple[Showtime, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DayShowtimes:
    """What is on at one cinema on one day.

    Attributes:
        cinema_id (str): The provider's canonical cinema id.
        day (date): The source's local date these showtimes belong to.
        films (tuple[Film, ...]): The films, sorted by title; empty when nothing is on (valid data).

    """

    cinema_id: str
    day: date
    films: tuple[Film, ...]

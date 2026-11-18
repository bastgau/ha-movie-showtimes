"""Typed, source-neutral models returned by the providers.

They are frozen and only hold tuples, so two fetches of the same data compare equal. Every field beyond a film's
title and showtimes and a showtime's start and version is optional: a source that does not know it leaves the
default.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class ShowtimeVersion(StrEnum):
    """The language version of a showtime, as mapped by the provider from its source's own codes.

    Subtitles and accessibility are separate axes (``Showtime.subtitled`` and the accessibility flags): a dubbed or
    local showtime can carry them too.

    """

    ORIGINAL = "original"
    """The film's original language, which is not the source country's (VO, subtitled or not)."""

    DUBBED = "dubbed"
    """Dubbed into the source country's language (VF). AlloCiné also uses it for some French films."""

    LOCAL = "local"
    """The film's original language is the source country's (VF)."""

    UNKNOWN = "unknown"
    """Anything the provider cannot map: kept rather than dropped."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ShowtimeFormats:
    """The projection formats of a showtime, as the source's codes, verbatim.

    Attributes:
        projection (tuple[str, ...]): E.g. ``("DIGITAL",)``, ``("F_3D", "IMAX")``.
        picture (tuple[str, ...]): Picture codes.
        sound (tuple[str, ...]): Sound codes.
        experience (tuple[str, ...]): E.g. ``("SCREEN_X", "PLF")``.
        comfort (tuple[str, ...]): Seating codes.

    """

    projection: tuple[str, ...] = ()
    picture: tuple[str, ...] = ()
    sound: tuple[str, ...] = ()
    experience: tuple[str, ...] = ()
    comfort: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Showtime:  # pylint: disable=too-many-instance-attributes
    """One showtime of a film.

    Attributes:
        starts_at (datetime): When it starts, aware, in the source's time zone.
        version (ShowtimeVersion): Its language version.
        subtitled (bool | None): Classic subtitles (not SME); ``None`` when the source does not say.
        hard_of_hearing_subtitles (bool | None): Subtitles for the deaf and hard of hearing (SME).
        disabled_access (bool | None): Accessible to people with reduced mobility (PMR).
        audio_description (bool | None): Audio description is offered.
        formats (ShowtimeFormats | None): Its formats; ``None`` when nothing is known.
        preview (bool | None): A preview screening.
        weekly_outing (bool | None): Part of the film's release week.
        ticket_url (str | None): The booking page, ``http(s)`` only.

    """

    starts_at: datetime
    version: ShowtimeVersion
    subtitled: bool | None = None
    hard_of_hearing_subtitles: bool | None = None
    disabled_access: bool | None = None
    audio_description: bool | None = None
    formats: ShowtimeFormats | None = None
    preview: bool | None = None
    weekly_outing: bool | None = None
    ticket_url: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Rating:
    """A rating, as the source gives it.

    Attributes:
        score (float): The score (AlloCiné: 0 to 5).
        count (int | None): How many ratings it averages.

    """

    score: float
    count: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Credit:
    """One person credited on a film.

    Attributes:
        name (str): The person's name, e.g. ``Denis Villeneuve``.
        role (str): The source's position code, e.g. ``DIRECTOR``.

    """

    name: str
    role: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FilmDetails:  # pylint: disable=too-many-instance-attributes
    """What the source says about the film itself, the same for every day.

    Attributes:
        url (str | None): The film's page on the source.
        film_type (str | None): The source's code, e.g. ``FEATURE_FILM``.
        original_title (str | None): The original title.
        year (int | None): The production year.
        release_date (str | None): The release date, verbatim (``2026-11-11``).
        visa_number (str | None): The exploitation visa number.
        runtime (int | None): Minutes, > 0.
        genres (tuple[str, ...]): The genres.
        certificate (str | None): The age certificate.
        countries (tuple[str, ...]): The production countries.
        languages (tuple[str, ...]): The source's language codes.
        directors (tuple[str, ...]): The directors' names.
        poster_url (str | None): The poster, ``http(s)`` only.
        synopsis (str | None): The plain-text synopsis.
        synopsis_full (str | None): The full synopsis, verbatim (may contain HTML).
        cast (tuple[str, ...]): The main cast's names.
        credits (tuple[Credit, ...]): The credited people.
        related_tags (tuple[str, ...]): The source's related tags.
        user_rating (Rating | None): The users' rating.
        user_review_count (int | None): The number of user reviews.
        press_rating (Rating | None): The press rating.
        want_to_see_count (int | None): How many users want to see it.
        hits (int | None): Page views.
        sessions (int | None): Visit sessions.
        premiere (bool | None): A premiere.
        weekly_outing (bool | None): Released this week.
        has_trailer (bool | None): A trailer exists.
        flags (tuple[str, ...]): The source names of the flags that are true.

    """

    url: str | None = None
    film_type: str | None = None
    original_title: str | None = None
    year: int | None = None
    release_date: str | None = None
    visa_number: str | None = None
    runtime: int | None = None
    genres: tuple[str, ...] = ()
    certificate: str | None = None
    countries: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    directors: tuple[str, ...] = ()
    poster_url: str | None = None
    synopsis: str | None = None
    synopsis_full: str | None = None
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
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Film:
    """A film and its showtimes on one day.

    Attributes:
        title (str): The film's title, never empty.
        showtimes (tuple[Showtime, ...]): Its showtimes, sorted by start, never empty.
        ref (str | None): The source's film id, non-empty; ``None`` if unknown.
        details (FilmDetails | None): What the source says about the film; ``None`` when nothing.

    """

    title: str
    showtimes: tuple[Showtime, ...]
    ref: str | None = None
    details: FilmDetails | None = None


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

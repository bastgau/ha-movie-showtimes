"""The client's models: defaults and hashability (design §3)."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.client import (
    Credit,
    Film,
    FilmDetails,
    Rating,
    Showtime,
    ShowtimeFormats,
    ShowtimeVersion,
)

START = datetime(2026, 11, 12, 20, tzinfo=ZoneInfo("Europe/Paris"))


def test_film_defaults() -> None:
    """A film built with its title and showtimes only has no ref and no details."""
    film = Film(title="A", showtimes=(Showtime(starts_at=START, version=ShowtimeVersion.LOCAL),))

    assert film.ref is None
    assert film.details is None


def test_showtime_defaults_equal_explicit_nones() -> None:
    """A showtime without the new fields equals one built with explicit ``None``s."""
    explicit = Showtime(
        starts_at=START,
        version=ShowtimeVersion.ORIGINAL,
        subtitled=None,
        hard_of_hearing_subtitles=None,
        disabled_access=None,
        audio_description=None,
        formats=None,
        preview=None,
        weekly_outing=None,
        ticket_url=None,
    )

    assert Showtime(starts_at=START, version=ShowtimeVersion.ORIGINAL) == explicit


def test_models_are_hashable() -> None:
    """Every model can be hashed and put in a set, details included."""
    details = FilmDetails(
        genres=("Drame",),
        credits=(Credit(name="Ann Example", role="DIRECTOR"),),
        user_rating=Rating(score=4.0, count=3),
    )
    showtime = Showtime(
        starts_at=START, version=ShowtimeVersion.ORIGINAL, formats=ShowtimeFormats(projection=("IMAX",))
    )
    film = Film(title="A", showtimes=(showtime,), ref="1", details=details)

    assert len({film, Film(title="A", showtimes=(showtime,), ref="1", details=details)}) == 1
    assert hash(details) == hash(replace(details))

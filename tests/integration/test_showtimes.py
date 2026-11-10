"""The pure helpers that turn the client's data into what the sensors show."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from custom_components.movie_showtimes import showtimes
from custom_components.movie_showtimes.client import ShowtimeVersion
from custom_components.movie_showtimes.showtimes import (
    day_data_expiry,
    film_attributes,
    is_day_usable,
    remaining_films,
    showtime_expiry,
)
from custom_components.movie_showtimes.store import CachedDay
import pytest

from tests.fake_provider import make_day, make_film, paris

from .helpers import TODAY, at, standard_day

START = at(TODAY, 14)


def test_expiry_is_start_plus_grace() -> None:
    """A showtime expires 15 minutes after it starts."""
    film = make_film("A", (START, ShowtimeVersion.LOCAL))

    assert showtime_expiry(film.showtimes[0]) == START + timedelta(minutes=15)


@pytest.mark.parametrize(
    ("elapsed", "kept"),
    [
        (timedelta(minutes=-5), True),
        (timedelta(0), True),
        (timedelta(minutes=14), True),
        (timedelta(minutes=14, seconds=59), True),
        (timedelta(minutes=15), False),
        (timedelta(hours=2), False),
    ],
)
def test_remaining_films_cut_off(elapsed: timedelta, kept: bool) -> None:
    """A showtime is kept strictly before its start plus 15 minutes."""
    day = make_day("C1", TODAY, make_film("A", (START, ShowtimeVersion.LOCAL)))

    result = remaining_films(day, START + elapsed)

    assert bool(result) is kept


def test_remaining_films_uses_the_grace_constant() -> None:
    """Changing the constant moves the cut-off."""
    day = make_day("C1", TODAY, make_film("A", (START, ShowtimeVersion.LOCAL)))

    with patch.object(showtimes, "SHOWTIME_GRACE_PERIOD", timedelta(minutes=30)):
        assert remaining_films(day, START + timedelta(minutes=20))
        assert not remaining_films(day, START + timedelta(minutes=30))


def test_film_left_with_no_showtime_is_removed_and_others_trimmed() -> None:
    """Only the future showtimes remain, and a film without any is dropped."""
    day = standard_day(TODAY)

    result = remaining_films(day, at(TODAY, 15))

    assert [film.title for film in result] == ["Film A"]
    assert [showtime.starts_at for showtime in result[0].showtimes] == [at(TODAY, 20)]


def test_future_day_is_untouched() -> None:
    """A day entirely ahead is returned as it is."""
    day = standard_day(TODAY + timedelta(days=1))

    assert remaining_films(day, at(TODAY, 23)) == day.films


@pytest.mark.parametrize(
    ("zone", "expected"),
    [("Europe/Paris", "20:00"), ("Europe/London", "19:00"), ("America/New_York", "14:00")],
)
def test_film_attributes_render_in_the_home_assistant_zone(
    set_time_zone: Callable[[str], None], zone: str, expected: str
) -> None:
    """The same aware 20:00 Paris showtime is rendered in the configured zone."""
    set_time_zone(zone)
    film = make_film("A", (paris(2026, 11, 12, 20), ShowtimeVersion.LOCAL))

    assert film_attributes(film) == {"title": "A", "vf": [expected], "vo": []}


def test_film_attributes_split_versions_and_sort_by_instant() -> None:
    """Dubbed and local go to ``vf``, original to ``vo``, anything else to ``other``, each by instant."""
    film = make_film(
        "A",
        (paris(2026, 11, 12, 21), ShowtimeVersion.LOCAL),
        (paris(2026, 11, 12, 14), ShowtimeVersion.DUBBED),
        (paris(2026, 11, 12, 18), ShowtimeVersion.ORIGINAL),
        (paris(2026, 11, 12, 16), ShowtimeVersion.UNKNOWN),
    )

    assert film_attributes(film) == {"title": "A", "vf": ["14:00", "21:00"], "vo": ["18:00"], "other": ["16:00"]}


def test_other_is_absent_without_unknown_versions() -> None:
    """``vf`` and ``vo`` are always there, ``other`` only when needed."""
    film = make_film("A", (START, ShowtimeVersion.ORIGINAL))

    assert film_attributes(film) == {"title": "A", "vf": [], "vo": ["14:00"]}


FETCHED = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _cached() -> CachedDay:
    """Return a day fetched at ``FETCHED``."""
    return CachedDay(showtimes=standard_day(TODAY), fetched_at=FETCHED)


def test_day_data_expiry_is_fetch_time_plus_48_hours() -> None:
    """A day's data expires 48 hours after it was fetched."""
    assert day_data_expiry(_cached()) == FETCHED + timedelta(hours=48)


@pytest.mark.parametrize(
    ("elapsed", "usable"),
    [
        (timedelta(0), True),
        (timedelta(hours=47, minutes=59, seconds=59), True),
        (timedelta(hours=48), False),
        (timedelta(hours=48, seconds=1), False),
        (timedelta(hours=-1), True),
    ],
)
def test_is_day_usable_boundary(elapsed: timedelta, usable: bool) -> None:
    """Data is usable strictly before fetched_at + 48 h."""
    assert is_day_usable(_cached(), FETCHED + elapsed) is usable

"""``film_attributes`` / ``attribute_version``: the ``films`` items of design §6, from models (no fixture read)."""

from collections.abc import Callable

from custom_components.movie_showtimes.client import Film, FilmDetails, Rating, ShowtimeFormats, ShowtimeVersion
from custom_components.movie_showtimes.showtimes import attribute_version, film_attributes
import pytest

from tests import reference_films
from tests.fake_provider import make_film, make_showtime, paris

from . import expected_attributes

ORIG = ShowtimeVersion.ORIGINAL


@pytest.mark.parametrize(
    ("film", "expected"),
    [
        (reference_films.COMMENT_BRAQUER, expected_attributes.COMMENT_BRAQUER),
        (reference_films.LE_CORSET, expected_attributes.LE_CORSET),
        (reference_films.DUNE, expected_attributes.DUNE),
        (reference_films.RAMAYANA, expected_attributes.RAMAYANA),
    ],
    ids=["comment_braquer", "le_corset", "dune", "ramayana"],
)
def test_real_examples(film: Film, expected: dict[str, object]) -> None:
    """The four real films of §6.1 render exactly as the design says."""
    assert film_attributes(film) == expected


def test_minimal_shape() -> None:
    """A film without any enrichment (the fake provider) gives exactly the minimal shape."""
    film = make_film("Film A", (paris(2026, 11, 12, 15), ShowtimeVersion.DUBBED))

    assert film_attributes(film) == expected_attributes.MINIMAL


@pytest.mark.parametrize(
    ("version", "subtitled", "expected"),
    [
        (ShowtimeVersion.DUBBED, None, "vf"),
        (ShowtimeVersion.LOCAL, True, "vf"),
        (ShowtimeVersion.DUBBED, True, "vf"),
        (ORIG, True, "vost"),
        (ORIG, False, "vo"),
        (ORIG, None, "vo"),
        (ShowtimeVersion.UNKNOWN, True, "other"),
    ],
)
def test_attribute_version(version: ShowtimeVersion, subtitled: bool | None, expected: str) -> None:
    """``vf`` = dubbed + local; ``vost`` = original subtitled; ``vo`` otherwise; ``other`` = unknown."""
    assert attribute_version(make_showtime(paris(2026, 11, 12, 20), version, subtitled=subtitled)) == expected


def test_accessibility_and_per_showtime_flags() -> None:
    """Only ``True`` goes in the lists; per-showtime flags omitted when ``None``, written when ``False``."""
    film = make_film(
        "A",
        make_showtime(paris(2026, 11, 12, 14), ORIG, hard_of_hearing_subtitles=True, disabled_access=False),
        make_showtime(paris(2026, 11, 12, 16), ORIG, subtitled=True, disabled_access=True, audio_description=True),
        make_showtime(paris(2026, 11, 12, 18), ShowtimeVersion.UNKNOWN),
    )

    attributes = film_attributes(film)

    assert (attributes["vo"], attributes["vost"], attributes["other"]) == (["14:00"], ["16:00"], ["18:00"])
    assert attributes["accessibility"] == {"pmr": ["16:00"], "sme": ["14:00"], "audio_description": ["16:00"]}
    first, second, third = attributes["details"]["showtimes"]
    assert first == {
        "time": "14:00",
        "starts_at": "2026-11-12T14:00:00+01:00",
        "version": "vo",
        "sme": True,
        "pmr": False,
    }
    assert second["pmr"] is True
    assert "sme" not in second
    assert set(third) == {"time", "starts_at", "version"}


def test_same_minute_twice_and_instant_order() -> None:
    """Two showtimes at the same minute give the time twice, in instant order, in every list."""
    film = make_film(
        "A",
        make_showtime(paris(2026, 11, 12, 20), ORIG, subtitled=True, disabled_access=True),
        make_showtime(paris(2026, 11, 12, 13, 45), ORIG, subtitled=True, disabled_access=True),
        make_showtime(paris(2026, 11, 12, 13, 45), ORIG, subtitled=True),
    )

    attributes = film_attributes(film)

    assert attributes["vost"] == ["13:45", "13:45", "20:00"]
    assert attributes["accessibility"]["pmr"] == ["13:45", "20:00"]
    assert [item["time"] for item in attributes["details"]["showtimes"]] == ["13:45", "13:45", "20:00"]


@pytest.mark.parametrize(
    ("zone", "time", "starts_at"),
    [
        ("Europe/Paris", "20:00", "2026-11-12T20:00:00+01:00"),
        ("Europe/London", "19:00", "2026-11-12T19:00:00+00:00"),
        ("America/New_York", "14:00", "2026-11-12T14:00:00-05:00"),
    ],
)
def test_same_time_in_every_list_and_zone(
    set_time_zone: Callable[[str], None], zone: str, time: str, starts_at: str
) -> None:
    """``time`` and ``starts_at`` are in Home Assistant's zone, the same in the version list, accessibility, details."""
    set_time_zone(zone)
    film = make_film("A", make_showtime(paris(2026, 11, 12, 20), ORIG, subtitled=True, disabled_access=True))

    attributes = film_attributes(film)

    assert attributes["vost"] == [time]
    assert attributes["accessibility"]["pmr"] == [time]
    assert attributes["details"]["showtimes"][0]["time"] == time
    assert attributes["details"]["showtimes"][0]["starts_at"] == starts_at


def test_empty_values_are_omitted_and_false_kept() -> None:
    """``None`` and ``()`` keys are absent; ``False`` and ``0`` are written; ratings without count."""
    film = make_film(
        "A",
        make_showtime(
            paris(2026, 11, 12, 20),
            ShowtimeVersion.LOCAL,
            formats=ShowtimeFormats(picture=("HDR",), sound=("ATMOS",), comfort=("RECLINER",)),
            preview=False,
        ),
        ref="7",
        details=FilmDetails(
            user_rating=Rating(score=3.0), press_rating=Rating(score=0.0, count=0), premiere=False, hits=0
        ),
    )

    attributes = film_attributes(film)

    assert {
        key: value for key, value in attributes.items() if key not in {"vf", "vo", "vost", "accessibility", "details"}
    } == {
        "title": "A",
        "film_id": "7",
        "user_rating": 3.0,
        "press_rating": 0.0,
        "press_rating_count": 0,
        "hits": 0,
        "premiere": False,
    }
    assert set(attributes["details"]) == {"showtimes"}
    showtime = attributes["details"]["showtimes"][0]
    assert (showtime["picture"], showtime["sound"], showtime["comfort"], showtime["preview"]) == (
        ["HDR"],
        ["ATMOS"],
        ["RECLINER"],
        False,
    )
    assert "projection" not in showtime

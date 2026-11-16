"""The store's film catalogue (design §5.1, §5.2): round trip, purge by construction, unification, strict loading."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.client import Credit, Film, FilmDetails, Rating, ShowtimeFormats, ShowtimeVersion
from custom_components.movie_showtimes.store import (
    CachedDay,
    StoredSnapshot,
    film_catalogue,
    snapshot_from_dict,
    snapshot_to_dict,
    unify_film_details,
)
from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory
import pytest

from tests import reference_films
from tests.fake_provider import make_day, make_film, make_showtime

from .helpers import TODAY, at

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
TOMORROW = TODAY + timedelta(days=1)

FULL_DETAILS = FilmDetails(
    url="https://www.allocine.fr/film/fichefilm_gen_cfilm=1.html",
    film_type="FEATURE_FILM",
    original_title="Original",
    year=2026,
    release_date="2026-11-11",
    visa_number="155420",
    runtime=121,
    genres=("Drame", "Action"),
    certificate="Tout public",
    countries=("France",),
    languages=("FRENCH",),
    directors=("Ann Example",),
    poster_url="https://img.example/p.jpg",
    synopsis="Plain.",
    synopsis_full='<p class="bo-p">Quoted "text" & <b>HTML</b></p>',
    cast=("Bob Sample",),
    credits=(Credit(name="Ann Example", role="DIRECTOR"),),
    related_tags=("Tag",),
    user_rating=Rating(score=4.02, count=1610),
    user_review_count=228,
    press_rating=Rating(score=4.45),
    want_to_see_count=2048,
    hits=777085,
    sessions=362466,
    premiere=False,
    weekly_outing=False,
    has_trailer=True,
    flags=("hasNews", "hasTrailer"),
)


def _details(count: int) -> FilmDetails:
    """Return details whose user rating count is ``count``."""
    return replace(FULL_DETAILS, user_rating=Rating(score=4.02, count=count))


def _film(title: str, day: date, ref: str | None, details: FilmDetails | None = FULL_DETAILS) -> Film:
    """Return a film with one fully enriched showtime at 20:00 on ``day``."""
    return make_film(
        title,
        make_showtime(
            at(day, 20),
            ShowtimeVersion.ORIGINAL,
            subtitled=True,
            hard_of_hearing_subtitles=False,
            disabled_access=True,
            audio_description=False,
            formats=ShowtimeFormats(projection=("F_3D", "IMAX"), experience=("SCREEN_X", "PLF")),
            preview=False,
            weekly_outing=True,
            ticket_url="https://s.example/fr/booking?a=1&code=VO; SUBTITLE",
        ),
        ref=ref,
        details=details,
    )


def _cached(day: date, *films: Film, fetched_at: datetime = NOW) -> CachedDay:
    """Return a cached day."""
    return CachedDay(showtimes=make_day("C1", day, *films), fetched_at=fetched_at)


def _snapshot(*days: CachedDay) -> StoredSnapshot:
    """Return a snapshot of these days."""
    return StoredSnapshot(last_refresh=NOW, days={cached.showtimes.day: cached for cached in days})


def _load(data: dict[str, Any]) -> StoredSnapshot:
    """Load stored data for the fake cinema."""
    return snapshot_from_dict(data, source_id="fake", cinema_id="C1", source_tz=PARIS)


@pytest.fixture(autouse=True)
def _morning(freezer: FrozenDateTimeFactory) -> None:
    """Freeze the clock on the morning of ``TODAY``."""
    freezer.move_to("2026-11-12T10:00:00+01:00")


def test_round_trip_with_every_field() -> None:
    """Every field of §3 survives; films of one ref share one details object; a film without ref keeps inline details."""
    snapshot = _snapshot(
        _cached(TODAY, _film("X", TODAY, "1"), _film("Inline", TODAY, None, _details(3))),
        _cached(TOMORROW, _film("X", TOMORROW, "1"), _film("Bare", TOMORROW, None, None)),
    )

    data = json.loads(json.dumps(snapshot_to_dict("fake", "C1", snapshot)))
    restored = _load(data)

    assert restored == snapshot
    assert list(data["films"]) == ["1"]
    first = restored.days[TODAY].showtimes.films[1]
    assert first.ref == "1"
    assert first.details is restored.days[TOMORROW].showtimes.films[1].details
    inline = data["days"][0]["films"][0]
    assert inline["title"] == "Inline"
    assert "ref" not in inline
    assert inline["details"]["user_rating"] == {"score": 4.02, "count": 3}
    assert data["films"]["1"]["press_rating"] == {"score": 4.45}


def test_omitted_and_false_keys() -> None:
    """``None`` and ``()`` are absent from the JSON, ``False`` is present."""
    film = make_film(
        "Y",
        make_showtime(at(TODAY, 20), ShowtimeVersion.DUBBED, subtitled=False),
        ref="2",
        details=FilmDetails(premiere=False),
    )

    data = snapshot_to_dict("fake", "C1", _snapshot(_cached(TODAY, film)))

    assert data["films"] == {"2": {"premiere": False}}
    assert data["days"][0]["films"][0]["showtimes"] == [
        {"starts_at": "2026-11-12T20:00:00+01:00", "version": "dubbed", "subtitled": False}
    ]
    assert _load(data).days[TODAY].showtimes.films[0] == film


def test_film_gone_from_every_day_is_purged() -> None:
    """X and Y on D and D+1, then X on no day: the catalogue has only Y."""
    before = _snapshot(
        _cached(TODAY, _film("X", TODAY, "1"), _film("Y", TODAY, "2")),
        _cached(TOMORROW, _film("X", TOMORROW, "1"), _film("Y", TOMORROW, "2")),
    )
    after = _snapshot(_cached(TODAY, _film("Y", TODAY, "2")), _cached(TOMORROW, _film("Y", TOMORROW, "2")))

    assert set(snapshot_to_dict("fake", "C1", before)["films"]) == {"1", "2"}
    assert set(snapshot_to_dict("fake", "C1", after)["films"]) == {"2"}


def test_film_on_two_days_stays_while_one_remains(freezer: FrozenDateTimeFactory) -> None:
    """X on D and D+1: saved on D+1 (D is past) X stays; once on no kept day, it is gone."""
    snapshot = _snapshot(_cached(TODAY, _film("X", TODAY, "1")), _cached(TOMORROW, _film("X", TOMORROW, "1")))
    freezer.move_to("2026-11-13T10:00:00+01:00")

    data = snapshot_to_dict("fake", "C1", snapshot)

    assert [day["date"] for day in data["days"]] == ["2026-11-13"]
    assert set(data["films"]) == {"1"}
    freezer.move_to("2026-11-14T10:00:00+01:00")
    assert snapshot_to_dict("fake", "C1", snapshot)["films"] == {}


def test_failed_day_keeps_its_films() -> None:
    """D+3 kept from an earlier refresh with film Z (on no fresh day): Z's details are in the catalogue."""
    d3 = TODAY + timedelta(days=3)
    snapshot = _snapshot(
        _cached(TODAY, _film("X", TODAY, "1"), fetched_at=NOW),
        _cached(d3, _film("Z", d3, "9", _details(5)), fetched_at=NOW - timedelta(hours=12)),
    )

    assert snapshot_to_dict("fake", "C1", snapshot)["films"]["9"]["user_rating"]["count"] == 5


def test_refetched_details_replace_the_old() -> None:
    """X on kept old D+3 (1 610 ratings) and on fresh D (1 615): catalogue and every film X have 1 615."""
    d3 = TODAY + timedelta(days=3)
    old = _cached(d3, _film("X", d3, "1", _details(1610)), fetched_at=NOW - timedelta(hours=12))
    fresh = _cached(TODAY, _film("X", TODAY, "1", _details(1615)), fetched_at=NOW)
    other = _cached(TOMORROW, _film("W", TOMORROW, None), fetched_at=NOW)

    unified, catalogue = unify_film_details({TODAY: fresh, d3: old, TOMORROW: other})

    assert catalogue["1"].user_rating == Rating(score=4.02, count=1615)
    assert unified[d3].showtimes.films[0].details is catalogue["1"]
    assert unified[TODAY] is fresh
    assert unified[TOMORROW] is other


def test_tie_goes_to_the_earliest_date() -> None:
    """Same fetch time: the details of the earliest day win."""
    days = {
        TOMORROW: _cached(TOMORROW, _film("X", TOMORROW, "1", _details(2))),
        TODAY: _cached(TODAY, _film("X", TODAY, "1", _details(1))),
    }

    assert film_catalogue(days)["1"].user_rating == Rating(score=4.02, count=1)


def test_reference_films_round_trip() -> None:
    """The real films of §6.1 survive the store unchanged."""
    films = [reference_films.COMMENT_BRAQUER, reference_films.LE_CORSET]
    day = films[0].showtimes[0].starts_at.date()
    snapshot = StoredSnapshot(last_refresh=NOW, days={day: _cached(day, *films)})

    assert _load(snapshot_to_dict("fake", "C1", snapshot)) == snapshot


def _stored() -> dict[str, Any]:
    """Return valid stored data with film X (ref "1") on today.

    Called at collection time too (parametrize), when the autouse clock is not frozen yet: freeze it here, or the
    serialisation drops the days before the real today.
    """
    with freeze_time("2026-11-12T10:00:00+01:00"):
        snapshot = _snapshot(_cached(TODAY, _film("X", TODAY, "1")))
        return json.loads(json.dumps(snapshot_to_dict("fake", "C1", snapshot)))


def test_orphan_reference_is_tolerated(caplog: pytest.LogCaptureFixture) -> None:
    """A day film whose ref has no catalogue entry loads without details, one debug line, no warning."""
    data = _stored()
    data["days"][0]["films"][0]["ref"] = "999"

    with caplog.at_level(logging.DEBUG):
        film = _load(data).days[TODAY].showtimes.films[0]

    assert (film.ref, film.details) == ("999", None)
    assert sum("has no details in the catalogue" in record.getMessage() for record in caplog.records) == 1
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]


def test_unreferenced_entry_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    """An extra catalogue entry loads, in no film."""
    data = _stored()
    data["films"]["5"] = {"runtime": 90}

    with caplog.at_level(logging.DEBUG):
        snapshot = _load(data)

    assert [film.ref for film in snapshot.days[TODAY].showtimes.films] == ["1"]
    assert any("no film refers to" in record.getMessage() for record in caplog.records)


def _set(path: tuple[Any, ...], value: object) -> dict[str, Any]:
    """Return the valid stored data with one value replaced (or removed for ``...``)."""
    data = deepcopy(_stored())
    target: Any = data
    for key in path[:-1]:
        target = target[key]
    if value is ...:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


@pytest.mark.parametrize(
    "data",
    [
        _set(("films",), ...),
        _set(("films",), []),
        _set(("films", "1"), "details"),
        _set(("films", "1", "runtime"), "x"),
        _set(("films", "1", "runtime"), True),  # noqa: FBT003
        _set(("films", "1", "premiere"), "no"),
        _set(("films", "1", "genres"), "Drame"),
        _set(("films", "1", "genres"), [1]),
        _set(("films", "1", "user_rating"), 4),
        _set(("films", "1", "user_rating"), {"score": "4"}),
        _set(("films", "1", "credits"), {}),
        _set(("films", "1", "credits"), [{"name": "A"}]),
        _set(("films", "1", "synopsis"), 3),
        _set(("days", 0, "films", 0, "ref"), 123),
        _set(("days", 0, "films", 0, "ref"), ""),
        _set(("days", 0, "films", 0, "showtimes", 0, "subtitled"), "yes"),
        _set(("days", 0, "films", 0, "showtimes", 0, "disabled_access"), 1),
        _set(("days", 0, "films", 0, "showtimes", 0, "formats"), ["IMAX"]),
        _set(("days", 0, "films", 0, "showtimes", 0, "ticket_url"), 5),
    ],
    ids=[
        "no_catalogue",
        "catalogue_list",
        "entry_string",
        "runtime_x",
        "runtime_bool",
        "premiere_string",
        "genres_string",
        "genres_int",
        "rating_number",
        "rating_score_string",
        "credits_object",
        "credit_without_role",
        "synopsis_int",
        "ref_int",
        "ref_empty",
        "subtitled_yes",
        "disabled_access_one",
        "formats_list",
        "ticket_url_int",
    ],
)
def test_rejected(data: dict[str, Any]) -> None:
    """A malformed catalogue or value rejects the whole snapshot."""
    with pytest.raises(ValueError, match="Malformed"):
        _load(data)


def test_all_empty_stored_formats_are_none() -> None:
    """A stored ``formats: {}`` comes back as ``None``."""
    data = _set(("days", 0, "films", 0, "showtimes", 0, "formats"), {})

    assert _load(data).days[TODAY].showtimes.films[0].showtimes[0].formats is None

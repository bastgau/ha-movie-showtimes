"""Enriched films through Home Assistant: sensor expiry, coordinator unification, store growth, restart, diagnostics."""

from dataclasses import fields
from datetime import date, timedelta
import json
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.client import Film, FilmDetails, Rating, ShowtimeVersion, SourceParseError
from custom_components.movie_showtimes.diagnostics import async_get_config_entry_diagnostics
from custom_components.movie_showtimes.store import snapshot_from_dict
from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider, make_day, make_film, make_showtime

from .helpers import STORE_KEY, TODAY, TODAY_ID, at, move_to, setup_entry

NOW = "2026-11-12T10:00:00+01:00"
ORIG = ShowtimeVersion.ORIGINAL


def _details(count: int) -> FilmDetails:
    """Return invented details with this rating count."""
    return FilmDetails(original_title="Invented", runtime=90, user_rating=Rating(score=4.0, count=count))


def _rich_film(day: date, ref: str = "1", count: int = 1610) -> Film:
    """Return an invented enriched film: a PMR VOST at 14:00, an SME VO at 16:00, a VF at 20:00."""
    return make_film(
        f"Film {ref}",
        make_showtime(at(day, 14), ORIG, subtitled=True, disabled_access=True, audio_description=True),
        make_showtime(at(day, 16), ORIG, subtitled=False, hard_of_hearing_subtitles=True, disabled_access=False),
        make_showtime(at(day, 20), ShowtimeVersion.DUBBED, disabled_access=True),
        ref=ref,
        details=_details(count),
    )


def _program(films_of: Any) -> None:
    """Program the 8 days from today with ``films_of(day)``."""
    for offset in range(8):
        day = TODAY + timedelta(days=offset)
        FakeProvider.days[day] = make_day("C1", day, *films_of(day))


def _stored(hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Return the stored data."""
    return hass_storage[STORE_KEY]["data"]


async def test_expired_showtimes_leave_every_list(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """After 14:15 the 14:00 showtime is gone from vost, accessibility and details.showtimes; details stay."""
    freezer.move_to(NOW)
    _program(lambda day: [_rich_film(day)])
    await setup_entry(hass)

    film = hass.states.get(TODAY_ID).attributes["films"][0]
    assert film["accessibility"] == {"pmr": ["14:00", "20:00"], "sme": ["16:00"], "audio_description": ["14:00"]}

    await move_to(hass, freezer, "2026-11-12T14:15:01+01:00")

    state = hass.states.get(TODAY_ID)
    assert state.state == "1"
    film = state.attributes["films"][0]
    assert (film["vf"], film["vo"], film["vost"]) == (["20:00"], ["16:00"], [])
    assert film["accessibility"] == {"pmr": ["20:00"], "sme": ["16:00"], "audio_description": []}
    assert [item["time"] for item in film["details"]["showtimes"]] == ["16:00", "20:00"]
    assert (film["film_id"], film["runtime"], film["user_rating_count"]) == ("1", 90, 1610)


async def test_refresh_unifies_details_before_saving(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """8 calls per refresh; a day kept after a parse error takes the refetched details, in memory and in the store."""
    freezer.move_to(NOW)
    _program(lambda day: [_rich_film(day, count=1610)])
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert len(FakeProvider.calls) == 8
    bad = TODAY + timedelta(days=3)
    freezer.tick(timedelta(hours=1))
    _program(lambda day: [_rich_film(day, count=1615)])
    FakeProvider.days[bad] = SourceParseError("changed")
    FakeProvider.calls.clear()

    await coordinator.async_refresh()

    assert len(FakeProvider.calls) == 8
    kept = coordinator.data[bad].showtimes.films[0].details
    assert kept is not None
    assert kept.user_rating == Rating(score=4.0, count=1615)
    assert kept is coordinator.data[TODAY].showtimes.films[0].details
    assert _stored(hass_storage)["films"]["1"]["user_rating"] == {"score": 4.0, "count": 1615}
    restored = snapshot_from_dict(
        _stored(hass_storage), source_id="fake", cinema_id="C1", source_tz=ZoneInfo("Europe/Paris")
    )
    assert restored.days == coordinator.data


async def test_store_does_not_grow(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """10 refreshes rotating the films: the catalogue is exactly the films of the stored days, the size bounded."""
    freezer.move_to(NOW)
    rotation = 0

    def _films(day: date) -> list[Film]:
        return [_rich_film(day, ref=str(rotation + index)) for index in range(3)]

    _program(_films)
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    first_size = len(json.dumps(_stored(hass_storage)))
    one_film = len(json.dumps(_stored(hass_storage)["films"]["0"]))

    for rotation in range(1, 11):  # read by _films
        freezer.tick(timedelta(hours=12))
        _program(_films)
        if rotation == 5:  # A partial refresh: one day keeps its previous copy.
            FakeProvider.days[TODAY + timedelta(days=7)] = SourceParseError("changed")
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        stored = _stored(hass_storage)
        refs = {film["ref"] for day in stored["days"] for film in day["films"]}
        assert set(stored["films"]) == refs
        assert len(json.dumps(stored)) <= first_size + 8 * one_film + 8 * 1000
        assert len(stored["films"]) <= 4
        restored = snapshot_from_dict(stored, source_id="fake", cinema_id="C1", source_tz=ZoneInfo("Europe/Paris"))
        first = date.fromisoformat(stored["days"][0]["date"])
        assert restored.days == {day: cached for day, cached in coordinator.data.items() if day >= first}


async def test_restart_with_details_makes_no_request(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A fresh store with details: no provider call at setup, the attributes equal those before."""
    freezer.move_to(NOW)
    _program(lambda day: [_rich_film(day)])
    entry = await setup_entry(hass)
    before = hass.states.get(TODAY_ID).attributes["films"]
    FakeProvider.calls.clear()

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert not FakeProvider.calls
    assert entry.runtime_data.restored_from_store
    assert hass.states.get(TODAY_ID).attributes["films"] == before


async def test_diagnostics_with_details(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The report has each film's ref, the four showtime flags and the film catalogue."""
    freezer.move_to(NOW)
    _program(lambda day: [_rich_film(day), make_film("Bare", (at(day, 18), ShowtimeVersion.LOCAL))])
    entry = await setup_entry(hass)

    report = await async_get_config_entry_diagnostics(hass, entry)

    detail = report["films"]["1"]
    assert detail == {
        **{item.name: None for item in fields(FilmDetails)},
        "genres": (),
        "countries": (),
        "languages": (),
        "directors": (),
        "cast": (),
        "credits": (),
        "related_tags": (),
        "flags": (),
        "original_title": "Invented",
        "runtime": 90,
        "user_rating": {"score": 4.0, "count": 1610},
    }
    today = report["days"][TODAY.isoformat()]
    assert [(film["title"], film["ref"]) for film in today["films"]] == [("Bare", None), ("Film 1", "1")]
    assert today["films"][1]["showtimes"][1] == {
        "starts_at": "2026-11-12T16:00:00+01:00",
        "version": "original",
        "subtitled": False,
        "hard_of_hearing_subtitles": True,
        "disabled_access": False,
        "audio_description": None,
    }

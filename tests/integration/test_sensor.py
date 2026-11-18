"""The day sensors: state, attributes, availability and what the recorder keeps."""

# pylint: disable=protected-access

from datetime import timedelta
from typing import Any

from custom_components.movie_showtimes.client import ShowtimeVersion, SourceConnectionError
from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider, make_day, make_film, paris

from .helpers import TODAY, TODAY_ID, TOMORROW_ID, at, program_week, setup_entry

NOW = "2026-11-12T10:00:00+01:00"


def _versions(film: dict[str, Any]) -> dict[str, Any]:
    """Keep the title and the version lists of a ``films`` item."""
    return {key: film[key] for key in ("title", "vf", "vo", "vost", "other") if key in film}


async def test_state_and_attributes(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The state counts the films still to come; the attributes list them split by version."""
    freezer.move_to(NOW)
    program_week()

    await setup_entry(hass)

    state = hass.states.get(TODAY_ID)
    assert state is not None
    assert state.state == "2"
    assert state.attributes["date"] == "2026-11-12"
    assert state.attributes["fetched_at"] == "2026-11-12T10:00:00+01:00"
    assert [_versions(film) for film in state.attributes["films"]] == [
        {"title": "Film A", "vf": ["14:00", "20:00"], "vo": [], "vost": []},
        {"title": "Film B", "vf": [], "vo": ["14:00"], "vost": []},
    ]
    assert hass.states.get(TOMORROW_ID).attributes["date"] == "2026-11-13"
    assert hass.states.get("sensor.cinema_test_in_6_days").attributes["date"] == "2026-11-18"


async def test_state_is_the_number_of_films(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Whatever the time, the state equals the number of films listed."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)

    for hour, minute in ((10, 0), (14, 15), (20, 15)):
        freezer.move_to(at(TODAY, hour, minute))
        entity = hass.data["entity_components"]["sensor"].get_entity(TODAY_ID)
        entity._handle_coordinator_update()
        state = hass.states.get(TODAY_ID)
        assert int(state.state) == len(state.attributes["films"])


async def test_unknown_version_goes_to_other(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """``other`` appears only for a film with a showtime of an unknown version."""
    freezer.move_to(NOW)
    program_week()
    FakeProvider.days[TODAY] = make_day(
        "C1",
        TODAY,
        make_film("Odd", (at(TODAY, 15), ShowtimeVersion.UNKNOWN), (at(TODAY, 16), ShowtimeVersion.LOCAL)),
        make_film("Plain", (at(TODAY, 15), ShowtimeVersion.LOCAL)),
    )

    await setup_entry(hass)

    films = hass.states.get(TODAY_ID).attributes["films"]
    assert _versions(films[0]) == {"title": "Odd", "vf": ["16:00"], "vo": [], "vost": [], "other": ["15:00"]}
    assert "other" not in films[1]


async def test_empty_day_is_zero_and_available(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A closed cinema is valid data: 0, not unavailable."""
    freezer.move_to(NOW)

    await setup_entry(hass)

    state = hass.states.get(TODAY_ID)
    assert state.state == "0"
    assert state.attributes["films"] == []
    assert state.attributes["date"] == "2026-11-12"


@pytest.mark.parametrize(
    ("zone", "expected"), [("Europe/Paris", "20:00"), ("Europe/London", "19:00"), ("America/New_York", "14:00")]
)
async def test_attributes_are_in_the_home_assistant_zone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, set_time_zone: Any, zone: str, expected: str
) -> None:
    """Times and ``fetched_at`` follow Home Assistant's zone, not the source's."""
    set_time_zone(zone)
    freezer.move_to("2026-11-12T09:00:00+00:00")
    FakeProvider.days[TODAY] = make_day("C1", TODAY, make_film("A", (paris(2026, 11, 12, 20), ShowtimeVersion.LOCAL)))

    await setup_entry(hass)

    state = hass.states.get(TODAY_ID)
    assert state.attributes["films"][0]["vf"] == [expected]
    assert state.attributes["fetched_at"].endswith(
        {"Europe/Paris": "+01:00", "Europe/London": "+00:00", "America/New_York": "-05:00"}[zone]
    )


async def test_sensor_ignores_a_failed_refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A failed refresh does not make the sensors unavailable: the last good copy stays right."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    FakeProvider.days.clear()
    FakeProvider.error = SourceConnectionError("down")
    freezer.tick(timedelta(hours=1))

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(TODAY_ID).state == "2"

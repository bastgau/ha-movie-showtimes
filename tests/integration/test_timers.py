"""Time-driven re-renders: expiring showtimes, midnight, and the data-age limit."""

# pylint: disable=protected-access

from datetime import timedelta
from typing import Any

from custom_components.movie_showtimes.client import ShowtimeVersion, SourceConnectionError
from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider, make_day, make_film

from .helpers import TODAY, TODAY_ID, TOMORROW_ID, at, move_to, program_week, setup_entry, standard_day

NOW = "2026-11-12T10:00:00+01:00"


def _titles(hass: HomeAssistant, entity_id: str = TODAY_ID) -> list[tuple[str, list[str]]]:
    """Return the (title, vf) pairs of a sensor."""
    state = hass.states.get(entity_id)
    assert state is not None
    return [(film["title"], film["vf"]) for film in state.attributes["films"]]


async def test_showtimes_drop_out_after_the_grace_period(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A showtime is shown until 15 minutes after its start; both 14:00 ones go at once, with no request."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    calls = len(FakeProvider.calls)
    assert hass.states.get(TODAY_ID).state == "2"

    for moment in ("14:00:00", "14:14:00", "14:14:59"):
        await move_to(hass, freezer, f"2026-11-12T{moment}+01:00")
        assert hass.states.get(TODAY_ID).state == "2"
        assert _titles(hass) == [("Film A", ["14:00", "20:00"]), ("Film B", [])]

    await move_to(hass, freezer, "2026-11-12T14:15:00+01:00")
    assert hass.states.get(TODAY_ID).state == "1"
    assert _titles(hass) == [("Film A", ["20:00"])]

    await move_to(hass, freezer, "2026-11-12T20:14:00+01:00")
    assert hass.states.get(TODAY_ID).state == "1"

    await move_to(hass, freezer, "2026-11-12T20:15:00+01:00")
    state = hass.states.get(TODAY_ID)
    assert state.state == "0"
    assert state.attributes["films"] == []
    assert len(FakeProvider.calls) == calls


async def test_next_day_is_untouched_by_todays_timers(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The timer is re-armed at the earliest later expiry, tomorrow included, and tomorrow is unchanged until then."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)

    await move_to(hass, freezer, "2026-11-12T20:15:00+01:00")

    assert hass.states.get(TOMORROW_ID).state == "2"
    assert entry.runtime_data._unsub_showtime is not None
    await move_to(hass, freezer, "2026-11-12T21:00:00+01:00")
    assert hass.states.get(TOMORROW_ID).state == "2"


async def test_refresh_does_not_bring_back_expired_showtimes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A refresh returning the full day again keeps the past showtimes hidden and re-arms the timer."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    await move_to(hass, freezer, "2026-11-12T15:00:00+01:00")
    assert hass.states.get(TODAY_ID).state == "1"

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(TODAY_ID).state == "1"
    assert _titles(hass) == [("Film A", ["20:00"])]
    await move_to(hass, freezer, "2026-11-12T20:14:59+01:00")
    assert hass.states.get(TODAY_ID).state == "1"
    await move_to(hass, freezer, "2026-11-12T20:15:00+01:00")
    assert hass.states.get(TODAY_ID).state == "0"


async def test_timer_is_kept_after_a_failed_refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A failed refresh leaves the armed timer alone; when it fires, the previous data is still rendered."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    timer = coordinator._unsub_showtime
    assert timer is not None
    FakeProvider.error = SourceConnectionError("down")
    FakeProvider.days.clear()

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert coordinator._unsub_showtime is timer
    await move_to(hass, freezer, "2026-11-12T14:15:00+01:00")
    state = hass.states.get(TODAY_ID)
    assert state.state == "1"
    assert state.state != "unavailable"


async def test_midnight_rollover(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """At midnight, Today shows tomorrow's data and In 6 days shows day 7's, with no request."""
    freezer.move_to("2026-11-12T23:59:00+01:00")
    program_week()
    await setup_entry(hass)
    calls = len(FakeProvider.calls)
    assert hass.states.get(TODAY_ID).attributes["date"] == "2026-11-12"
    assert hass.states.get("sensor.cinema_test_in_6_days").attributes["date"] == "2026-11-18"

    await move_to(hass, freezer, "2026-11-13T00:00:00+01:00")

    today = hass.states.get(TODAY_ID)
    assert today.attributes["date"] == "2026-11-13"
    assert today.state == "2"
    assert _titles(hass) == [("Film A", ["14:00", "20:00"]), ("Film B", [])]
    assert hass.states.get("sensor.cinema_test_in_6_days").attributes["date"] == "2026-11-19"
    assert hass.states.get("sensor.cinema_test_in_6_days").state == "2"
    assert len(FakeProvider.calls) == calls


async def test_grace_period_does_not_cross_midnight(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A 23:50 showtime is shown at 23:59:59 and is gone from Today at midnight, because the day changes."""
    freezer.move_to("2026-11-12T23:00:00+01:00")
    program_week()
    FakeProvider.days[TODAY] = make_day("C1", TODAY, make_film("Late", (at(TODAY, 23, 50), ShowtimeVersion.LOCAL)))
    await setup_entry(hass)

    await move_to(hass, freezer, "2026-11-12T23:59:59+01:00")
    assert hass.states.get(TODAY_ID).state == "1"

    await move_to(hass, freezer, "2026-11-13T00:00:00+01:00")
    assert "Late" not in [title for title, _ in _titles(hass)]
    assert hass.states.get(TODAY_ID).attributes["date"] == "2026-11-13"


async def test_data_is_withdrawn_after_48_hours_of_outage(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """With the source down, each sensor becomes unavailable once its data is over 48 hours old."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    FakeProvider.error = SourceConnectionError("down")
    FakeProvider.days.clear()

    await move_to(hass, freezer, "2026-11-14T09:00:00+01:00")
    assert hass.states.get(TODAY_ID).state == "2"

    await move_to(hass, freezer, "2026-11-14T10:01:00+01:00")
    assert hass.states.get(TODAY_ID).state == "unavailable"
    assert hass.states.get(TOMORROW_ID).state == "unavailable"


async def test_timer_stops_with_nothing_left(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """With no data at all there is nothing to arm."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data

    coordinator._async_schedule_next_showtime(None)
    coordinator._async_schedule_next_showtime({})

    assert coordinator._unsub_showtime is None


async def test_midnight_without_data_changes_nothing(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: Any
) -> None:
    """A midnight tick on an empty-day cinema still works."""
    freezer.move_to(NOW)
    FakeProvider.days[TODAY + timedelta(days=1)] = standard_day(TODAY + timedelta(days=1))
    await setup_entry(hass)

    await move_to(hass, freezer, "2026-11-13T00:00:00+01:00")

    assert hass.states.get(TODAY_ID).state == "2"

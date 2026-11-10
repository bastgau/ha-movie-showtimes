"""Diagnostics: the entry, the source, the coordinator and every fetched day."""

from datetime import UTC, datetime, timedelta
from typing import Any

from custom_components.movie_showtimes.client import SourceConnectionError
from custom_components.movie_showtimes.diagnostics import async_get_config_entry_diagnostics
from freezegun.api import FrozenDateTimeFactory

from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider

from .helpers import prefill, program_week, setup_entry, stored_data

NOW = "2026-11-12T10:00:00+01:00"
NOW_UTC = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


async def test_diagnostics_after_a_refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The report lists the source, the status of the last refresh and every day, unfiltered."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    freezer.tick(timedelta(minutes=30))

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"] == {
        "title": "Cinema Test",
        "data": {"source": "fake", "cinema_id": "C1"},
        "unique_id": "fake_C1",
    }
    assert result["source"] == {"id": "fake", "name": "Fake Cinemas", "time_zone": "Europe/Paris"}
    assert result["coordinator"] == {
        "last_update_success": True,
        "last_exception": None,
        "update_interval": "12:00:00",
        "last_refresh": "2026-11-12T09:00:00+00:00",
        "restored_from_store": False,
        "data_age_seconds": 1800.0,
    }
    assert list(result["days"]) == [f"2026-11-{day}" for day in range(12, 20)]
    today = result["days"]["2026-11-12"]
    assert today["film_count"] == 2
    assert today["fetched_at"] == "2026-11-12T09:00:00+00:00"
    assert today["films"][0] == {
        "title": "Film A",
        "showtimes": [
            {"starts_at": "2026-11-12T14:00:00+01:00", "version": "dubbed"},
            {"starts_at": "2026-11-12T20:00:00+01:00", "version": "local"},
        ],
    }


async def test_diagnostics_after_a_restore(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """After a restart, the report says the data came from the store and when it was fetched."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=NOW_UTC - timedelta(hours=2)))
    entry = await setup_entry(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"]["restored_from_store"] is True
    assert result["coordinator"]["last_refresh"] == "2026-11-12T07:00:00+00:00"
    assert result["coordinator"]["data_age_seconds"] == 7200.0
    assert result["days"]["2026-11-12"]["fetched_at"] == "2026-11-12T07:00:00+00:00"


async def test_diagnostics_without_data(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A coordinator that never refreshed reports no data and no age."""
    freezer.move_to(NOW)
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    coordinator.data = None
    coordinator.last_refresh = None

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["days"] == {}
    assert result["coordinator"]["last_refresh"] is None
    assert result["coordinator"]["data_age_seconds"] is None


async def test_diagnostics_after_a_failed_refresh(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The last exception is reported."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    FakeProvider.error = SourceConnectionError("down")
    FakeProvider.days.clear()
    await entry.runtime_data.async_refresh()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["coordinator"]["last_update_success"] is False
    assert "UpdateFailed" in result["coordinator"]["last_exception"]

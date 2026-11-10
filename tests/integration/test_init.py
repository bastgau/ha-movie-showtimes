"""Setup, unload and removal of the entry, and the device and entities it creates."""

# pylint: disable=protected-access

from typing import Any

from custom_components.movie_showtimes.client import SourceConnectionError
from custom_components.movie_showtimes.const import DOMAIN
from freezegun.api import FrozenDateTimeFactory

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from tests.fake_provider import FakeProvider, FakeProvider2

from .helpers import STORE_KEY, make_entry, move_to, program_week, setup_entry

NOW = "2026-11-12T10:00:00+01:00"


async def test_setup_creates_device_and_sensors(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Setup creates the cinema's device and its seven day sensors, with namespaced ids."""
    freezer.move_to(NOW)
    program_week()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.cinema_id == "C1"
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "fake_C1"), entry.entry_id)
    assert device is not None
    assert device.name == "Cinema Test"
    assert device.manufacturer == "Fake Cinemas"
    assert device.entry_type is DeviceEntryType.SERVICE
    assert device.configuration_url == "https://fake.example/C1"

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert sorted(e.unique_id for e in entities) == [f"fake_C1_day_{i}" for i in range(7)]
    assert sorted(e.entity_id for e in entities) == sorted(
        f"sensor.cinema_test_{name}"
        for name in ("today", "tomorrow", "in_2_days", "in_3_days", "in_4_days", "in_5_days", "in_6_days")
    )
    assert len(FakeProvider.calls) == 8


async def test_second_source_has_no_configuration_url(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, two_sources: None
) -> None:
    """A source without a cinema page gives a device without a configuration URL, and its own manufacturer."""
    freezer.move_to(NOW)
    entry = make_entry(data={"source": "fake2", "cinema_id": "C1"}, unique_id="fake2_C1")

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "fake2_C1"), entry.entry_id)
    assert device is not None
    assert device.manufacturer == "Other Cinemas"
    assert device.configuration_url is None
    assert FakeProvider2.calls
    assert not FakeProvider.calls


async def test_same_cinema_id_in_two_sources(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, two_sources: None
) -> None:
    """The same cinema id under two sources makes two devices and 14 sensors, with no collision."""
    freezer.move_to(NOW)
    first = await setup_entry(hass)
    second = await setup_entry(
        hass,
        make_entry(
            entry_id="entryc2", data={"source": "fake2", "cinema_id": "C1"}, unique_id="fake2_C1", title="Other"
        ),
    )

    assert first.state is ConfigEntryState.LOADED
    assert second.state is ConfigEntryState.LOADED
    unique_ids = {e.unique_id for e in er.async_get(hass).entities.values() if e.platform == DOMAIN}
    assert len(unique_ids) == 14


async def test_unknown_source_is_a_setup_error(hass: HomeAssistant) -> None:
    """An entry whose source this version does not provide fails for good, with a translated reason."""
    entry = make_entry(data={"source": "gone", "cinema_id": "C1"}, unique_id="gone_C1")

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.reason is not None
    assert "gone" in entry.reason


async def test_nothing_stored_and_source_down_retries(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """With nothing stored, an unreachable source makes the entry retry."""
    freezer.move_to(NOW)
    FakeProvider.error = SourceConnectionError("down")

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(FakeProvider.calls) == 1


async def test_unload_cancels_the_timers(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """After an unload, neither midnight nor a showtime's end touches anything, and nothing is requested."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert coordinator._unsub_showtime is not None
    calls = len(FakeProvider.calls)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator._unsub_showtime is None
    await move_to(hass, freezer, "2026-11-13T00:00:00+01:00")
    await move_to(hass, freezer, "2026-11-13T14:15:00+01:00")
    assert len(FakeProvider.calls) == calls


async def test_reload_keeps_the_store(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Unloading or reloading keeps the stored showtimes."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    assert STORE_KEY in hass_storage

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert STORE_KEY in hass_storage
    assert len(FakeProvider.calls) == 8


async def test_remove_deletes_the_store(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Removing the entry removes its file."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    assert STORE_KEY in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert STORE_KEY not in hass_storage


async def test_remove_without_a_file(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Removing an entry that never stored anything raises nothing."""
    entry = make_entry(data={"source": "gone", "cinema_id": "C1"})
    entry.add_to_hass(hass)

    await hass.config_entries.async_remove(entry.entry_id)

    assert STORE_KEY not in hass_storage
    assert not hass.config_entries.async_entries(DOMAIN)

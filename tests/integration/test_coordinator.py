"""The coordinator's refresh policy: which days it requests, and what a failure keeps or drops."""

from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

from custom_components.movie_showtimes.client import (
    CinemaNotFoundError,
    ShowtimesError,
    SourceAccessDeniedError,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
)
from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider

from .helpers import STORE_KEY, TODAY, TODAY_ID, program_week, setup_entry, standard_day, tick

NOW = "2026-11-12T10:00:00+01:00"
NOW_UTC = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


async def test_requests_eight_days_from_today_in_the_home_assistant_zone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, set_time_zone: Any
) -> None:
    """The first date is today where Home Assistant is, not in UTC; the next seven follow in order."""
    set_time_zone("Pacific/Auckland")
    freezer.move_to("2026-11-12T11:30:00+00:00")

    await setup_entry(hass)

    assert [day for _, day in FakeProvider.calls] == [date(2026, 11, 13) + timedelta(days=i) for i in range(8)]
    assert {cinema_id for cinema_id, _ in FakeProvider.calls} == {"C1"}


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (SourceConnectionError("down"), "cannot_connect"),
        (SourceTimeoutError("slow"), "cannot_connect"),
        (CinemaNotFoundError("gone"), "cinema_not_found"),
    ],
)
async def test_connection_failure_stops_the_refresh_and_keeps_the_data(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any], error: ShowtimesError, key: str
) -> None:
    """The refresh stops at the first failing day; sensors keep the previous data; the store is untouched."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    stored = repr(hass_storage[STORE_KEY])
    FakeProvider.calls.clear()
    FakeProvider.days[TODAY + timedelta(days=3)] = error

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert [day for _, day in FakeProvider.calls] == [TODAY + timedelta(days=i) for i in range(4)]
    assert not coordinator.last_update_success
    assert getattr(coordinator.last_exception, "translation_key", None) == key
    assert repr(hass_storage[STORE_KEY]) == stored
    state = hass.states.get(TODAY_ID)
    assert state is not None
    assert state.state == "2"


async def test_parse_error_keeps_the_previous_copy_of_that_day(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A day that cannot be parsed keeps its previous copy and its old fetch time; the others are fresh."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    freezer.tick(timedelta(hours=1))
    bad = TODAY + timedelta(days=3)
    FakeProvider.days[bad] = SourceParseError("changed")

    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data[bad].fetched_at == NOW_UTC
    assert coordinator.data[TODAY].fetched_at == NOW_UTC + timedelta(hours=1)
    assert len(coordinator.data) == 8
    by_date = {day["date"]: day["fetched_at"] for day in hass_storage[STORE_KEY]["data"]["days"]}
    assert by_date[bad.isoformat()] == "2026-11-12T09:00:00+00:00"
    assert by_date[TODAY.isoformat()] == "2026-11-12T10:00:00+00:00"


async def test_parse_error_without_a_previous_copy_leaves_the_day_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """With no previous copy, the failing day's sensor is unavailable while the others work."""
    freezer.move_to(NOW)
    program_week()
    FakeProvider.days[TODAY + timedelta(days=3)] = SourceParseError("changed")

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert TODAY + timedelta(days=3) not in entry.runtime_data.data
    assert hass.states.get("sensor.cinema_test_in_3_days").state == "unavailable"
    assert hass.states.get("sensor.cinema_test_in_2_days").state == "2"
    assert hass.states.get("sensor.cinema_test_in_4_days").state == "2"


async def test_stale_copy_is_not_carried_over(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A previous copy older than 48 hours is not kept for a day that fails to parse."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    freezer.tick(timedelta(hours=49))
    program_week(TODAY + timedelta(days=2))
    FakeProvider.days[TODAY + timedelta(days=4)] = SourceParseError("changed")

    await coordinator.async_refresh()

    assert TODAY + timedelta(days=4) not in coordinator.data
    assert TODAY + timedelta(days=5) in coordinator.data


async def test_every_day_failing_to_parse_is_a_failure(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """When nothing can be parsed the refresh fails, with the previous data still shown."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    FakeProvider.error = SourceParseError("changed")
    FakeProvider.days.clear()

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not coordinator.last_update_success
    assert getattr(coordinator.last_exception, "translation_key", None) == "invalid_response"
    assert hass.states.get(TODAY_ID).state == "2"


async def test_every_day_failing_to_parse_at_setup_retries(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """With nothing stored and nothing parsable, the entry retries."""
    freezer.move_to(NOW)
    FakeProvider.error = SourceParseError("changed")

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert len(FakeProvider.calls) == 8


async def test_recovery_after_a_failure(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """The next refresh after an outage brings fresh data and a new fetch time."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    FakeProvider.error = SourceConnectionError("down")
    FakeProvider.days.clear()
    await coordinator.async_refresh()
    assert not coordinator.last_update_success

    FakeProvider.error = None
    program_week()
    freezer.tick(timedelta(hours=1))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert coordinator.data[TODAY].fetched_at == NOW_UTC + timedelta(hours=1)
    assert coordinator.last_refresh == NOW_UTC + timedelta(hours=1)


async def test_refresh_every_twelve_hours(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A refresh every 12 hours, and none before."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    assert len(FakeProvider.calls) == 8

    await tick(hass, freezer, timedelta(hours=11, minutes=59))
    assert len(FakeProvider.calls) == 8

    await tick(hass, freezer, timedelta(minutes=1))
    assert len(FakeProvider.calls) == 16

    await tick(hass, freezer, timedelta(hours=11, minutes=59))
    assert len(FakeProvider.calls) == 16

    await tick(hass, freezer, timedelta(minutes=1))
    assert len(FakeProvider.calls) == 24


@pytest.mark.parametrize(("status", "shown"), [(403, "403"), (429, "429"), (None, "?")])
async def test_access_denied_is_a_translated_update_failure(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, status: int | None, shown: str
) -> None:
    """A refusal fails the refresh with the ``access_denied`` message showing the status."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    FakeProvider.error = SourceAccessDeniedError("refused", status_code=status)
    FakeProvider.days.clear()

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    error = coordinator.last_exception
    assert not coordinator.last_update_success
    assert getattr(error, "translation_key", None) == "access_denied"
    assert getattr(error, "translation_placeholders", {})["status"] == shown
    assert shown in str(error)
    assert hass.states.get(TODAY_ID).state == "2"


async def test_access_denied_at_setup_retries(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A refusal at the first refresh, with nothing stored, retries the setup."""
    freezer.move_to(NOW)
    FakeProvider.error = SourceAccessDeniedError("refused", status_code=403)

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_access_denied_is_warned_once_while_it_continues(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Our warning (with the status) appears when the refusal starts, not on every failing refresh."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    FakeProvider.error = SourceAccessDeniedError("refused", status_code=429)
    FakeProvider.days.clear()

    for _ in range(3):
        await coordinator.async_refresh()
    await hass.async_block_till_done()

    ours = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "custom_components.movie_showtimes.coordinator"
    ]
    assert len(ours) == 1
    assert "HTTP 429" in ours[0].getMessage()

    FakeProvider.error = None
    program_week()
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    caplog.clear()
    FakeProvider.error = SourceAccessDeniedError("refused", status_code=403)
    FakeProvider.days.clear()

    await coordinator.async_refresh()

    assert any("HTTP 403" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


OUR_LOGGER = "custom_components.movie_showtimes.coordinator"


def _ours(caplog: pytest.LogCaptureFixture, level: int = logging.WARNING) -> list[logging.LogRecord]:
    """Return the records of our coordinator at ``level`` or above."""
    return [r for r in caplog.records if r.name == OUR_LOGGER and r.levelno >= level]


def _parse_records(caplog: pytest.LogCaptureFixture, level: int = logging.WARNING) -> list[logging.LogRecord]:
    """Return our "Ignoring the showtimes" records at ``level`` or above."""
    return [r for r in _ours(caplog, level) if "Ignoring the showtimes" in r.getMessage()]


@pytest.mark.parametrize(
    ("error", "delay"),
    [
        (SourceConnectionError("down"), timedelta(minutes=30)),
        (SourceTimeoutError("slow"), timedelta(minutes=30)),
        (SourceAccessDeniedError("refused", status_code=403), timedelta(hours=12)),
        (CinemaNotFoundError("gone"), timedelta(hours=12)),
        (SourceParseError("changed"), timedelta(hours=12)),
    ],
)
async def test_next_attempt_after_a_failure(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, error: ShowtimesError, delay: timedelta
) -> None:
    """A connection error or timeout is retried after 30 minutes; the other failures wait the usual 12 hours."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    FakeProvider.error = error
    FakeProvider.days.clear()
    FakeProvider.calls.clear()

    await tick(hass, freezer, timedelta(hours=12))  # The failing refresh.
    FakeProvider.calls.clear()

    await tick(hass, freezer, delay - timedelta(seconds=1))
    assert not FakeProvider.calls
    await tick(hass, freezer, timedelta(seconds=1))
    assert FakeProvider.calls


async def test_interval_is_back_to_twelve_hours_after_a_successful_retry(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """After a retry that works, the following refresh is 12 hours later."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    FakeProvider.error = SourceConnectionError("down")
    FakeProvider.days.clear()
    await tick(hass, freezer, timedelta(hours=12))
    FakeProvider.error = None
    program_week()
    FakeProvider.calls.clear()

    await tick(hass, freezer, timedelta(minutes=30))
    assert len(FakeProvider.calls) == 8

    await tick(hass, freezer, timedelta(hours=11, minutes=59))
    assert len(FakeProvider.calls) == 8
    await tick(hass, freezer, timedelta(minutes=1))
    assert len(FakeProvider.calls) == 16


async def test_failed_retries_add_no_warning(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Retrying every 30 minutes during an outage logs nothing from our logger above debug."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    FakeProvider.error = SourceConnectionError("down")
    FakeProvider.days.clear()

    await tick(hass, freezer, timedelta(hours=12))  # Home Assistant itself logs when the outage starts.
    caplog.clear()
    FakeProvider.calls.clear()
    for _ in range(4):
        await tick(hass, freezer, timedelta(minutes=30))

    assert len(FakeProvider.calls) == 4
    assert not _ours(caplog)


async def test_parse_failure_is_warned_once_per_episode(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """One warning for the first failing day of the first failing refresh; debug afterwards; reset when clean."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    for offset in (2, 3):
        FakeProvider.days[TODAY + timedelta(days=offset)] = SourceParseError("changed")
    caplog.clear()

    with caplog.at_level(logging.DEBUG, logger=OUR_LOGGER):
        await coordinator.async_refresh()
        assert len(_parse_records(caplog)) == 1
        assert len(_parse_records(caplog, logging.DEBUG)) == 2

        caplog.clear()
        await coordinator.async_refresh()
        assert not _parse_records(caplog)
        assert len(_parse_records(caplog, logging.DEBUG)) == 2

        FakeProvider.days.update({TODAY + timedelta(days=i): standard_day(TODAY + timedelta(days=i)) for i in (2, 3)})
        await coordinator.async_refresh()  # A clean refresh closes the episode.

        caplog.clear()
        FakeProvider.days[TODAY + timedelta(days=2)] = SourceParseError("changed again")
        await coordinator.async_refresh()
        assert len(_parse_records(caplog)) == 1


async def test_connection_error_does_not_reset_the_parse_failure_flag(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """An aborted refresh leaves the episode open: the next parse failure is not warned again."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    FakeProvider.days[TODAY + timedelta(days=2)] = SourceParseError("changed")
    await coordinator.async_refresh()
    assert coordinator.last_update_success

    FakeProvider.days[TODAY + timedelta(days=5)] = SourceConnectionError("down")
    await coordinator.async_refresh()
    assert not coordinator.last_update_success

    FakeProvider.days[TODAY + timedelta(days=5)] = standard_day(TODAY + timedelta(days=5))
    caplog.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.last_update_success
    assert not _parse_records(caplog)


async def test_no_save_while_the_entry_is_being_removed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """The snapshot is saved at setup, and a refresh that ends once the entry is unloaded does not save again."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    coordinator = entry.runtime_data
    assert STORE_KEY in hass_storage

    await hass.config_entries.async_unload(entry.entry_id)
    hass_storage.pop(STORE_KEY, None)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert STORE_KEY not in hass_storage


async def test_removing_the_entry_removes_the_store_for_good(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """After a removal the store file stays gone."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    assert STORE_KEY in hass_storage

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert STORE_KEY not in hass_storage

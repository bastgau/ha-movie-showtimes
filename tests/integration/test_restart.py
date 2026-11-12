"""Restarts: the store is pre-filled through ``hass_storage`` and the setup decides what to fetch."""

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.client import SourceConnectionError, SourceParseError
from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider

from .helpers import (
    STORE_KEY,
    TODAY,
    TODAY_ID,
    at,
    move_to,
    prefill,
    program_week,
    setup_entry,
    stored_data,
    tick,
)

NOW = "2026-11-12T10:00:00+01:00"
NOW_UTC = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def _ago(**delta: float) -> datetime:
    """Return the time ``delta`` before the frozen now, in UTC."""
    return NOW_UTC - timedelta(**delta)


async def test_fresh_store_makes_no_request(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Fresh data is shown as it is; the refresh comes 12 hours after the stored fetch, then every 12 hours."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=2)))
    program_week()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.restored_from_store
    assert not FakeProvider.calls
    state = hass.states.get(TODAY_ID)
    assert state is not None
    assert state.state == "2"
    assert state.attributes["fetched_at"] == "2026-11-12T08:00:00+01:00"

    await tick(hass, freezer, timedelta(hours=9, minutes=59))
    assert not FakeProvider.calls

    await tick(hass, freezer, timedelta(minutes=1))
    assert len(FakeProvider.calls) == 8

    await tick(hass, freezer, timedelta(hours=11, minutes=59))
    assert len(FakeProvider.calls) == 8
    await tick(hass, freezer, timedelta(minutes=1))
    assert len(FakeProvider.calls) == 16


async def test_stale_store_refreshes_at_setup(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Data older than 12 hours is refreshed at setup and the store is rewritten."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=13)))
    program_week()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert len(FakeProvider.calls) == 8
    assert hass.states.get(TODAY_ID).attributes["fetched_at"] == NOW
    assert hass_storage[STORE_KEY]["data"]["last_refresh"] == "2026-11-12T09:00:00+00:00"


async def test_stale_store_and_source_down_serves_the_stored_data(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """The stored data is shown rather than failing the setup; the next attempt is 30 minutes later."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=13)))
    FakeProvider.error = SourceConnectionError("down")

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert len(FakeProvider.calls) == 1
    assert hass.states.get(TODAY_ID).state == "2"
    assert "unreachable, showing the showtimes fetched at 2026-11-11T20:00:00+00:00" in caplog.text

    await tick(hass, freezer, timedelta(minutes=29, seconds=59))
    assert len(FakeProvider.calls) == 1
    await tick(hass, freezer, timedelta(seconds=1))
    assert len(FakeProvider.calls) == 2

    # The retry failed too: the next one is again 30 minutes later, not 12 hours.
    await tick(hass, freezer, timedelta(minutes=29, seconds=59))
    assert len(FakeProvider.calls) == 2
    await tick(hass, freezer, timedelta(seconds=1))
    assert len(FakeProvider.calls) == 3


async def test_setup_fallback_retry_then_back_to_twelve_hours(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Stale store and source down: one retry after 30 minutes; once it succeeds the interval is 12 hours again."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=13)))
    FakeProvider.error = SourceConnectionError("down")
    entry = await setup_entry(hass)
    assert entry.runtime_data.update_interval == timedelta(minutes=30)
    FakeProvider.error = None
    program_week()

    await tick(hass, freezer, timedelta(minutes=30))

    assert len(FakeProvider.calls) == 9
    assert entry.runtime_data.update_interval == timedelta(hours=12)
    await tick(hass, freezer, timedelta(hours=11, minutes=59))
    assert len(FakeProvider.calls) == 9
    await tick(hass, freezer, timedelta(minutes=1))
    assert len(FakeProvider.calls) == 17


@pytest.mark.parametrize(
    "data",
    [
        stored_data(last_refresh=NOW_UTC - timedelta(hours=50)),
        stored_data(last_refresh=NOW_UTC - timedelta(hours=13), start=TODAY - timedelta(days=10)),
    ],
    ids=["all_too_old", "all_in_the_past"],
)
async def test_unusable_store_and_source_down_retries(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any], data: dict[str, Any]
) -> None:
    """Stored data with nothing left to show does not stand in for a live source."""
    freezer.move_to(NOW)
    prefill(hass_storage, data)
    FakeProvider.error = SourceConnectionError("down")

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(("start", "offset"), [(TODAY, "+01:00"), (date(2026, 7, 14), "+02:00")])
async def test_store_is_written_after_a_refresh(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any], start: date, offset: str
) -> None:
    """The store holds the exact JSON: UTC fetch times, Paris start times and version values."""
    freezer.move_to(datetime.combine(start, datetime.min.time(), tzinfo=ZoneInfo("Europe/Paris")) + timedelta(hours=10))
    program_week(start)

    await setup_entry(hass)

    expected_refresh = datetime.combine(start, datetime.min.time(), tzinfo=ZoneInfo("Europe/Paris")) + timedelta(
        hours=10
    )
    assert hass_storage[STORE_KEY]["version"] == 1
    assert hass_storage[STORE_KEY]["minor_version"] == 1
    assert hass_storage[STORE_KEY]["data"] == stored_data(last_refresh=expected_refresh.astimezone(UTC), start=start)
    data = hass_storage[STORE_KEY]["data"]
    assert data["days"][0]["films"][0]["showtimes"][0] == {
        "starts_at": f"{start.isoformat()}T14:00:00{offset}",
        "version": "dubbed",
    }
    assert data["last_refresh"].endswith("+00:00")
    assert [day["date"] for day in data["days"]] == [(start + timedelta(days=i)).isoformat() for i in range(8)]


async def test_round_trip_through_a_reload(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A reload restores equal data, with Paris time zones, and makes no request."""
    freezer.move_to(NOW)
    program_week()
    entry = await setup_entry(hass)
    before = dict(entry.runtime_data.data)
    FakeProvider.calls.clear()

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = entry.runtime_data.data
    assert entry.runtime_data.restored_from_store
    assert after == before
    assert after[TODAY].showtimes.films[0].showtimes[0].starts_at.tzinfo == ZoneInfo("Europe/Paris")
    assert not FakeProvider.calls


async def test_partial_refresh_at_setup_keeps_the_stored_copy(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A day failing to parse at a stale setup keeps its stored copy and fetch time, in memory and in the store."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=13)))
    program_week()
    bad = TODAY + timedelta(days=3)
    FakeProvider.days[bad] = SourceParseError("changed")

    entry = await setup_entry(hass)

    assert entry.runtime_data.data[bad].fetched_at == _ago(hours=13)
    by_date = {day["date"]: day["fetched_at"] for day in hass_storage[STORE_KEY]["data"]["days"]}
    assert by_date[bad.isoformat()] == _ago(hours=13).isoformat()
    assert by_date[TODAY.isoformat()] == NOW_UTC.isoformat()


def _break(mutate: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a function applying ``mutate`` to a copy of the data."""

    def _apply(data: dict[str, Any]) -> dict[str, Any]:
        copy = deepcopy(data)
        mutate(copy)
        return copy

    return _apply


@pytest.mark.parametrize(
    "corrupt",
    [
        _break(lambda d: d.pop("days")),
        _break(lambda d: d["days"][0].update(date="2026-13-45")),
        _break(lambda d: d["days"][0]["films"][0]["showtimes"][0].update(starts_at="2026-11-12T14:00:00")),
        _break(lambda d: d.update(last_refresh="2026-11-12T08:00:00")),
        _break(lambda d: d["days"][0].update(fetched_at=123)),
        _break(lambda d: d["days"][0]["films"][0]["showtimes"][0].update(version="klingon")),
        _break(lambda d: d.update(cinema_id="OTHER")),
        _break(lambda d: d.update(source="other")),
        _break(lambda d: d.pop("source")),
        _break(lambda d: d["days"][0]["films"][0].update(showtimes=[])),
        _break(lambda d: d["days"][0]["films"][0].update(title=" ")),
        lambda d: {},
    ],
    ids=[
        "missing_days",
        "bad_date",
        "naive_start",
        "naive_last_refresh",
        "bad_fetched_at",
        "unknown_version",
        "other_cinema",
        "other_source",
        "no_source",
        "film_without_showtimes",
        "empty_title",
        "empty_data",
    ],
)
async def test_invalid_store_is_treated_as_nothing_stored(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    corrupt: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """A store that does not validate is ignored: the setup refreshes, and does not crash."""
    freezer.move_to(NOW)
    prefill(hass_storage, corrupt(stored_data(last_refresh=_ago(hours=2))))
    program_week()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert len(FakeProvider.calls) == 8
    assert not entry.runtime_data.restored_from_store


async def test_older_minor_version_is_loaded_as_is(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A store of an older minor version is used."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=2)), minor_version=0)

    entry = await setup_entry(hass)

    assert entry.runtime_data.restored_from_store
    assert not FakeProvider.calls


async def test_older_major_version_is_dropped(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A store of an older major version is nothing stored."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=2)), version=0)
    program_week()

    entry = await setup_entry(hass)

    assert not entry.runtime_data.restored_from_store
    assert len(FakeProvider.calls) == 8


async def test_newer_major_version_is_dropped_then_overwritten(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A store written by a later version is ignored, and the next save writes version 1."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=2)), version=2)
    program_week()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert not entry.runtime_data.restored_from_store
    assert len(FakeProvider.calls) == 8
    assert hass_storage[STORE_KEY]["version"] == 1
    assert "Ignoring the stored showtimes" in caplog.text


async def test_grace_period_applies_at_setup(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Set up at 14:20, the 14:00 showtimes are not shown; the 14:10 one is until 14:25; no request."""
    freezer.move_to("2026-11-12T14:20:00+01:00")
    data = stored_data(last_refresh=at(TODAY, 12, 20).astimezone(UTC))
    data["days"][0]["films"][1]["showtimes"].append({"starts_at": at(TODAY, 14, 10).isoformat(), "version": "original"})
    prefill(hass_storage, data)

    await setup_entry(hass)

    state = hass.states.get(TODAY_ID)
    assert state is not None
    assert state.state == "2"
    assert [{key: film[key] for key in ("title", "vf", "vo", "vost")} for film in state.attributes["films"]] == [
        {"title": "Film A", "vf": ["20:00"], "vo": [], "vost": []},
        {"title": "Film B", "vf": [], "vo": ["14:10"], "vost": []},
    ]

    await move_to(hass, freezer, "2026-11-12T14:24:59+01:00")
    assert hass.states.get(TODAY_ID).state == "2"
    await move_to(hass, freezer, "2026-11-12T14:25:00+01:00")
    assert hass.states.get(TODAY_ID).state == "1"
    assert not FakeProvider.calls


async def test_missing_day_is_unavailable_not_zero(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A day the store does not cover is unavailable; the others are available."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=2), skip=(4,)))

    await setup_entry(hass)

    assert hass.states.get("sensor.cinema_test_in_4_days").state == "unavailable"
    assert hass.states.get("sensor.cinema_test_in_3_days").state == "2"
    assert hass.states.get("sensor.cinema_test_in_5_days").state == "2"


async def test_age_expiry_after_a_restore(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Data fetched 40 hours ago is shown while the source is down, and withdrawn after 48 hours, with no request."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=40)))
    FakeProvider.error = SourceConnectionError("down")

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(TODAY_ID).state == "2"
    assert len(FakeProvider.calls) == 1

    await move_to(hass, freezer, "2026-11-12T17:59:00+01:00")  # the 30-minute retries keep failing
    assert hass.states.get(TODAY_ID).state == "1"
    await move_to(hass, freezer, "2026-11-12T18:01:00+01:00")
    assert hass.states.get(TODAY_ID).state == "unavailable"


async def test_age_expiry_happens_at_the_limit(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """The data is still shown one second before 48 hours, and withdrawn at exactly 48 hours (the timer is armed there)."""
    freezer.move_to("2026-11-12T17:00:00+01:00")
    prefill(hass_storage, stored_data(last_refresh=datetime(2026, 11, 10, 17, 0, tzinfo=UTC)))
    FakeProvider.error = SourceConnectionError("down")
    await setup_entry(hass)

    await move_to(hass, freezer, "2026-11-12T17:59:59+01:00")
    assert hass.states.get(TODAY_ID).state != "unavailable"

    await move_to(hass, freezer, "2026-11-12T18:00:00+01:00")  # exactly fetched_at + 48 h: no longer allowed

    assert hass.states.get(TODAY_ID).state == "unavailable"


async def test_midnight_after_a_restore(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """The midnight rollover works from restored data, with no request."""
    freezer.move_to("2026-11-12T23:00:00+01:00")
    prefill(hass_storage, stored_data(last_refresh=at(TODAY, 21).astimezone(UTC)))
    await setup_entry(hass)
    assert hass.states.get(TODAY_ID).attributes["date"] == "2026-11-12"

    await move_to(hass, freezer, "2026-11-13T00:00:00+01:00")

    state = hass.states.get(TODAY_ID)
    assert state.attributes["date"] == "2026-11-13"
    assert state.state == "2"
    assert hass.states.get("sensor.cinema_test_in_6_days").attributes["date"] == "2026-11-19"
    assert not FakeProvider.calls


async def test_clock_skew_forces_a_refresh(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A stored fetch time in the future is not trusted: the setup refreshes."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=NOW_UTC + timedelta(hours=3)))
    program_week()

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert len(FakeProvider.calls) == 8
    assert entry.runtime_data.last_refresh == NOW_UTC


async def test_past_days_are_dropped_at_restore(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Days before today are not restored; the others are shown, with no request."""
    freezer.move_to(NOW)
    prefill(hass_storage, stored_data(last_refresh=_ago(hours=2), start=TODAY - timedelta(days=2)))

    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert sorted(entry.runtime_data.data) == [TODAY + timedelta(days=i) for i in range(6)]
    assert not FakeProvider.calls
    assert hass.states.get(TODAY_ID).state == "2"

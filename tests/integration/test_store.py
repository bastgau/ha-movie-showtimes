"""The persistence layer, below the coordinator."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.store import (
    CachedDay,
    ShowtimesStore,
    StoredSnapshot,
    snapshot_from_dict,
    snapshot_to_dict,
)
from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.fake_provider import FakeProvider

from .helpers import ENTRY_ID, STORE_KEY, TODAY, prefill, standard_day, stored_data

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def _snapshot(*offsets: int) -> StoredSnapshot:
    """Build a snapshot with the standard day at each offset from today."""
    days = {
        TODAY + timedelta(days=offset): CachedDay(
            showtimes=standard_day(TODAY + timedelta(days=offset)), fetched_at=NOW
        )
        for offset in offsets
    }
    return StoredSnapshot(last_refresh=NOW, days=days)


def test_round_trip(freezer: FrozenDateTimeFactory) -> None:
    """A snapshot survives serialisation, with its Paris zone."""
    freezer.move_to("2026-11-12T10:00:00+01:00")
    snapshot = _snapshot(0, 1, 2)

    data = snapshot_to_dict("fake", "C1", snapshot)
    restored = snapshot_from_dict(data, source_id="fake", cinema_id="C1", source_tz=PARIS)

    assert restored == snapshot
    assert data == stored_data(last_refresh=NOW, count=3)
    assert restored.days[TODAY].showtimes.films[0].showtimes[0].starts_at.tzinfo == PARIS


def test_only_days_from_today_are_written(freezer: FrozenDateTimeFactory) -> None:
    """Days in the past are left out of the store."""
    freezer.move_to("2026-11-12T10:00:00+01:00")
    snapshot = _snapshot(-2, -1, 0, 1)

    data = snapshot_to_dict("fake", "C1", snapshot)

    assert [day["date"] for day in data["days"]] == ["2026-11-12", "2026-11-13"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("days"),
        lambda d: d.update(days=[{"date": "nope"}]),
        lambda d: d.update(last_refresh="2026-11-12T09:00:00"),
        lambda d: d.update(source="other"),
        lambda d: d.update(cinema_id="Z"),
        lambda d: d["days"][0]["films"][0].update(showtimes=[]),
        lambda d: d["days"][0]["films"][0].update(title=3),
        lambda d: d["days"][0]["films"][0]["showtimes"][0].update(version="x"),
    ],
)
def test_invalid_data_is_rejected(mutate: Any) -> None:
    """Each broken invariant raises ``ValueError``."""
    data = stored_data(last_refresh=NOW, count=2)
    mutate(data)

    with pytest.raises(ValueError):  # noqa: PT011
        snapshot_from_dict(data, source_id="fake", cinema_id="C1", source_tz=PARIS)


async def test_load_ignores_a_read_error(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A file that cannot be read is nothing stored."""
    store = ShowtimesStore(hass, ENTRY_ID)

    with patch.object(ShowtimesStore, "async_load", AsyncMock(side_effect=OSError("disk"))):
        assert await store.async_load_snapshot(FakeProvider.source, "C1") is None

    assert "Ignoring the stored showtimes of C1" in caplog.text


async def test_load_ignores_an_unknown_time_zone(
    hass: HomeAssistant, hass_storage: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A source zone that cannot be resolved is nothing stored."""
    prefill(hass_storage, stored_data(last_refresh=NOW))
    store = ShowtimesStore(hass, ENTRY_ID)

    with patch.object(dt_util, "async_get_time_zone", AsyncMock(return_value=None)):
        assert await store.async_load_snapshot(FakeProvider.source, "C1") is None

    assert "unknown time zone" in caplog.text


async def test_load_and_save(hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory) -> None:
    """A saved snapshot is loaded back; a missing file loads nothing, silently."""
    freezer.move_to("2026-11-12T10:00:00+01:00")
    store = ShowtimesStore(hass, ENTRY_ID)
    assert await store.async_load_snapshot(FakeProvider.source, "C1") is None

    await store.async_save_snapshot(FakeProvider.source, "C1", _snapshot(0, 1))

    assert hass_storage[STORE_KEY]["data"]["cinema_id"] == "C1"
    assert await store.async_load_snapshot(FakeProvider.source, "C1") == _snapshot(0, 1)

"""Helpers shared by the Home Assistant tests."""

from datetime import date, datetime, timedelta
from typing import Any

from custom_components.movie_showtimes.client import DayShowtimes, ShowtimeVersion
from custom_components.movie_showtimes.const import DOMAIN
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.core import HomeAssistant
from tests.fake_provider import FakeProvider, make_day, make_film, paris

ENTRY_ID = "entryc1"
STORE_KEY = f"{DOMAIN}.{ENTRY_ID}"
TODAY = date(2026, 11, 12)
"""A Thursday in winter time."""
TITLE = "Cinema Test"
TODAY_ID = "sensor.cinema_test_today"
TOMORROW_ID = "sensor.cinema_test_tomorrow"


def at(day: date, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Return an aware Europe/Paris datetime."""
    return paris(day.year, day.month, day.day, hour, minute).replace(second=second)


def standard_day(day: date, cinema_id: str = "C1") -> DayShowtimes:
    """Return a day with Film A at 14:00 (dubbed) and 20:00 (local) and Film B at 14:00 (original)."""
    return make_day(
        cinema_id,
        day,
        make_film("Film A", (at(day, 14), ShowtimeVersion.DUBBED), (at(day, 20), ShowtimeVersion.LOCAL)),
        make_film("Film B", (at(day, 14), ShowtimeVersion.ORIGINAL)),
    )


def program_week(start: date = TODAY, count: int = 8) -> None:
    """Make the fake return the standard day for ``count`` days from ``start``."""
    for offset in range(count):
        day = start + timedelta(days=offset)
        FakeProvider.days[day] = standard_day(day)


def make_entry(**kwargs: Any) -> MockConfigEntry:
    """Build the entry of cinema ``C1`` of the fake source."""
    arguments: dict[str, Any] = {
        "domain": DOMAIN,
        "data": {"source": "fake", "cinema_id": "C1"},
        "unique_id": "fake_C1",
        "title": TITLE,
        "entry_id": ENTRY_ID,
    }
    arguments.update(kwargs)
    return MockConfigEntry(**arguments)


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry | None = None) -> MockConfigEntry:
    """Add the entry to Home Assistant and set it up."""
    entry = entry or make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def move_to(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str | datetime) -> None:
    """Move the clock to ``when``, fire the timers due, and let Home Assistant settle."""
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta) -> None:
    """Advance the clock by ``delta``, fire the timers due, and let Home Assistant settle."""
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def stored_data(  # pylint: disable=too-many-arguments
    *,
    last_refresh: datetime,
    start: date = TODAY,
    count: int = 8,
    skip: tuple[int, ...] = (),
    fetched_at: datetime | None = None,
    source: str = "fake",
    cinema_id: str = "C1",
) -> dict[str, Any]:
    """Build the content of a store in the version-1 format."""
    fetched = (fetched_at or last_refresh).isoformat()
    days: list[dict[str, Any]] = []
    for offset in range(count):
        if offset in skip:
            continue
        day = start + timedelta(days=offset)
        days.append(
            {
                "date": day.isoformat(),
                "fetched_at": fetched,
                "films": [
                    {
                        "title": film.title,
                        "showtimes": [
                            {"starts_at": showtime.starts_at.isoformat(), "version": showtime.version.value}
                            for showtime in film.showtimes
                        ],
                    }
                    for film in standard_day(day).films
                ],
            }
        )
    return {
        "source": source,
        "cinema_id": cinema_id,
        "last_refresh": last_refresh.isoformat(),
        "films": {},
        "days": days,
    }


def prefill(hass_storage: dict[str, Any], data: dict[str, Any], *, version: int = 1, minor_version: int = 1) -> None:
    """Put a store in the fake storage of the test."""
    hass_storage[STORE_KEY] = {"version": version, "minor_version": minor_version, "key": STORE_KEY, "data": data}

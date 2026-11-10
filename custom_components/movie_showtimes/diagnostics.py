"""Diagnostics of the Movie Showtimes integration."""

from typing import Any, Final, cast

from homeassistant.components.diagnostics import async_redact_data  # pyright: ignore[reportUnknownVariableType]
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .coordinator import MovieShowtimesConfigEntry
from .store import CachedDay

# Nothing is secret today (no credentials; the cinema id and name are public): the one place to add a field.
TO_REDACT: Final[set[str]] = set()


def _day_diagnostics(cached: CachedDay) -> dict[str, Any]:
    """Return one fetched day, unfiltered.

    Args:
        cached (CachedDay): The day and when it was fetched.

    Returns:
        dict[str, Any]: The fetch time, the film count and every film with all its showtimes.

    """
    day = cached.showtimes
    return {
        "fetched_at": cached.fetched_at.isoformat(),
        "film_count": len(day.films),
        "films": [
            {
                "title": film.title,
                "showtimes": [
                    {"starts_at": showtime.starts_at.isoformat(), "version": showtime.version.value}
                    for showtime in film.showtimes
                ],
            }
            for film in day.films
        ],
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: MovieShowtimesConfigEntry,
) -> dict[str, Any]:
    """Return the diagnostics of a cinema entry.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (MovieShowtimesConfigEntry): The entry of the cinema.

    Returns:
        dict[str, Any]: The entry, the source, the coordinator's status and every fetched day.

    """
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    source = coordinator.provider.source
    last_refresh = coordinator.last_refresh
    diagnostics: dict[str, Any] = {
        "entry": {"title": entry.title, "data": dict(entry.data), "unique_id": entry.unique_id},
        "source": {"id": source.id, "name": source.name, "time_zone": source.time_zone},
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception) if coordinator.last_exception is not None else None,
            "update_interval": str(coordinator.update_interval),
            "last_refresh": last_refresh.isoformat() if last_refresh is not None else None,
            "restored_from_store": coordinator.restored_from_store,
            "data_age_seconds": (dt_util.utcnow() - last_refresh).total_seconds() if last_refresh is not None else None,
        },
        "days": {day.isoformat(): _day_diagnostics(data[day]) for day in sorted(data)},
    }
    return cast("dict[str, Any]", async_redact_data(diagnostics, TO_REDACT))

"""Persistence of the last good showtimes of a cinema, so that a restart costs no request."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
import logging
from typing import Any, override

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import DayShowtimes, Film, Showtime, ShowtimeVersion, SourceInfo
from .const import DOMAIN, STORAGE_MINOR_VERSION, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class CachedDay:
    """One day as held in memory and in the store.

    Attributes:
        showtimes (DayShowtimes): The day's films.
        fetched_at (datetime): When the day was last fetched successfully, aware UTC.

    """

    showtimes: DayShowtimes
    fetched_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredSnapshot:
    """The data of the last successful refresh.

    Attributes:
        last_refresh (datetime): The end of that refresh, aware UTC.
        days (dict[date, CachedDay]): The cached days, keyed by date.

    """

    last_refresh: datetime
    days: dict[date, CachedDay]


def snapshot_to_dict(source_id: str, cinema_id: str, snapshot: StoredSnapshot) -> dict[str, Any]:
    """Serialise a snapshot to the store's JSON format, version 1.

    Only the days from today (Home Assistant's time zone) on are written.

    Args:
        source_id (str): The provider id.
        cinema_id (str): The canonical cinema id.
        snapshot (StoredSnapshot): The snapshot.

    Returns:
        dict[str, Any]: A JSON-compatible dict.

    """
    today = dt_util.now().date()
    return {
        "source": source_id,
        "cinema_id": cinema_id,
        "last_refresh": snapshot.last_refresh.isoformat(),
        "days": [
            {
                "date": day.isoformat(),
                "fetched_at": cached.fetched_at.isoformat(),
                "films": [
                    {
                        "title": film.title,
                        "showtimes": [
                            {"starts_at": showtime.starts_at.isoformat(), "version": showtime.version.value}
                            for showtime in film.showtimes
                        ],
                    }
                    for film in cached.showtimes.films
                ],
            }
            for day, cached in sorted(snapshot.days.items())
            if day >= today
        ],
    }


def _aware(value: str) -> datetime:
    """Parse an ISO datetime that must carry an offset.

    Args:
        value (str): The ISO datetime.

    Returns:
        datetime: The aware datetime.

    Raises:
        ValueError: The value is not an ISO datetime, or is naive.

    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        msg = f"Naive datetime in the store: {value!r}"
        raise ValueError(msg)
    return parsed


def _film_from_dict(raw: Mapping[str, Any], source_tz: tzinfo) -> Film:
    """Rebuild a film.

    Args:
        raw (Mapping[str, Any]): The stored film.
        source_tz (tzinfo): The source's time zone.

    Returns:
        Film: The film.

    Raises:
        ValueError: The film is empty or has an empty title.

    """
    title = raw["title"]
    if not isinstance(title, str) or not title.strip():
        msg = "A stored film has no title"
        raise ValueError(msg)
    showtimes = tuple(
        Showtime(
            starts_at=_aware(entry["starts_at"]).astimezone(source_tz),
            version=ShowtimeVersion(entry["version"]),
        )
        for entry in raw["showtimes"]
    )
    if not showtimes:
        msg = f"The stored film {title!r} has no showtimes"
        raise ValueError(msg)
    return Film(title=title, showtimes=showtimes)


def snapshot_from_dict(raw: Mapping[str, Any], *, source_id: str, cinema_id: str, source_tz: tzinfo) -> StoredSnapshot:
    """Rebuild a snapshot from the store's JSON, strictly.

    Args:
        raw (Mapping[str, Any]): The stored data.
        source_id (str): The entry's provider id; the stored one must match.
        cinema_id (str): The entry's canonical cinema id; the stored one must match.
        source_tz (tzinfo): The source's time zone, restored on every ``starts_at``.

    Returns:
        StoredSnapshot: The snapshot.

    Raises:
        ValueError: A key is missing, a type or value is wrong, or an invariant is broken.

    """
    try:
        if raw["source"] != source_id or raw["cinema_id"] != cinema_id:
            msg = "The stored data belongs to another source or cinema"
            raise ValueError(msg)
        days: dict[date, CachedDay] = {}
        for entry in raw["days"]:
            day = date.fromisoformat(entry["date"])
            films = tuple(_film_from_dict(film, source_tz) for film in entry["films"])
            days[day] = CachedDay(
                showtimes=DayShowtimes(cinema_id=cinema_id, day=day, films=films),
                fetched_at=_aware(entry["fetched_at"]).astimezone(UTC),
            )
        return StoredSnapshot(last_refresh=_aware(raw["last_refresh"]).astimezone(UTC), days=days)
    except (KeyError, TypeError) as err:
        msg = f"Malformed stored data: {err!r}"
        raise ValueError(msg) from err


class ShowtimesStore(Store[dict[str, Any]]):
    """The store of one config entry: ``.storage/movie_showtimes.<entry_id>``."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create the store.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            entry_id (str): The config entry id.

        """
        super().__init__(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            minor_version=STORAGE_MINOR_VERSION,
            atomic_writes=True,
        )

    @override
    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Migrate the stored data: a cache, so an older major is simply dropped.

        Args:
            old_major_version (int): The stored major version.
            old_minor_version (int): The stored minor version.
            old_data (dict[str, Any]): The stored data.

        Returns:
            dict[str, Any]: The data unchanged for an older minor, otherwise ``{}``.

        """
        if old_major_version == STORAGE_VERSION and old_minor_version < STORAGE_MINOR_VERSION:
            return old_data
        return {}

    async def async_load_snapshot(self, source: SourceInfo, cinema_id: str) -> StoredSnapshot | None:
        """Load the stored snapshot, or ``None`` if there is nothing valid for this cinema.

        Args:
            source (SourceInfo): The entry's source.
            cinema_id (str): The entry's canonical cinema id.

        Returns:
            StoredSnapshot | None: The snapshot, or ``None`` (a warning is logged unless there is no file).

        """
        try:
            raw = await self.async_load()
        except (HomeAssistantError, OSError) as err:
            _LOGGER.warning("Ignoring the stored showtimes of %s: %s", cinema_id, err)
            return None
        if not raw:
            return None

        source_tz = await dt_util.async_get_time_zone(source.time_zone)
        if source_tz is None:
            _LOGGER.warning("Ignoring the stored showtimes of %s: unknown time zone %s", cinema_id, source.time_zone)
            return None
        try:
            return snapshot_from_dict(raw, source_id=source.id, cinema_id=cinema_id, source_tz=source_tz)
        except ValueError as err:
            _LOGGER.warning("Ignoring the stored showtimes of %s: %s", cinema_id, err)
            return None

    async def async_save_snapshot(self, source: SourceInfo, cinema_id: str, snapshot: StoredSnapshot) -> None:
        """Write the snapshot. Store logs write errors itself, so this never fails a refresh.

        Args:
            source (SourceInfo): The entry's source.
            cinema_id (str): The entry's canonical cinema id.
            snapshot (StoredSnapshot): The snapshot to write.

        """
        await self.async_save(snapshot_to_dict(source.id, cinema_id, snapshot))

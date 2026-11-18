"""Persistence of the last good showtimes of a cinema, so that a restart costs no request."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime, tzinfo
import logging
from typing import Any, Final, cast, override

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import (
    Credit,
    DayShowtimes,
    Film,
    FilmDetails,
    Rating,
    Showtime,
    ShowtimeFormats,
    ShowtimeVersion,
    SourceInfo,
)
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


_STR_FIELDS: Final = frozenset(
    {
        "url",
        "film_type",
        "original_title",
        "release_date",
        "visa_number",
        "certificate",
        "poster_url",
        "synopsis",
        "synopsis_full",
    }
)
_INT_FIELDS: Final = frozenset({"year", "runtime", "user_review_count", "want_to_see_count", "hits", "sessions"})
_BOOL_FIELDS: Final = frozenset({"premiere", "weekly_outing", "has_trailer"})
_TEXTS_FIELDS: Final = frozenset({"genres", "countries", "languages", "directors", "cast", "related_tags", "flags"})
_RATING_FIELDS: Final = frozenset({"user_rating", "press_rating"})
_SHOWTIME_FLAGS: Final = (
    "subtitled",
    "hard_of_hearing_subtitles",
    "disabled_access",
    "audio_description",
    "preview",
    "weekly_outing",
)
_FORMAT_FIELDS: Final = tuple(item.name for item in fields(ShowtimeFormats))


def _put(target: dict[str, Any], key: str, value: object) -> None:
    """Set ``key`` unless ``value`` is ``None`` or an empty tuple (``False`` is written).

    Args:
        target (dict[str, Any]): The JSON object being built.
        key (str): The key.
        value (object): The value; a tuple is written as a list.

    """
    if value is None or value == ():
        return
    target[key] = list(cast("tuple[Any, ...]", value)) if isinstance(value, tuple) else value


def _details_to_dict(details: FilmDetails) -> dict[str, Any]:
    """Serialise a film's details: the model's field names, ``None`` and empty tuples omitted.

    Args:
        details (FilmDetails): The details.

    Returns:
        dict[str, Any]: A JSON-compatible dict.

    """
    result: dict[str, Any] = {}
    for item in fields(FilmDetails):
        value = getattr(details, item.name)
        if isinstance(value, Rating):
            rating: dict[str, Any] = {"score": value.score}
            _put(rating, "count", value.count)
            result[item.name] = rating
        elif item.name == "credits":
            _put(result, item.name, tuple({"name": credit.name, "role": credit.role} for credit in value))
        else:
            _put(result, item.name, value)
    return result


def _showtime_to_dict(showtime: Showtime) -> dict[str, Any]:
    """Serialise a showtime, omitting the unknown optional fields.

    Args:
        showtime (Showtime): The showtime.

    Returns:
        dict[str, Any]: A JSON-compatible dict.

    """
    result: dict[str, Any] = {"starts_at": showtime.starts_at.isoformat(), "version": showtime.version.value}
    for name in _SHOWTIME_FLAGS:
        _put(result, name, getattr(showtime, name))
    if showtime.formats is not None:
        formats: dict[str, Any] = {}
        for name in _FORMAT_FIELDS:
            _put(formats, name, getattr(showtime.formats, name))
        result["formats"] = formats
    _put(result, "ticket_url", showtime.ticket_url)
    return result


def _film_to_dict(film: Film) -> dict[str, Any]:
    """Serialise a film of a day: its details go to the catalogue when it has a ``ref``, inline otherwise.

    Args:
        film (Film): The film.

    Returns:
        dict[str, Any]: A JSON-compatible dict.

    """
    result: dict[str, Any] = {"title": film.title}
    if film.ref is not None:
        result["ref"] = film.ref
    elif film.details is not None:
        result["details"] = _details_to_dict(film.details)
    result["showtimes"] = [_showtime_to_dict(showtime) for showtime in film.showtimes]
    return result


def film_catalogue(days: Mapping[date, CachedDay]) -> dict[str, FilmDetails]:
    """Return the details of every film with a ``ref`` in ``days``: the film catalogue, rebuilt from scratch.

    For each ``ref``, the details come from the day fetched last (tie: the earliest date); films without details are
    skipped. Nothing else is in it, so it cannot outgrow the days.

    Args:
        days (Mapping[date, CachedDay]): The days.

    Returns:
        dict[str, FilmDetails]: The details, keyed by ``ref``, in the order the films first appear by date.

    """
    order = {day: index for index, day in enumerate(sorted(days))}
    chosen: dict[str, tuple[datetime, int, FilmDetails]] = {}
    for day in sorted(days):
        cached = days[day]
        for film in cached.showtimes.films:
            if film.ref is None or film.details is None:
                continue
            rank = (cached.fetched_at, -order[day])
            current = chosen.get(film.ref)
            if current is None or rank > current[:2]:
                chosen[film.ref] = (*rank, film.details)
    return {ref: details for ref, (_, _, details) in chosen.items()}


def unify_film_details(days: Mapping[date, CachedDay]) -> tuple[dict[date, CachedDay], dict[str, FilmDetails]]:
    """Make every film with the same ``ref`` carry the same details: those of the day fetched last.

    A day is rebuilt only when one of its films changes, so unchanged days keep their identity.

    Args:
        days (Mapping[date, CachedDay]): The days.

    Returns:
        tuple[dict[date, CachedDay], dict[str, FilmDetails]]: The unified days and the film catalogue.

    """
    catalogue = film_catalogue(days)
    unified: dict[date, CachedDay] = {}
    for day, cached in days.items():
        films = tuple(
            replace(film, details=catalogue[film.ref])
            if film.ref is not None and film.ref in catalogue and film.details is not catalogue[film.ref]
            else film
            for film in cached.showtimes.films
        )
        if all(new is old for new, old in zip(films, cached.showtimes.films, strict=True)):
            unified[day] = cached
        else:
            unified[day] = replace(cached, showtimes=replace(cached.showtimes, films=films))
    return unified, catalogue


def snapshot_to_dict(source_id: str, cinema_id: str, snapshot: StoredSnapshot) -> dict[str, Any]:
    """Serialise a snapshot to the store's JSON format, version 1.

    Only the days from today (Home Assistant's time zone) on are written, and the ``films`` catalogue holds only the
    films of those days: whatever left them is purged at the same save.

    Args:
        source_id (str): The provider id.
        cinema_id (str): The canonical cinema id.
        snapshot (StoredSnapshot): The snapshot.

    Returns:
        dict[str, Any]: A JSON-compatible dict.

    """
    today = dt_util.now().date()
    kept = {day: cached for day, cached in snapshot.days.items() if day >= today}
    return {
        "source": source_id,
        "cinema_id": cinema_id,
        "last_refresh": snapshot.last_refresh.isoformat(),
        "films": {ref: _details_to_dict(details) for ref, details in film_catalogue(kept).items()},
        "days": [
            {
                "date": day.isoformat(),
                "fetched_at": cached.fetched_at.isoformat(),
                "films": [_film_to_dict(film) for film in cached.showtimes.films],
            }
            for day, cached in sorted(kept.items())
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


class MalformedStoreError(ValueError):
    """A stored value has the wrong type: the whole snapshot is rejected."""


def _malformed(what: str, value: object) -> str:
    """Build the message of a stored value of the wrong type.

    Args:
        what (str): What the value is.
        value (object): The value.

    Returns:
        str: The message.

    """
    return f"Malformed stored {what}: {value!r}"


def _optional_str(raw: Mapping[str, Any], key: str) -> str | None:
    """Read an optional string.

    Args:
        raw (Mapping[str, Any]): The stored object.
        key (str): The key.

    Returns:
        str | None: The value, or ``None`` when absent.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        raise MalformedStoreError(_malformed(key, value))
    return value


def _optional_int(raw: Mapping[str, Any], key: str) -> int | None:
    """Read an optional integer (not a ``bool``).

    Args:
        raw (Mapping[str, Any]): The stored object.
        key (str): The key.

    Returns:
        int | None: The value, or ``None`` when absent.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    value = raw.get(key)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise MalformedStoreError(_malformed(key, value))
    return value


def _optional_bool(raw: Mapping[str, Any], key: str) -> bool | None:
    """Read an optional boolean.

    Args:
        raw (Mapping[str, Any]): The stored object.
        key (str): The key.

    Returns:
        bool | None: The value, or ``None`` when absent.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    value = raw.get(key)
    if value is not None and not isinstance(value, bool):
        raise MalformedStoreError(_malformed(key, value))
    return value


def _texts(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    """Read an optional list of strings.

    Args:
        raw (Mapping[str, Any]): The stored object.
        key (str): The key.

    Returns:
        tuple[str, ...]: The strings, ``()`` when absent.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    value: object = raw.get(key, [])
    items: list[object] | None = cast("list[object]", value) if isinstance(value, list) else None
    if items is None or not all(isinstance(item, str) for item in items):
        raise MalformedStoreError(_malformed(key, cast("object", value)))
    return tuple(cast("list[str]", items))


def _rating(raw: Mapping[str, Any], key: str) -> Rating | None:
    """Read an optional ``{score, count}`` rating.

    Args:
        raw (Mapping[str, Any]): The stored object.
        key (str): The key.

    Returns:
        Rating | None: The rating, or ``None`` when absent.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    value: object = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise MalformedStoreError(_malformed(key, value))
    rating = cast("dict[str, Any]", value)
    score = rating.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise MalformedStoreError(_malformed(f"{key}.score", score))
    return Rating(score=float(score), count=_optional_int(rating, "count"))


def _credits(raw: Mapping[str, Any]) -> tuple[Credit, ...]:
    """Read the optional list of credits.

    Args:
        raw (Mapping[str, Any]): The stored details.

    Returns:
        tuple[Credit, ...]: The credits, ``()`` when absent.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    value: object = raw.get("credits", [])
    if not isinstance(value, list):
        raise MalformedStoreError(_malformed("credits", value))
    result: list[Credit] = []
    item: object
    for item in cast("list[object]", value):
        entry = cast("dict[str, Any]", item) if isinstance(item, dict) else None
        name, role = (entry.get("name"), entry.get("role")) if entry is not None else (None, None)
        if not isinstance(name, str) or not isinstance(role, str):
            raise MalformedStoreError(_malformed("credit", cast("object", item)))
        result.append(Credit(name=name, role=role))
    return tuple(result)


def _details_from_dict(raw: object) -> FilmDetails:
    """Rebuild a film's details, strictly.

    Args:
        raw (object): The stored details.

    Returns:
        FilmDetails: The details.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    if not isinstance(raw, dict):
        raise MalformedStoreError(_malformed("film details", raw))
    stored = cast("dict[str, Any]", raw)
    values: dict[str, Any] = {}
    for name in _STR_FIELDS:
        values[name] = _optional_str(stored, name)
    for name in _INT_FIELDS:
        values[name] = _optional_int(stored, name)
    for name in _BOOL_FIELDS:
        values[name] = _optional_bool(stored, name)
    for name in _TEXTS_FIELDS:
        values[name] = _texts(stored, name)
    for name in _RATING_FIELDS:
        values[name] = _rating(stored, name)
    values["credits"] = _credits(stored)
    return FilmDetails(**values)


def _formats_from_dict(raw: object) -> ShowtimeFormats | None:
    """Rebuild a showtime's formats, strictly.

    Args:
        raw (object): The stored formats, or ``None``.

    Returns:
        ShowtimeFormats | None: The formats, or ``None`` when absent or all empty.

    Raises:
        MalformedStoreError: Present but of the wrong type.

    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise MalformedStoreError(_malformed("formats", raw))
    stored = cast("dict[str, Any]", raw)
    formats = ShowtimeFormats(**{name: _texts(stored, name) for name in _FORMAT_FIELDS})
    return None if formats == ShowtimeFormats() else formats


def _showtime_from_dict(raw: Mapping[str, Any], source_tz: tzinfo) -> Showtime:
    """Rebuild a showtime; the optional keys default to unknown.

    Args:
        raw (Mapping[str, Any]): The stored showtime.
        source_tz (tzinfo): The source's time zone.

    Returns:
        Showtime: The showtime.

    """
    return Showtime(
        starts_at=_aware(raw["starts_at"]).astimezone(source_tz),
        version=ShowtimeVersion(raw["version"]),
        formats=_formats_from_dict(raw.get("formats")),
        ticket_url=_optional_str(raw, "ticket_url"),
        **{name: _optional_bool(raw, name) for name in _SHOWTIME_FLAGS},
    )


def _film_from_dict(raw: Mapping[str, Any], source_tz: tzinfo, catalogue: Mapping[str, FilmDetails]) -> Film:
    """Rebuild a film; a film with a ``ref`` takes its details from the catalogue.

    Args:
        raw (Mapping[str, Any]): The stored film.
        source_tz (tzinfo): The source's time zone.
        catalogue (Mapping[str, FilmDetails]): The stored film details, keyed by ``ref``.

    Returns:
        Film: The film.

    Raises:
        ValueError: The film is empty or has an empty title.
        MalformedStoreError: A malformed ``ref`` or value.

    """
    title = raw["title"]
    if not isinstance(title, str) or not title.strip():
        msg = "A stored film has no title"
        raise ValueError(msg)
    showtimes = tuple(_showtime_from_dict(entry, source_tz) for entry in raw["showtimes"])
    if not showtimes:
        msg = f"The stored film {title!r} has no showtimes"
        raise ValueError(msg)

    ref = raw.get("ref")
    if ref is None:
        details = _details_from_dict(raw["details"]) if "details" in raw else None
        return Film(title=title, showtimes=showtimes, details=details)
    if not isinstance(ref, str) or not ref:
        raise MalformedStoreError(_malformed("film ref", ref))
    details = catalogue.get(ref)
    if details is None:
        _LOGGER.debug("The stored film %r (%s) has no details in the catalogue", title, ref)
    return Film(title=title, showtimes=showtimes, ref=ref, details=details)


def snapshot_from_dict(raw: Mapping[str, Any], *, source_id: str, cinema_id: str, source_tz: tzinfo) -> StoredSnapshot:
    """Rebuild a snapshot from the store's JSON, strictly.

    The ``films`` catalogue is required. A film whose ``ref`` is not in it loads without details; a catalogue entry no
    film refers to is ignored. Films with the same ``ref`` share one details object.

    Args:
        raw (Mapping[str, Any]): The stored data.
        source_id (str): The entry's provider id; the stored one must match.
        cinema_id (str): The entry's canonical cinema id; the stored one must match.
        source_tz (tzinfo): The source's time zone, restored on every ``starts_at``.

    Returns:
        StoredSnapshot: The snapshot.

    Raises:
        ValueError: A key is missing, a type or value is wrong, or an invariant is broken.
        MalformedStoreError: A value of the wrong type (a ``ValueError`` too).

    """
    try:
        if raw["source"] != source_id or raw["cinema_id"] != cinema_id:
            msg = "The stored data belongs to another source or cinema"
            raise ValueError(msg)
        stored_films = raw["films"]
        if not isinstance(stored_films, dict):
            raise MalformedStoreError(_malformed("film catalogue", stored_films))
        catalogue = {str(ref): _details_from_dict(entry) for ref, entry in cast("dict[str, Any]", stored_films).items()}
        days: dict[date, CachedDay] = {}
        referenced: set[str] = set()
        for entry in raw["days"]:
            day = date.fromisoformat(entry["date"])
            films = tuple(_film_from_dict(film, source_tz, catalogue) for film in entry["films"])
            referenced.update(film.ref for film in films if film.ref is not None)
            days[day] = CachedDay(
                showtimes=DayShowtimes(cinema_id=cinema_id, day=day, films=films),
                fetched_at=_aware(entry["fetched_at"]).astimezone(UTC),
            )
        if unreferenced := catalogue.keys() - referenced:
            _LOGGER.debug("Ignoring %d stored film detail(s) no film refers to", len(unreferenced))
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

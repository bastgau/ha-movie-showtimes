"""Sensor platform of the Movie Showtimes integration: one sensor per day, from today to today + 6."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, override

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ATTR_DATE, ATTR_FETCHED_AT, ATTR_FILMS, DAYS_EXPOSED
from .coordinator import MovieShowtimesConfigEntry, MovieShowtimesCoordinator
from .entity import MovieShowtimesEntity
from .showtimes import film_attributes, is_day_usable, remaining_films

# The coordinator does all the fetching: entities never make a request.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MovieShowtimesSensorEntityDescription(SensorEntityDescription):
    """Describe a day sensor.

    Attributes:
        offset (int): Days from today: 0 for today, 1 for tomorrow, and so on.

    """

    offset: int


def _translation_key(offset: int) -> str:
    """Return the translation key of the sensor for a day offset.

    Args:
        offset (int): Days from today.

    Returns:
        str: ``today``, ``tomorrow``, then ``day_<offset>``.

    """
    if offset == 0:
        return "today"
    if offset == 1:
        return "tomorrow"
    return f"day_{offset}"


SENSOR_DESCRIPTIONS: tuple[MovieShowtimesSensorEntityDescription, ...] = tuple(
    MovieShowtimesSensorEntityDescription(key=f"day_{offset}", translation_key=_translation_key(offset), offset=offset)
    for offset in range(DAYS_EXPOSED)
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: MovieShowtimesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the day sensors of a cinema.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (MovieShowtimesConfigEntry): The entry of the cinema.
        async_add_entities (AddConfigEntryEntitiesCallback): Adds the entities.

    """
    coordinator = entry.runtime_data
    async_add_entities(MovieShowtimesDaySensor(coordinator, description) for description in SENSOR_DESCRIPTIONS)


class MovieShowtimesDaySensor(MovieShowtimesEntity, SensorEntity):
    """The number of films still to come at the cinema on one day, with those films as attributes.

    Attributes:
        entity_description (MovieShowtimesSensorEntityDescription): The sensor's key, translation key and offset.
        _unrecorded_attributes (frozenset[str]): ``films`` is kept out of the recorder: it can be large.
        _attr_unique_id (str): ``<entry unique id>_day_<offset>``, tied to the offset, never to a date.
        _offset (int): Days from today of the sensor's date.
        _day_usable (bool): Whether the coordinator holds the sensor's current date, and young enough.

    """

    _unrecorded_attributes = frozenset({ATTR_FILMS})

    def __init__(
        self,
        coordinator: MovieShowtimesCoordinator,
        description: MovieShowtimesSensorEntityDescription,
    ) -> None:
        """Create the sensor and compute its first state.

        Args:
            coordinator (MovieShowtimesCoordinator): The coordinator of the cinema.
            description (MovieShowtimesSensorEntityDescription): The sensor's description.

        """
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{description.key}"
        self._offset = description.offset
        self._day_usable = False
        self._compute(dt_util.now())

    def _compute(self, now: datetime) -> None:
        """Compute availability, state and attributes together, from a single ``now``.

        Args:
            now (datetime): The current time, in Home Assistant's time zone.

        """
        sensor_date = now.date() + timedelta(days=self._offset)
        data = self.coordinator.data
        cached = data.get(sensor_date) if data else None
        self._day_usable = cached is not None and is_day_usable(cached, now)
        if cached is None or not self._day_usable:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        films = remaining_films(cached.showtimes, now)
        self._attr_native_value = len(films)
        attributes: dict[str, Any] = {
            ATTR_DATE: sensor_date.isoformat(),
            ATTR_FETCHED_AT: dt_util.as_local(cached.fetched_at).isoformat(),
            ATTR_FILMS: [film_attributes(film) for film in films],
        }
        self._attr_extra_state_attributes = attributes

    @property
    @override
    def available(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Whether the sensor's date is held and its data is not older than ``MAX_DATA_AGE``.

        Deliberately ignores ``last_update_success``: the data is a timetable keyed by date and filtered by the
        current time, so the last good copy stays right after a failed refresh or a restart.

        Returns:
            bool: ``False`` when the sensor's date was not fetched, or its data is too old.

        """
        return self._day_usable

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Recompute from the current time, then write the state."""
        self._compute(dt_util.now())
        super()._handle_coordinator_update()

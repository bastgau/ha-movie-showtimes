"""Base entity of the Movie Showtimes integration."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MovieShowtimesCoordinator


class MovieShowtimesEntity(CoordinatorEntity[MovieShowtimesCoordinator]):
    """An entity of the cinema's device, fed by its coordinator.

    Attributes:
        _attr_has_entity_name (bool): The entity name comes from its translation, prefixed by the device name.
        _attr_device_info (DeviceInfo): The cinema's service device.

    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: MovieShowtimesCoordinator) -> None:
        """Attach the entity to the cinema's device.

        Args:
            coordinator (MovieShowtimesCoordinator): The coordinator of the cinema.

        """
        super().__init__(coordinator)
        provider = coordinator.provider
        entry = coordinator.config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id))},
            name=entry.title,
            manufacturer=provider.source.name,
            entry_type=DeviceEntryType.SERVICE,
        )
        if (url := provider.cinema_url(coordinator.cinema_id)) is not None:
            self._attr_device_info["configuration_url"] = url

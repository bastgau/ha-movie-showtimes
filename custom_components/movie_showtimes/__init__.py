"""The Movie Showtimes integration: the showtimes of a cinema, as sensors."""

from typing import Final

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from .card import async_register_card
from .client import UnknownSourceError, create_provider
from .const import CONF_SOURCE, DOMAIN
from .coordinator import MovieShowtimesConfigEntry, MovieShowtimesCoordinator
from .store import ShowtimesStore

PLATFORMS: Final = [Platform.SENSOR]

# Home Assistant looks this name up; hassfest requires it next to ``async_setup``.
CONFIG_SCHEMA: Final = cv.config_entry_only_config_schema(DOMAIN)  # pylint: disable=invalid-name  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Serve the Lovelace card, once per Home Assistant run whatever the number of entries.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        config (ConfigType): The YAML configuration, unused: the integration is set up from the UI.

    Returns:
        bool: ``True`` always.

    """
    await async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MovieShowtimesConfigEntry) -> bool:
    """Set up a cinema: restore or refresh the data, midnight rollover, then the sensors.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (MovieShowtimesConfigEntry): The entry of the cinema.

    Returns:
        bool: ``True`` once set up.

    Raises:
        ConfigEntryError: The entry's source is not provided by this version.

    """
    source: str = entry.data[CONF_SOURCE]
    try:
        provider = create_provider(source, session=async_get_clientsession(hass))
    except UnknownSourceError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="unknown_source",
            translation_placeholders={"source": source},
        ) from err

    coordinator = MovieShowtimesCoordinator(hass, entry, provider, ShowtimesStore(hass, entry.entry_id))
    await coordinator.async_initialize()
    entry.runtime_data = coordinator

    entry.async_on_unload(async_track_time_change(hass, coordinator.async_handle_midnight, hour=0, minute=0, second=0))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MovieShowtimesConfigEntry) -> bool:
    """Unload a cinema.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (MovieShowtimesConfigEntry): The entry of the cinema.

    Returns:
        bool: Whether the platforms unloaded.

    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: MovieShowtimesConfigEntry) -> None:
    """Delete the entry's stored showtimes.

    Args:
        hass (HomeAssistant): The Home Assistant instance.
        entry (MovieShowtimesConfigEntry): The removed entry.

    """
    await ShowtimesStore(hass, entry.entry_id).async_remove()

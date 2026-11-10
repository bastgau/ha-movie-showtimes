"""Config flow of the Movie Showtimes integration: choose a source (if several), then a cinema."""

import logging
from typing import Any, Final, override

import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig  # pyright: ignore[reportUnknownVariableType]
from homeassistant.util import dt as dt_util

from .client import (
    PROVIDERS,
    CinemaNotFoundError,
    InvalidCinemaRefError,
    ShowtimesError,
    SourceAccessDeniedError,
    SourceConnectionError,
    create_provider,
)
from .const import CONF_CINEMA_ID, CONF_SOURCE, DOMAIN

_LOGGER = logging.getLogger(__name__)

_CINEMA_STEP: Final[dict[str, str]] = {}
"""Source id to the name of its first cinema step. A source whose reference does not fit one text field adds its
own steps here; the default is the generic ``cinema`` step."""

STEP_CINEMA_DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_CINEMA_ID): str,
        probatio.Optional(CONF_NAME, default=""): str,
    }
)


class MovieShowtimesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a cinema from its source: the source's reference (id or page URL) and a name.

    Attributes:
        _source (str): The chosen source id.

    """

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Start with the default source: the first registered one."""
        self._source: str = next(iter(PROVIDERS))

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the source; skipped when only one is registered.

        Args:
            user_input (dict[str, Any] | None): The submitted form, or ``None`` to show it.

        Returns:
            ConfigFlowResult: The source form, or the first cinema step of the source.

        """
        if user_input is None and len(PROVIDERS) > 1:
            return self.async_show_form(
                step_id="user",
                data_schema=probatio.Schema(
                    {
                        probatio.Required(CONF_SOURCE): SelectSelector(
                            SelectSelectorConfig(options=list(PROVIDERS), translation_key=CONF_SOURCE)
                        )
                    }
                ),
            )

        if user_input is not None:
            self._source = user_input[CONF_SOURCE]
        step: str = _CINEMA_STEP.get(self._source, "cinema")
        return await getattr(self, f"async_step_{step}")()

    async def async_step_cinema(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the cinema reference and an optional name, then check the cinema with its source.

        Args:
            user_input (dict[str, Any] | None): The submitted form, or ``None`` to show it.

        Returns:
            ConfigFlowResult: The form (again, with errors), an abort, or the created entry.

        """
        provider = create_provider(self._source, session=async_get_clientsession(self.hass))
        errors: dict[str, str] = {}
        if user_input is not None:
            cinema_id: str | None = None
            try:
                cinema_id = provider.normalize_cinema_ref(user_input[CONF_CINEMA_ID])
            except InvalidCinemaRefError:
                errors[CONF_CINEMA_ID] = "invalid_cinema_id"

            name = str(user_input.get(CONF_NAME, "")).strip()

            if cinema_id is not None and not errors:
                await self.async_set_unique_id(f"{self._source}_{cinema_id}")
                self._abort_if_unique_id_configured()

                try:
                    await provider.async_validate_cinema(cinema_id, dt_util.now().date())
                except CinemaNotFoundError:
                    errors[CONF_CINEMA_ID] = "invalid_cinema_id"
                except SourceAccessDeniedError as err:
                    _LOGGER.warning(
                        "%s refused the request for cinema %s (HTTP %s)",
                        provider.source.name,
                        cinema_id,
                        err.status_code,
                    )
                    errors["base"] = "access_denied"
                except SourceConnectionError as err:
                    _LOGGER.warning("Cannot connect to %s for cinema %s: %s", provider.source.name, cinema_id, err)
                    errors["base"] = "cannot_connect"
                except ShowtimesError:
                    _LOGGER.exception("Unexpected response from %s for cinema %s", provider.source.name, cinema_id)
                    errors["base"] = "unknown"
                else:
                    return self._async_finish(cinema_id, name or f"{provider.source.name} - {cinema_id}")

        return self.async_show_form(
            step_id="cinema",
            data_schema=self.add_suggested_values_to_schema(STEP_CINEMA_DATA_SCHEMA, user_input),
            errors=errors,
            description_placeholders={
                "source_name": provider.source.name,
                "ref_example": provider.source.ref_example,
                "url_example": provider.source.url_example,
            },
        )

    def _async_finish(self, cinema_id: str, name: str) -> ConfigFlowResult:
        """Create the entry. The unique id was set, and checked against the entries, before validation.

        Args:
            cinema_id (str): The canonical cinema id.
            name (str): The entry title.

        Returns:
            ConfigFlowResult: The created entry.

        """
        return self.async_create_entry(title=name, data={CONF_SOURCE: self._source, CONF_CINEMA_ID: cinema_id})

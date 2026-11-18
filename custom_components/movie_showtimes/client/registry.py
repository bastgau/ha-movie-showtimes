"""Static registry of the showtimes providers, keyed by source id."""

from typing import Final

import aiohttp

from .exceptions import UnknownSourceError
from .provider import ShowtimesProvider
from .providers.allocine import AllocineProvider

PROVIDERS: Final[dict[str, type[ShowtimesProvider]]] = {AllocineProvider.source.id: AllocineProvider}
"""The registered providers. Ordered: the first is the default, used when it is the only one."""


def get_provider_class(source_id: str) -> type[ShowtimesProvider]:
    """Return the provider class registered under a source id.

    Args:
        source_id (str): The source id, e.g. ``allocine``.

    Returns:
        type[ShowtimesProvider]: The provider class.

    Raises:
        UnknownSourceError: No provider is registered under this id.

    """
    try:
        return PROVIDERS[source_id]
    except KeyError as err:
        msg = f"No showtimes provider is registered for the source {source_id!r}"
        raise UnknownSourceError(msg) from err


def create_provider(source_id: str, *, session: aiohttp.ClientSession | None = None) -> ShowtimesProvider:
    """Create the provider registered under a source id.

    Args:
        source_id (str): The source id, e.g. ``allocine``.
        session (aiohttp.ClientSession | None): Home Assistant's shared session, passed to the provider.

    Returns:
        ShowtimesProvider: A new provider; ``UnknownSourceError`` is raised if the id is not registered.

    """
    return get_provider_class(source_id)(session=session)

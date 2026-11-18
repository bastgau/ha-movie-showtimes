"""The source-neutral contract every showtimes provider implements.

The integration depends on this module only: a provider hides one source (its API or site, its id format, its
time zone, its errors) behind it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

import aiohttp

from .models import DayShowtimes


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceInfo:
    """Static description of a source.

    Attributes:
        id (str): Provider id, ``^[a-z][a-z0-9]*$`` (no ``_``, so ``f"{id}_{cinema_id}"`` is unambiguous).
        name (str): The source's brand, not translated; used for the device manufacturer and in messages.
        time_zone (str): IANA time zone of the source's datetimes.
        ref_example (str): An example cinema reference, shown in the cinema step.
        url_example (str): An example cinema page URL, shown in the cinema step; empty if there is none.

    """

    id: str
    name: str
    time_zone: str
    ref_example: str
    url_example: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CinemaInfo:
    """A cinema the source knows.

    Attributes:
        cinema_id (str): The canonical cinema id.
        name (str | None): The source's name for the cinema, or ``None`` if it cannot tell.

    """

    cinema_id: str
    name: str | None


class ShowtimesProvider(ABC):
    """A source of showtimes.

    Attributes:
        source (SourceInfo): Static description of the source (class level).

    """

    source: ClassVar[SourceInfo]

    def __init__(self, *, session: aiohttp.ClientSession | None = None) -> None:  # noqa: B027
        """Create the provider.

        Args:
            session (aiohttp.ClientSession | None): Home Assistant's shared session, for async HTTP providers.

        """

    @abstractmethod
    def normalize_cinema_ref(self, raw: str) -> str:
        """Return the canonical cinema id from what the user typed (an id, a URL, ...).

        Pure, no I/O, and idempotent.

        Args:
            raw (str): The user's input.

        Returns:
            str: The canonical cinema id.

        """

    @abstractmethod
    async def async_get_day(self, cinema_id: str, day: date) -> DayShowtimes:
        """Fetch one day of showtimes. Never blocks the event loop and enforces its own timeouts.

        Args:
            cinema_id (str): The cinema's canonical id.
            day (date): The source's local date.

        Returns:
            DayShowtimes: The day's films; no film at all is valid data.

        """

    async def async_validate_cinema(self, cinema_id: str, day: date) -> CinemaInfo:
        """Check that the cinema exists, by fetching that day. An empty day is a success.

        Args:
            cinema_id (str): The cinema's canonical id.
            day (date): The date to fetch.

        Returns:
            CinemaInfo: The cinema, with no name.

        """
        await self.async_get_day(cinema_id, day)
        return CinemaInfo(cinema_id=cinema_id, name=None)

    def cinema_url(self, cinema_id: str) -> str | None:  # pylint: disable=redundant-returns-doc
        """Return the public page of the cinema, if the source has one.

        Args:
            cinema_id (str): The cinema's canonical id.

        Returns:
            str | None: The URL, or ``None``.

        """
        return None

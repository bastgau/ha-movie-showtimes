"""Source-neutral showtimes client of the Movie Showtimes integration.

The only code that talks to a showtimes source. It never imports Home Assistant, returns its own models and raises
its own exceptions. Providers are reached through the registry; they are not exported.
"""

from .exceptions import (
    CinemaNotFoundError,
    InvalidCinemaRefError,
    ShowtimesError,
    SourceAccessDeniedError,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
    UnknownSourceError,
)
from .models import DayShowtimes, Film, Showtime, ShowtimeVersion
from .provider import CinemaInfo, ShowtimesProvider, SourceInfo
from .registry import PROVIDERS, create_provider, get_provider_class

__all__ = [
    "PROVIDERS",
    "CinemaInfo",
    "CinemaNotFoundError",
    "DayShowtimes",
    "Film",
    "InvalidCinemaRefError",
    "Showtime",
    "ShowtimeVersion",
    "ShowtimesError",
    "ShowtimesProvider",
    "SourceAccessDeniedError",
    "SourceConnectionError",
    "SourceInfo",
    "SourceParseError",
    "SourceTimeoutError",
    "UnknownSourceError",
    "create_provider",
    "get_provider_class",
]

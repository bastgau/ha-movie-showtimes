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
from .models import Credit, DayShowtimes, Film, FilmDetails, Rating, Showtime, ShowtimeFormats, ShowtimeVersion
from .provider import CinemaInfo, ShowtimesProvider, SourceInfo
from .registry import PROVIDERS, create_provider, get_provider_class

__all__ = [
    "PROVIDERS",
    "CinemaInfo",
    "CinemaNotFoundError",
    "Credit",
    "DayShowtimes",
    "Film",
    "FilmDetails",
    "InvalidCinemaRefError",
    "Rating",
    "Showtime",
    "ShowtimeFormats",
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

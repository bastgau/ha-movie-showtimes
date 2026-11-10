"""Constants of the Movie Showtimes integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "movie_showtimes"

CONF_SOURCE: Final = "source"
"""The provider id of the entry, e.g. ``allocine``."""

CONF_CINEMA_ID: Final = "cinema_id"
"""The provider's canonical cinema id."""

UPDATE_INTERVAL: Final = timedelta(hours=12)
"""Time between two refreshes: twice a day, to be gentle with the source."""

RETRY_AFTER_CONNECTION_ERROR: Final = timedelta(minutes=30)
"""Delay before the next attempt after a transient connection error, instead of ``UPDATE_INTERVAL``."""

DAYS_EXPOSED: Final = 7
"""Number of day sensors: today to today + 6."""

DAYS_FETCHED: Final = 8
"""Number of days fetched per refresh: today to today + 7, one buffer day for the midnight rollover."""

SHOWTIME_GRACE_PERIOD: Final = timedelta(minutes=15)
"""A showtime stays visible until its start plus this."""

MAX_DATA_AGE: Final = timedelta(hours=48)
"""A day's data is shown at most this long after it was fetched."""

STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 1

ATTR_DATE: Final = "date"
ATTR_FETCHED_AT: Final = "fetched_at"
ATTR_FILMS: Final = "films"
ATTR_TITLE: Final = "title"
ATTR_VF: Final = "vf"
ATTR_VO: Final = "vo"
ATTR_OTHER: Final = "other"

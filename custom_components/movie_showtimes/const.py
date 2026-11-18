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
ATTR_VOST: Final = "vost"
ATTR_ACCESSIBILITY: Final = "accessibility"
ATTR_PMR: Final = "pmr"
ATTR_SME: Final = "sme"
ATTR_AUDIO_DESCRIPTION: Final = "audio_description"
ATTR_DETAILS: Final = "details"
ATTR_SHOWTIMES: Final = "showtimes"

# Film keys of a ``films`` item. Stable: renaming one breaks the users' templates.
ATTR_FILM_ID: Final = "film_id"
ATTR_URL: Final = "url"
ATTR_POSTER: Final = "poster"
ATTR_FILM_TYPE: Final = "film_type"
ATTR_ORIGINAL_TITLE: Final = "original_title"
ATTR_YEAR: Final = "year"
ATTR_RELEASE_DATE: Final = "release_date"
ATTR_VISA_NUMBER: Final = "visa_number"
ATTR_RUNTIME: Final = "runtime"
ATTR_GENRES: Final = "genres"
ATTR_CERTIFICATE: Final = "certificate"
ATTR_COUNTRIES: Final = "countries"
ATTR_LANGUAGES: Final = "languages"
ATTR_DIRECTORS: Final = "directors"
ATTR_USER_RATING: Final = "user_rating"
ATTR_USER_RATING_COUNT: Final = "user_rating_count"
ATTR_USER_REVIEW_COUNT: Final = "user_review_count"
ATTR_PRESS_RATING: Final = "press_rating"
ATTR_PRESS_RATING_COUNT: Final = "press_rating_count"
ATTR_WANT_TO_SEE_COUNT: Final = "want_to_see_count"
ATTR_HITS: Final = "hits"
ATTR_SESSIONS: Final = "sessions"
ATTR_PREMIERE: Final = "premiere"
ATTR_WEEKLY_OUTING: Final = "weekly_outing"
ATTR_HAS_TRAILER: Final = "has_trailer"
ATTR_FLAGS: Final = "flags"
ATTR_SYNOPSIS: Final = "synopsis"
ATTR_SYNOPSIS_FULL: Final = "synopsis_full"
ATTR_CAST: Final = "cast"
ATTR_CREDITS: Final = "credits"
ATTR_RELATED_TAGS: Final = "related_tags"
ATTR_NAME: Final = "name"
ATTR_ROLE: Final = "role"

# Keys of a ``details.showtimes`` item.
ATTR_TIME: Final = "time"
ATTR_STARTS_AT: Final = "starts_at"
ATTR_VERSION: Final = "version"
ATTR_SUBTITLED: Final = "subtitled"
ATTR_PREVIEW: Final = "preview"
ATTR_TICKET_URL: Final = "ticket_url"
ATTR_PROJECTION: Final = "projection"
ATTR_PICTURE: Final = "picture"
ATTR_SOUND: Final = "sound"
ATTR_EXPERIENCE: Final = "experience"
ATTR_COMFORT: Final = "comfort"

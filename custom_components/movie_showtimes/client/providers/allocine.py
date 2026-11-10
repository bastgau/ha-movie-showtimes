"""AlloCiné provider, wrapping the synchronous ``allocine-seances`` library.

The library is blocking (``requests``) and sets no timeout. This module runs it in the event loop's default
executor, gives every HTTP request a connect and read timeout, bounds the whole call with an ``asyncio``
timeout, and turns the library's raw dicts and errors into this package's models and exceptions. Everything
specific to AlloCiné lives here.
"""

import asyncio
from datetime import date, datetime
from functools import partial
from http import HTTPStatus
import json
import logging
import re
from typing import Any, ClassVar, Final, cast, override
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import aiohttp
from allocineAPI.allocineAPI import allocineAPI
import requests

from ..exceptions import (
    CinemaNotFoundError,
    InvalidCinemaRefError,
    ShowtimesError,
    SourceAccessDeniedError,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
)
from ..models import DayShowtimes, Film, Showtime, ShowtimeVersion
from ..provider import ShowtimesProvider, SourceInfo

_LOGGER = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT: Final = 10.0
"""Seconds allowed to connect, per HTTP request (enforced inside the worker thread)."""

DEFAULT_READ_TIMEOUT: Final = 20.0
"""Seconds allowed per read, per HTTP request (enforced inside the worker thread)."""

DEFAULT_CALL_TIMEOUT: Final = 60.0
"""Seconds allowed for a whole day call, pagination included (``asyncio`` backstop)."""

ALLOCINE_TIME_ZONE: Final = "Europe/Paris"
"""The time zone of the naive datetimes AlloCiné returns."""

USER_AGENT: Final = "ha-movie-showtimes/0.1"
"""The honest identity sent to allocine.fr, which refuses the library's default ``python-requests`` one."""

_ACCESS_DENIED_STATUSES: Final = frozenset({HTTPStatus.FORBIDDEN, HTTPStatus.TOO_MANY_REQUESTS})

_CINEMA_URL: Final = "https://www.allocine.fr/seance/salle_gen_csalle={cinema_id}.html"

_CINEMA_ID_PATTERN: Final = re.compile(r"[A-Z0-9]{2,10}", re.ASCII)
_CINEMA_PATH_PATTERN: Final = re.compile(r"/seance/salle_gen_csalle=([A-Za-z0-9]+)\.html/?", re.ASCII)
_ALLOWED_SCHEMES: Final = {"http": 80, "https": 443}
_ALLOWED_HOSTS: Final = frozenset({"allocine.fr", "www.allocine.fr", "m.allocine.fr"})

_VERSIONS: Final = {
    "ORIGINAL": ShowtimeVersion.ORIGINAL,
    "DUBBED": ShowtimeVersion.DUBBED,
    "LOCAL": ShowtimeVersion.LOCAL,
}


def _cinema_id_from_url(url: str) -> str:
    """Extract the raw cinema id from an allocine.fr cinema page URL.

    Args:
        url (str): The URL, with a scheme.

    Returns:
        str: The id as it appears in the URL, not yet validated nor upper-cased.

    Raises:
        InvalidCinemaRefError: Not an allocine.fr cinema page URL.

    """
    msg = f"Not an allocine.fr cinema page URL: {url!r}"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as err:
        raise InvalidCinemaRefError(msg) from err

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES or parts.hostname not in _ALLOWED_HOSTS:
        raise InvalidCinemaRefError(msg)
    if (port is not None and port != _ALLOWED_SCHEMES[scheme]) or parts.username is not None:
        raise InvalidCinemaRefError(msg)

    match = _CINEMA_PATH_PATTERN.fullmatch(parts.path)
    if match is None:
        raise InvalidCinemaRefError(msg)
    return match.group(1)


def _as_dict(value: object) -> dict[str, Any] | None:
    """Return ``value`` typed as a JSON object, or ``None`` if it is not a dict.

    Args:
        value (object): A decoded JSON value.

    Returns:
        dict[str, Any] | None: The same object, or ``None``.

    """
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[Any] | None:
    """Return ``value`` typed as a JSON array, or ``None`` if it is not a list.

    Args:
        value (object): A decoded JSON value.

    Returns:
        list[Any] | None: The same object, or ``None``.

    """
    return cast("list[Any]", value) if isinstance(value, list) else None


def _is_non_film(item: object) -> bool:
    """Tell whether a showtimes result is a non-film event (``"movie": null``).

    Args:
        item (object): One item of the response's ``results``.

    Returns:
        bool: ``True`` if the item has a ``movie`` key set to ``None``.

    """
    result = _as_dict(item)
    return result is not None and "movie" in result and result["movie"] is None


class _AllocineAPIWithTimeout(allocineAPI):
    """The library's class, with a timeout and typed errors on the JSON requests ``get_showtime`` makes.

    Attributes:
        _timeout (tuple[float, float]): The ``(connect, read)`` timeout of every request.

    """

    def __init__(self, *, connect_timeout: float, read_timeout: float) -> None:
        """Store the per-request timeouts.

        Args:
            connect_timeout (float): Seconds allowed to connect.
            read_timeout (float): Seconds allowed per read.

        """
        self._timeout = (connect_timeout, read_timeout)

    @override
    def _get_json_request(self, path: str, url_params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch a JSON document, as the library does, but with a timeout and typed errors.

        Results whose ``movie`` is ``None`` (non-film events) are removed: the library would otherwise fail on
        them with a ``TypeError``.

        Args:
            path (str): The URL to fetch.
            url_params (dict[str, Any] | None): The query parameters.

        Returns:
            dict[str, Any]: The decoded JSON object.

        Raises:
            CinemaNotFoundError: HTTP 404.
            SourceAccessDeniedError: HTTP 403 or 429.
            SourceConnectionError: Any other status than 200.
            SourceParseError: The body is not a JSON object.

        """
        # The canonical URL ends with "/": without it allocine.fr answers a 301 to it, doubling the requests.
        parts = urlsplit(path)
        if not parts.path.endswith("/"):
            path = urlunsplit(parts._replace(path=f"{parts.path}/"))
        response = requests.get(path, params=url_params, headers={"User-Agent": USER_AGENT}, timeout=self._timeout)
        if response.status_code == HTTPStatus.NOT_FOUND:
            msg = f"AlloCiné has no such cinema (HTTP 404 for {path})"
            raise CinemaNotFoundError(msg)
        if response.status_code in _ACCESS_DENIED_STATUSES:
            msg = f"allocine.fr refused the request (HTTP {response.status_code})"
            raise SourceAccessDeniedError(msg, status_code=response.status_code)
        if response.status_code != HTTPStatus.OK:
            msg = f"HTTP {response.status_code}"
            raise SourceConnectionError(msg)

        try:
            payload: object = json.loads(response.text)
        except ValueError as err:
            msg = f"The response of {path} is not JSON"
            raise SourceParseError(msg) from err
        document = _as_dict(payload)
        if document is None:
            msg = f"The response of {path} is not a JSON object"
            raise SourceParseError(msg)

        results = _as_list(document.get("results"))
        if results is not None:
            kept = [item for item in results if not _is_non_film(item)]
            if len(kept) != len(results):
                _LOGGER.debug("Ignored %d non-film result(s) in %s", len(results) - len(kept), path)
                document["results"] = kept
        return document

    def fetch_showtimes(self, cinema_id: str, date_str: str) -> object:
        """Run the library's ``get_showtime``, typed: its result is checked by the caller.

        Args:
            cinema_id (str): The normalized cinema id.
            date_str (str): The date, ``YYYY-MM-DD``.

        Returns:
            object: The library's list of ``{"title", "showtimes"}`` dicts.

        """
        return self.get_showtime(cinema_id, date_str)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


class AllocineProvider(ShowtimesProvider):
    """Async access to one cinema's showtimes on allocine.fr.

    Attributes:
        source (SourceInfo): AlloCiné's description.
        _api (_AllocineAPIWithTimeout): The library instance; it keeps no state, so it is safe in the executor.
        _call_timeout (float): Seconds allowed for a whole day call.
        _warned_versions (set[str]): The unknown ``diffusionVersion`` values already logged.

    """

    source: ClassVar[SourceInfo] = SourceInfo(
        id="allocine",
        name="AlloCiné",
        time_zone=ALLOCINE_TIME_ZONE,
        ref_example="W0124",
        url_example=_CINEMA_URL.format(cinema_id="W0124"),
    )

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        call_timeout: float = DEFAULT_CALL_TIMEOUT,
    ) -> None:
        """Create the provider.

        Args:
            session (aiohttp.ClientSession | None): Ignored: the library does its own synchronous HTTP.
            connect_timeout (float): Seconds allowed to connect, per HTTP request.
            read_timeout (float): Seconds allowed per read, per HTTP request.
            call_timeout (float): Seconds allowed for a whole day call, pagination included.

        """
        super().__init__(session=session)
        self._api = _AllocineAPIWithTimeout(connect_timeout=connect_timeout, read_timeout=read_timeout)
        self._call_timeout = call_timeout
        self._warned_versions: set[str] = set()

    @override
    def normalize_cinema_ref(self, raw: str) -> str:
        """Return the cinema id from a bare id or an allocine.fr cinema page URL.

        A bare id is upper-cased and must be 2 to 10 ASCII letters or digits. A URL must be
        ``http(s)://[www.|m.]allocine.fr/seance/salle_gen_csalle=<ID>.html`` (trailing ``/``, query and fragment
        allowed); a missing scheme is completed with ``https://``. No I/O.

        Args:
            raw (str): What the user typed: an id such as ``W0124`` or a cinema page URL.

        Returns:
            str: The normalized id, e.g. ``W0124``.

        Raises:
            InvalidCinemaRefError: Neither a valid id nor a supported URL.

        """
        value = raw.strip()
        if not value:
            msg = "The cinema id is empty"
            raise InvalidCinemaRefError(msg)

        lowered = value.lower()
        if "://" in value or lowered.startswith(("www.", "allocine.fr")):
            value = _cinema_id_from_url(value if "://" in value else f"https://{value}")

        candidate = value.upper()
        if not value.isascii() or _CINEMA_ID_PATTERN.fullmatch(candidate) is None:
            msg = f"Not a valid AlloCiné cinema id: {raw!r}"
            raise InvalidCinemaRefError(msg)
        return candidate

    @override
    def cinema_url(self, cinema_id: str) -> str | None:
        """Return the cinema's page on allocine.fr.

        Args:
            cinema_id (str): The cinema's canonical id.

        Returns:
            str | None: The page URL.

        """
        return _CINEMA_URL.format(cinema_id=cinema_id)

    @override
    async def async_get_day(self, cinema_id: str, day: date) -> DayShowtimes:
        """Fetch and parse one day's showtimes, off the event loop.

        Args:
            cinema_id (str): The cinema id, or its allocine.fr cinema page URL.
            day (date): The AlloCiné date to fetch.

        Returns:
            DayShowtimes: The day's films; no film at all is valid data.

        Raises:
            SourceTimeoutError: A request, or the whole call, took too long.

        """
        normalized = self.normalize_cinema_ref(cinema_id)
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout(self._call_timeout):
                return await loop.run_in_executor(None, partial(self._fetch_day_sync, normalized, day))
        except TimeoutError as err:
            msg = f"Fetching the showtimes of {normalized} for {day.isoformat()} took more than {self._call_timeout} s"
            raise SourceTimeoutError(msg) from err

    def _fetch_day_sync(self, cinema_id: str, day: date) -> DayShowtimes:
        """Fetch and convert one day. Blocking: runs in the executor.

        Args:
            cinema_id (str): The normalized cinema id.
            day (date): The AlloCiné date to fetch.

        Returns:
            DayShowtimes: The converted day.

        Raises:
            SourceTimeoutError: An HTTP request timed out.
            SourceConnectionError: allocine.fr could not be reached.
            SourceParseError: The response did not have the expected shape.
            ShowtimesError: Any other library failure.

        """
        try:
            raw = self._api.fetch_showtimes(cinema_id, day.isoformat())
            return self._convert_day(cinema_id, day, raw)
        except ShowtimesError:
            raise
        except requests.Timeout as err:
            msg = f"allocine.fr did not answer in time for {cinema_id} on {day.isoformat()}"
            raise SourceTimeoutError(msg) from err
        except requests.RequestException as err:
            msg = f"Could not reach allocine.fr for {cinema_id} on {day.isoformat()}: {err}"
            raise SourceConnectionError(msg) from err
        except (KeyError, TypeError, ValueError) as err:
            msg = f"Unexpected showtimes data for {cinema_id} on {day.isoformat()}: {err!r}"
            raise SourceParseError(msg) from err
        except Exception as err:
            msg = f"The AlloCiné library failed for {cinema_id} on {day.isoformat()}: {err!r}"
            raise ShowtimesError(msg) from err

    def _convert_day(self, cinema_id: str, day: date, raw: object) -> DayShowtimes:
        """Convert the library's list of films into a ``DayShowtimes``.

        Args:
            cinema_id (str): The normalized cinema id.
            day (date): The AlloCiné date fetched.
            raw (object): What ``get_showtime`` returned.

        Returns:
            DayShowtimes: The films with at least one showtime, sorted by title.

        Raises:
            SourceParseError: The data does not have the expected shape.

        """
        items = _as_list(raw)
        if items is None:
            msg = f"Expected a list of films, got {type(raw).__name__}"
            raise SourceParseError(msg)

        time_zone = ZoneInfo(self.source.time_zone)
        films: list[Film] = []
        for item in items:
            film = self._convert_film(item, time_zone)
            if film is not None:
                films.append(film)
        films.sort(key=lambda film: film.title.casefold())
        return DayShowtimes(cinema_id=cinema_id, day=day, films=tuple(films))

    def _convert_film(self, item: object, time_zone: ZoneInfo) -> Film | None:
        """Convert one film of the library's result.

        Args:
            item (object): One ``{"title", "showtimes"}`` dict.
            time_zone (ZoneInfo): The zone of AlloCiné's naive datetimes.

        Returns:
            Film | None: The film, or ``None`` if it has no showtime.

        Raises:
            SourceParseError: The film does not have the expected shape.

        """
        film = _as_dict(item)
        if film is None:
            msg = f"Expected a film object, got {type(item).__name__}"
            raise SourceParseError(msg)

        title = film.get("title")
        if not isinstance(title, str) or not title.strip():
            msg = f"A film has no usable title: {title!r}"
            raise SourceParseError(msg)

        entries = _as_list(film.get("showtimes"))
        if entries is None:
            msg = f"The film {title!r} has no showtimes list"
            raise SourceParseError(msg)

        showtimes = sorted(
            (self._convert_showtime(entry, title, time_zone) for entry in entries),
            key=lambda showtime: showtime.starts_at,
        )
        if not showtimes:
            return None
        return Film(title=title, showtimes=tuple(showtimes))

    def _convert_showtime(self, entry: object, title: str, time_zone: ZoneInfo) -> Showtime:
        """Convert one ``{"startsAt", "diffusionVersion"}`` dict.

        Args:
            entry (object): The library's showtime dict.
            title (str): The film's title, for the error messages.
            time_zone (ZoneInfo): The zone of AlloCiné's naive datetimes.

        Returns:
            Showtime: The showtime, with an aware start in ``time_zone``.

        Raises:
            SourceParseError: The start is missing or not an ISO datetime.

        """
        showtime = _as_dict(entry)
        if showtime is None:
            msg = f"A showtime of {title!r} is not an object"
            raise SourceParseError(msg)

        starts_at_raw = showtime.get("startsAt")
        if not isinstance(starts_at_raw, str):
            msg = f"A showtime of {title!r} has no start: {starts_at_raw!r}"
            raise SourceParseError(msg)
        try:
            starts_at = datetime.fromisoformat(starts_at_raw)
        except ValueError as err:
            msg = f"A showtime of {title!r} has an invalid start: {starts_at_raw!r}"
            raise SourceParseError(msg) from err
        starts_at = starts_at.replace(tzinfo=time_zone) if starts_at.tzinfo is None else starts_at.astimezone(time_zone)

        return Showtime(starts_at=starts_at, version=self._convert_version(showtime.get("diffusionVersion")))

    def _convert_version(self, raw: object) -> ShowtimeVersion:
        """Map AlloCiné's ``diffusionVersion`` to a ``ShowtimeVersion``.

        An unknown value becomes ``UNKNOWN``, with one warning per value for the client's lifetime.

        Args:
            raw (object): The ``diffusionVersion`` value.

        Returns:
            ShowtimeVersion: The mapped version.

        """
        if isinstance(raw, str) and (version := _VERSIONS.get(raw)) is not None:
            return version
        key = repr(raw)
        if key not in self._warned_versions:
            self._warned_versions.add(key)
            _LOGGER.warning("Unknown AlloCiné diffusionVersion %s, shown as 'other'", key)
        return ShowtimeVersion.UNKNOWN

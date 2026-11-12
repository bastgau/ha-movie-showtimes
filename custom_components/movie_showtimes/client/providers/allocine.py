"""AlloCiné provider, wrapping the synchronous ``allocine-seances`` library.

The library is blocking (``requests``) and sets no timeout. This module runs it in the event loop's default
executor, gives every HTTP request a connect and read timeout, bounds the whole call with an ``asyncio``
timeout, and turns the library's raw dicts and errors into this package's models and exceptions. Everything
specific to AlloCiné lives here.
"""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from functools import partial
from http import HTTPStatus
import json
import logging
import re
import time
from typing import Any, ClassVar, Final, cast, override
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import aiohttp
from allocineAPI.allocineAPI import URLs, allocineAPI
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
from ..models import Credit, DayShowtimes, Film, FilmDetails, Rating, Showtime, ShowtimeFormats, ShowtimeVersion
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

_SHOWTIME_LISTS: Final = ("original", "original_st", "original_sme", "multiple", "multiple_st", "multiple_sme")
_CLASSIC_SUBTITLE_LISTS: Final = frozenset({"original_st", "multiple_st"})
_SME_LISTS: Final = frozenset({"original_sme", "multiple_sme"})
_SUBTITLED_TAG: Final = "Showtime.Accessibility.Subtitled"
_SUBTITLE_LANGUAGE_TAG_PREFIX: Final = "Localization.Subtitle."
_DISABLED_ACCESS_SERVICE: Final = "DISABLED_ACCESS"
_DISABLED_ACCESS_TAG: Final = "Theater.Service.DisabledAccess"
_AUDIO_DESCRIPTION_TAG: Final = "Showtime.Accessibility.Greta"
"""Assumed to mean audio description (Greta is an audio description app); no AlloCiné source confirms it."""
_FRENCH_ONLY: Final = ["FRENCH"]
_DIRECTOR: Final = "DIRECTOR"
_DESKTOP: Final = "DESKTOP"
_TICKET_PROVIDER_ORDER: Final = ("default", "relay")
"""The preferred DESKTOP ticketing providers, in order; any other comes after them, in document order."""
_FORMAT_KEYS: Final = ("projection", "picture", "sound", "experience", "comfort")
_MAX_PAGES: Final = 20
"""More showtimes pages than this for one day is taken as a broken response, not fetched."""
_FILM_URL: Final = "https://www.allocine.fr/film/fichefilm_gen_cfilm={ref}.html"
_RUNTIME_PATTERN: Final = re.compile(r"\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*min)?\s*", re.ASCII)
_CONTROL_CHARACTERS: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MAX_SCORE: Final = 5
_MIN_YEAR: Final = 1870
_MAX_YEAR: Final = 2100
_NO_DETAILS: Final = FilmDetails()
_NO_FORMATS: Final = ShowtimeFormats()
_ENRICHMENT_ERRORS: Final = (KeyError, TypeError, ValueError, AttributeError, IndexError)
"""Caught around the optional fields (D28): an odd one is dropped, it never fails the day."""


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


def _page_number(raw: object, what: str) -> int:
    """Read a page number of the ``pagination`` object: an ``int`` or a decimal string, never negative.

    Args:
        raw (object): The value of ``page`` or ``totalPages``.
        what (str): Which one it is, for the error message.

    Returns:
        int: The number.

    Raises:
        SourceParseError: Not a non-negative integer.

    """
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal():
        return int(raw)
    msg = f"Unexpected pagination {what}: {raw!r}"
    raise SourceParseError(msg)


def _pagination(document: dict[str, Any]) -> tuple[int, int]:
    """Read ``pagination.page`` and ``pagination.totalPages`` of a showtimes page.

    Args:
        document (dict[str, Any]): One decoded page.

    Returns:
        tuple[int, int]: ``(page, total_pages)``.

    Raises:
        SourceParseError: ``pagination`` is missing or not an object, or a number is unreadable.

    """
    pagination = _as_dict(document.get("pagination"))
    if pagination is None:
        msg = "The showtimes page has no pagination object"
        raise SourceParseError(msg)
    return _page_number(pagination.get("page"), "page"), _page_number(pagination.get("totalPages"), "totalPages")


def _showtime_url(cinema_id: str, date_str: str, page: int) -> str:
    """Return the library's showtimes page URL (its public ``URLs.showtime_url``), typed.

    Args:
        cinema_id (str): The normalized cinema id.
        date_str (str): The date, ``YYYY-MM-DD``.
        page (int): The page number, from 1.

    Returns:
        str: The URL, without the trailing slash ``_get_json_request`` adds.

    """
    return str(URLs.showtime_url(cinema_id, date_str, page))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


class _AllocineAPIWithTimeout(allocineAPI):
    """The library's class, with a timeout and typed errors on its JSON requests, and our own pagination.

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
        return document

    def fetch_showtime_pages(
        self, cinema_id: str, date_str: str, *, deadline: float | None = None
    ) -> list[dict[str, Any]]:
        """Fetch every showtimes page of one day, in order: one request per page, as the library does.

        Local variables only, no state on the instance: two calls can run at once in two threads. The deadline is
        checked before every request, so a thread the ``asyncio`` backstop gave up on stops paginating.

        Args:
            cinema_id (str): The normalized cinema id.
            date_str (str): The date, ``YYYY-MM-DD``.
            deadline (float | None): The ``time.monotonic()`` instant after which no request is started.

        Returns:
            list[dict[str, Any]]: The decoded pages, the first one included even when the day is empty.

        Raises:
            SourceParseError: The pagination is unreadable, implausible, or a page is not the one requested.
            SourceTimeoutError: The deadline passed before a page was requested.

        """
        if deadline is not None and time.monotonic() >= deadline:
            msg = f"No time left to fetch page 1 of {cinema_id} on {date_str}"
            raise SourceTimeoutError(msg)
        first = self._get_json_request(_showtime_url(cinema_id, date_str, 1))
        page, total = _pagination(first)
        if total > _MAX_PAGES:
            msg = f"Implausible pagination for {cinema_id} on {date_str}: {total} pages"
            raise SourceParseError(msg)
        if page != 1:
            msg = f"Asked for page 1 of {cinema_id} on {date_str}, got page {page}"
            raise SourceParseError(msg)
        pages = [first]
        for number in range(2, total + 1):
            if deadline is not None and time.monotonic() >= deadline:
                msg = f"No time left to fetch page {number} of {cinema_id} on {date_str}: the whole call timed out"
                raise SourceTimeoutError(msg)
            document = self._get_json_request(_showtime_url(cinema_id, date_str, number))
            page, _ = _pagination(document)
            if page != number:
                msg = f"Asked for page {number} of {cinema_id} on {date_str}, got page {page}"
                raise SourceParseError(msg)
            pages.append(document)
        return pages


def parse_runtime(raw: object) -> int | None:
    """Read AlloCiné's runtime, e.g. ``"2h 25min"``, as minutes.

    Args:
        raw (object): The ``movie.runtime`` value.

    Returns:
        int | None: The minutes, > 0; ``None`` when absent, zero (``"0h 00min"``: unknown) or unreadable.

    """
    if raw is None:
        return None
    if isinstance(raw, str):
        match = _RUNTIME_PATTERN.fullmatch(raw)
        if match is not None and (match.group(1) is not None or match.group(2) is not None):
            minutes = int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
            return minutes if minutes > 0 else None
        if not raw.strip():
            return None
    _LOGGER.debug("Unreadable AlloCiné runtime %r", raw)
    return None


def _text(raw: object, label: str) -> str | None:
    """Read an optional string: stripped, non-empty.

    Args:
        raw (object): The value.
        label (str): Its name, for the debug line.

    Returns:
        str | None: The stripped string, or ``None``.

    """
    if isinstance(raw, str):
        return raw.strip() or None
    if raw is not None:
        _LOGGER.debug("Ignoring the AlloCiné field %s: %r", label, raw)
    return None


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    """Return the non-blank strings of ``values``, stripped, in order, without duplicates.

    Args:
        values (Iterable[str]): The strings.

    Returns:
        tuple[str, ...]: The kept strings.

    """
    return tuple(dict.fromkeys(stripped for value in values if (stripped := value.strip())))


def _texts(raw: object, label: str) -> tuple[str, ...]:
    """Read an optional list of strings; non-string items are skipped.

    Args:
        raw (object): The value.
        label (str): Its name, for the debug line.

    Returns:
        tuple[str, ...]: The strings, stripped, in order, without duplicates; ``()`` when not a list.

    """
    items = _as_list(raw)
    if items is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné field %s: %r", label, raw)
        return ()
    return _unique(item for item in items if isinstance(item, str))


def _texts_of(raw: object, label: str, *keys: str) -> tuple[str, ...]:
    """Read a list of objects, each named by the first of ``keys`` that holds a non-blank string.

    Args:
        raw (object): The list.
        label (str): Its name, for the debug line.
        *keys (str): The keys to try in each object, in order.

    Returns:
        tuple[str, ...]: The names, in order, without duplicates; ``()`` when not a list.

    """
    items = _as_list(raw)
    if items is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné field %s: %r", label, raw)
        return ()
    names: list[str] = []
    skipped = 0
    for item in items:
        entry = _as_dict(item) or {}
        name = next((value for key in keys if isinstance(value := entry.get(key), str) and value.strip()), None)
        if name is not None:
            names.append(name)
        else:
            skipped += 1
    if skipped:
        _LOGGER.debug("Ignoring %d unreadable item(s) of the AlloCiné field %s", skipped, label)
    return _unique(names)


def _object(raw: object, label: str) -> dict[str, Any]:
    """Read an optional JSON object; anything else is empty.

    Args:
        raw (object): The value.
        label (str): Its name, for the debug line (only for an unexpected type, never for ``null``).

    Returns:
        dict[str, Any]: The object, or ``{}``.

    """
    value = _as_dict(raw)
    if value is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné field %s: %r", label, raw)
        return {}
    return value


def _note(noted: set[str], key: str, raw: object) -> None:
    """Log, once per key and per day, a showtime value of an unexpected type.

    Args:
        noted (set[str]): The keys already logged for this day; updated.
        key (str): The showtime key.
        raw (object): The value, for the debug line.

    """
    if key not in noted:
        noted.add(key)
        _LOGGER.debug("Ignoring the AlloCiné showtime field %s: %r (logged once per day)", key, raw)


def _flag(raw: object) -> bool | None:
    """Read an optional boolean: only a real ``bool`` counts.

    Args:
        raw (object): The value.

    Returns:
        bool | None: The boolean, or ``None``.

    """
    return raw if isinstance(raw, bool) else None


def _count(raw: object, label: str) -> int | None:
    """Read an optional counter: an ``int`` >= 0, not a ``bool``.

    Args:
        raw (object): The value.
        label (str): Its name, for the debug line.

    Returns:
        int | None: The counter, or ``None``.

    """
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    if raw is not None:
        _LOGGER.debug("Ignoring the AlloCiné counter %s: %r", label, raw)
    return None


def _rating(raw: object, label: str) -> Rating | None:
    """Read a ``{score, count}`` rating; the score must be a number in 0 to 5.

    Args:
        raw (object): The rating object.
        label (str): Its name, for the debug line.

    Returns:
        Rating | None: The rating, or ``None`` without a usable score.

    """
    rating = _as_dict(raw)
    if rating is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné rating %s: %r", label, raw)
        return None
    score = rating.get("score")
    if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= _MAX_SCORE:
        if score is not None:
            _LOGGER.debug("Ignoring the AlloCiné rating %s: score %r", label, score)
        return None
    return Rating(score=float(score), count=_count(rating.get("count"), f"{label}.count"))


def _http_url(raw: object, label: str) -> str | None:
    """Keep a URL verbatim if it is an absolute ``http(s)`` URL with a host.

    Args:
        raw (object): The value.
        label (str): Its name, for the debug line.

    Returns:
        str | None: The URL unchanged (never re-encoded), or ``None``.

    """
    if _is_http_url(raw):
        return cast("str", raw)
    if raw is not None:
        _LOGGER.debug("Ignoring the AlloCiné URL %s: %r", label, raw)
    return None


def _is_http_url(raw: object) -> bool:
    """Tell whether a value is an absolute ``http(s)`` URL with a host, usable verbatim.

    Leading whitespace and control characters are refused. Raw spaces inside and at the end are accepted: AlloCiné's
    ``relay`` URLs have them (``…&code=VO; SUBTITLE``, ``…&code=vf; pmr; ``).

    Args:
        raw (object): The value.

    Returns:
        bool: ``True`` when the value can be kept as is.

    """
    if not isinstance(raw, str) or raw != raw.lstrip() or _CONTROL_CHARACTERS.search(raw) is not None:
        return False
    try:
        parts = urlsplit(raw)
    except ValueError:
        return False
    return parts.scheme.lower() in _ALLOWED_SCHEMES and bool(parts.hostname)


def _person_name(raw: object) -> str | None:
    """Build ``"<firstName> <lastName>"`` from whichever parts are strings.

    Args:
        raw (object): A person object.

    Returns:
        str | None: The name, or ``None`` if empty.

    """
    person = _as_dict(raw)
    if person is None:
        return None
    parts = [part.strip() for key in ("firstName", "lastName") if isinstance(part := person.get(key), str)]
    return " ".join(part for part in parts if part) or None


def _credits(raw: object) -> tuple[Credit, ...]:
    """Read ``movie.credits``: one credit per item with a name and a ``position.name``.

    Args:
        raw (object): The credits list.

    Returns:
        tuple[Credit, ...]: The credits, in order, without duplicates.

    """
    items = _as_list(raw)
    if items is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné credits: %r", raw)
        return ()
    found: dict[Credit, None] = {}
    for item in items:
        entry = _as_dict(item) or {}
        name = _person_name(entry.get("person"))
        role = (_as_dict(entry.get("position")) or {}).get("name")
        if name is not None and isinstance(role, str) and role.strip():
            found[Credit(name=name, role=role.strip())] = None
    return tuple(found)


def _cast(raw: object) -> tuple[str, ...]:
    """Read ``movie.cast.edges``: the actor, else the original voice, else the voice of each node.

    Args:
        raw (object): The ``movie.cast`` object.

    Returns:
        tuple[str, ...]: The names, in the order received, without duplicates.

    """
    raw_edges = _object(raw, "cast").get("edges")
    edges = _as_list(raw_edges)
    if edges is None:
        if raw_edges is not None:
            _LOGGER.debug("Ignoring the AlloCiné field cast.edges: %r", raw_edges)
        return ()
    names: list[str] = []
    for edge in edges:
        node = _as_dict((_as_dict(edge) or {}).get("node")) or {}
        name = next(
            (name for key in ("actor", "originalVoiceActor", "voiceActor") if (name := _person_name(node.get(key)))),
            None,
        )
        if name is not None:
            names.append(name)
    return _unique(names)


def _visa(raw: object) -> str | None:
    """Read a release's ``visaNumber``: a non-blank string, or an ``int`` converted.

    Args:
        raw (object): The value.

    Returns:
        str | None: The visa number, or ``None``.

    """
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return _text(raw, "visaNumber")


def _release_date(release: dict[str, Any]) -> str | None:
    """Read a release's ``releaseDate.date``, verbatim.

    Args:
        release (dict[str, Any]): One item of ``movie.releases``.

    Returns:
        str | None: The date string, or ``None``.

    """
    return _text((_as_dict(release.get("releaseDate")) or {}).get("date"), "releaseDate.date")


def _certificate(release: dict[str, Any]) -> str | None:
    """Read a release's ``certificate.label``, else its ``code``.

    Args:
        release (dict[str, Any]): One item of ``movie.releases``.

    Returns:
        str | None: The certificate, or ``None``.

    """
    certificate = _as_dict(release.get("certificate")) or {}
    return _text(certificate.get("label"), "certificate.label") or _text(certificate.get("code"), "certificate.code")


def _release(raw: object) -> tuple[str | None, str | None, str | None]:
    """Choose the release the date, visa and certificate come from.

    The first release with a visa gives all three; without any visa, each comes from the first release that has it.

    Args:
        raw (object): The ``movie.releases`` list.

    Returns:
        tuple[str | None, str | None, str | None]: ``(release_date, visa_number, certificate)``.

    """
    items = _as_list(raw)
    if items is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné releases: %r", raw)
        return None, None, None
    releases = [release for item in items if (release := _as_dict(item)) is not None]
    chosen = next((release for release in releases if _visa(release.get("visaNumber")) is not None), None)
    if chosen is not None:
        return _release_date(chosen), _visa(chosen.get("visaNumber")), _certificate(chosen)
    release_date = next((value for release in releases if (value := _release_date(release)) is not None), None)
    certificate = next((value for release in releases if (value := _certificate(release)) is not None), None)
    return release_date, None, certificate


def _year(raw: object) -> int | None:
    """Read ``data.productionYear``: an ``int`` in 1870 to 2100.

    Args:
        raw (object): The ``movie.data`` object.

    Returns:
        int | None: The year, or ``None``.

    """
    year = _object(raw, "data").get("productionYear")
    if isinstance(year, int) and not isinstance(year, bool) and _MIN_YEAR <= year <= _MAX_YEAR:
        return year
    if year is not None:
        _LOGGER.debug("Ignoring the AlloCiné production year %r", year)
    return None


def _true_flags(raw: object) -> tuple[str, ...]:
    """Return the keys of ``movie.flags`` whose value is exactly ``True``, in document order.

    Args:
        raw (object): The ``movie.flags`` object.

    Returns:
        tuple[str, ...]: The source names of the true flags.

    """
    flags = _as_dict(raw)
    if flags is None:
        if raw is not None:
            _LOGGER.debug("Ignoring the AlloCiné flags: %r", raw)
        return ()
    return tuple(name for name, value in flags.items() if value is True)


def _film_details(movie: dict[str, Any], ref: str | None) -> FilmDetails | None:
    """Read everything the showtimes document says about a film. Never raises on data.

    Args:
        movie (dict[str, Any]): The ``movie`` object.
        ref (str | None): The film id, if usable.

    Returns:
        FilmDetails | None: The details, or ``None`` when none is known.

    """
    stats = _object(movie.get("stats"), "stats")
    metric = _object(stats.get("metric"), "stats.metric")
    flags = _as_dict(movie.get("flags")) or {}  # Its type is logged by _true_flags.
    custom_flags = _object(movie.get("customFlags"), "customFlags")
    film_credits = _credits(movie.get("credits"))
    release_date, visa_number, certificate = _release(movie.get("releases"))
    details = FilmDetails(
        url=_FILM_URL.format(ref=ref) if ref is not None else None,
        film_type=_text(movie.get("type"), "type"),
        original_title=_text(movie.get("originalTitle"), "originalTitle"),
        year=_year(movie.get("data")),
        release_date=release_date,
        visa_number=visa_number,
        runtime=parse_runtime(movie.get("runtime")),
        genres=_texts_of(movie.get("genres"), "genres", "translate"),
        certificate=certificate,
        countries=_texts_of(movie.get("countries"), "countries", "localizedName", "name"),
        languages=_texts(movie.get("languages"), "languages"),
        directors=_unique(credit.name for credit in film_credits if credit.role == _DIRECTOR),
        poster_url=_http_url(_object(movie.get("poster"), "poster").get("url"), "poster.url"),
        synopsis=_text(movie.get("synopsis"), "synopsis"),
        synopsis_full=_text(movie.get("synopsisFull"), "synopsisFull"),
        cast=_cast(movie.get("cast")),
        credits=film_credits,
        related_tags=_texts_of(movie.get("relatedTags"), "relatedTags", "name"),
        user_rating=_rating(stats.get("userRating"), "userRating"),
        user_review_count=_count(_object(stats.get("userReview"), "userReview").get("count"), "userReview.count"),
        press_rating=_rating(stats.get("pressReview"), "pressReview"),
        want_to_see_count=_count(stats.get("wantToSeeCount"), "wantToSeeCount"),
        hits=_count(metric.get("hits"), "metric.hits"),
        sessions=_count(metric.get("sessions"), "metric.sessions"),
        premiere=_flag(custom_flags.get("isPremiere")),
        weekly_outing=_flag(custom_flags.get("weeklyOuting")),
        has_trailer=_flag(flags.get("hasTrailer")),
        flags=_true_flags(movie.get("flags")),
    )
    return None if details == _NO_DETAILS else details


def _ticket_url(raw: object, noted: set[str]) -> str | None:
    """Choose one DESKTOP booking link: provider ``default``, else ``relay``, else any other, in document order.

    Args:
        raw (object): The showtime's ``data`` object.
        noted (set[str]): The keys whose unexpected type was already logged for this day; updated.

    Returns:
        str | None: The first valid ``http(s)`` URL of the first candidate that has one, or ``None``.

    """
    data = _as_dict(raw)
    if data is None:
        if raw is not None:
            _note(noted, "data", raw)
        return None
    ticketing = data.get("ticketing")
    entries = _as_list(ticketing)
    if entries is None:
        if ticketing is not None:
            _note(noted, "data.ticketing", ticketing)
        return None
    desktop = [entry for item in entries if (entry := _as_dict(item)) is not None and entry.get("type") == _DESKTOP]

    def rank(entry: dict[str, Any]) -> int:
        provider = entry.get("provider")
        return (
            _TICKET_PROVIDER_ORDER.index(provider)
            if provider in _TICKET_PROVIDER_ORDER
            else len(_TICKET_PROVIDER_ORDER)
        )

    for entry in sorted(desktop, key=rank):  # sorted() is stable: document order within a rank.
        for url in _as_list(entry.get("urls")) or []:
            if _is_http_url(url):
                return cast("str", url)
            if url is not None:
                _note(noted, "data.ticketing.urls", url)
    return None


def _formats(entry: dict[str, Any], noted: set[str]) -> ShowtimeFormats | None:
    """Read the five format lists of a showtime, codes verbatim (``null`` is an empty list).

    Args:
        entry (dict[str, Any]): The showtime object.
        noted (set[str]): The keys whose unexpected type was already logged for this day; updated.

    Returns:
        ShowtimeFormats | None: The formats, or ``None`` when all five are empty.

    """
    values: dict[str, tuple[str, ...]] = {}
    for name in _FORMAT_KEYS:
        raw = entry.get(name)
        items = _as_list(raw)
        if items is None and raw is not None:
            _note(noted, name, raw)
        values[name] = _unique(item for item in items or [] if isinstance(item, str))
    formats = ShowtimeFormats(**values)
    return None if formats == _NO_FORMATS else formats


def _showtime_extras(entry: dict[str, Any], list_key: str, noted: set[str] | None = None) -> dict[str, Any]:
    """Read the optional fields of a showtime: subtitles, accessibility, formats, booking link. Never raises on data.

    Args:
        entry (dict[str, Any]): The showtime object.
        list_key (str): The ``showtimes`` list it came from.
        noted (set[str] | None): The keys of an unexpected type already logged for this day; ``None`` logs each.

    Returns:
        dict[str, Any]: Keyword arguments of ``Showtime``.

    """
    if noted is None:
        noted = set()
    raw_tags = entry.get("tags")
    tags_list = _as_list(raw_tags)
    if tags_list is None and raw_tags is not None:
        _note(noted, "tags", raw_tags)
    tags = {tag for tag in tags_list if isinstance(tag, str)} if tags_list is not None else set[str]()
    known = list_key in _SHOWTIME_LISTS

    subtitled: bool | None
    if list_key in _SME_LISTS:
        subtitled = False  # Those subtitles are SME, never "vost".
    elif (
        list_key in _CLASSIC_SUBTITLE_LISTS
        or _SUBTITLED_TAG in tags
        or any(tag.startswith(_SUBTITLE_LANGUAGE_TAG_PREFIX) for tag in tags)
    ):
        subtitled = True
    else:
        subtitled = False if known else None

    service = entry.get("service")
    service_list = _as_list(service)
    if service is not None and service_list is None:
        _note(noted, "service", service)
    disabled_access: bool | None
    if _DISABLED_ACCESS_TAG in tags or (service_list is not None and _DISABLED_ACCESS_SERVICE in service_list):
        disabled_access = True
    elif "service" in entry and (service is None or service_list is not None):
        disabled_access = False
    else:
        disabled_access = None

    return {
        "subtitled": subtitled,
        "hard_of_hearing_subtitles": (list_key in _SME_LISTS) if known else None,
        "disabled_access": disabled_access,
        "audio_description": (_AUDIO_DESCRIPTION_TAG in tags) if tags_list is not None else None,
        "formats": _formats(entry, noted),
        "preview": _flag(entry.get("isPreview")),
        "weekly_outing": _flag(entry.get("isWeeklyMovieOuting")),
        "ticket_url": _ticket_url(entry.get("data"), noted),
    }


def _merge_flag(first: bool | None, second: bool | None) -> bool | None:
    """Merge an accessibility or subtitle flag of two occurrences of one showtime.

    Args:
        first (bool | None): The flag of the kept occurrence.
        second (bool | None): The flag of the duplicate.

    Returns:
        bool | None: ``True`` if either is ``True``, else ``False`` if either is ``False``, else ``None``.

    """
    if first is True or second is True:
        return True
    if first is False or second is False:
        return False
    return None


def _merge_showtime(kept: Showtime, duplicate: Showtime) -> Showtime:
    """Merge a duplicate occurrence into the kept one: only the four flags are combined.

    Args:
        kept (Showtime): The first occurrence.
        duplicate (Showtime): A later occurrence with the same id.

    Returns:
        Showtime: The kept occurrence, with the merged flags.

    """
    return replace(
        kept,
        subtitled=_merge_flag(kept.subtitled, duplicate.subtitled),
        hard_of_hearing_subtitles=_merge_flag(kept.hard_of_hearing_subtitles, duplicate.hard_of_hearing_subtitles),
        disabled_access=_merge_flag(kept.disabled_access, duplicate.disabled_access),
        audio_description=_merge_flag(kept.audio_description, duplicate.audio_description),
    )


def _showtime_key(entry: dict[str, Any]) -> int | str | None:
    """Return a showtime's ``internalId`` if it can identify duplicates.

    Args:
        entry (dict[str, Any]): The showtime object.

    Returns:
        int | str | None: The id, or ``None`` (the entry is then never merged).

    """
    key = entry.get("internalId")
    if isinstance(key, int) and not isinstance(key, bool):
        return key
    if isinstance(key, str) and key.strip():
        return key
    return None


def _film_ref(movie: dict[str, Any], title: str) -> str | None:
    """Return the film's ``internalId`` as a string, if it is a positive integer or a string of digits.

    Args:
        movie (dict[str, Any]): The ``movie`` object.
        title (str): The film's title, for the debug line.

    Returns:
        str | None: The ref, or ``None``.

    """
    raw = movie.get("internalId")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return str(raw)
    if isinstance(raw, str) and raw.isascii() and raw.isdecimal() and raw.lstrip("0"):
        return raw
    _LOGGER.debug("No usable AlloCiné film id for %r: %r", title, raw)
    return None


@dataclass(slots=True, kw_only=True)
class _ParsedFilm:
    """A film being assembled from one day's pages.

    Attributes:
        title (str): Its title.
        ref (str | None): Its id, if usable.
        details (FilmDetails | None): Its details.
        showtimes (list[Showtime]): Its showtimes, de-duplicated.
        index (dict[int | str, int]): The position in ``showtimes`` of each showtime id.

    """

    title: str
    ref: str | None
    details: FilmDetails | None
    showtimes: list[Showtime] = field(default_factory=list[Showtime])
    index: dict[int | str, int] = field(default_factory=dict[int | str, int])

    def add(self, key: int | str | None, showtime: Showtime) -> None:
        """Add a showtime, merging it into an earlier one with the same id.

        Args:
            key (int | str | None): Its id, or ``None`` to never merge it.
            showtime (Showtime): The showtime.

        """
        if key is not None and (position := self.index.get(key)) is not None:
            self.showtimes[position] = _merge_showtime(self.showtimes[position], showtime)
            return
        if key is not None:
            self.index[key] = len(self.showtimes)
        self.showtimes.append(showtime)


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
        deadline = time.monotonic() + self._call_timeout
        try:
            async with asyncio.timeout(self._call_timeout):
                return await loop.run_in_executor(
                    None, partial(self._fetch_day_sync, normalized, day, deadline=deadline)
                )
        except TimeoutError as err:
            msg = f"Fetching the showtimes of {normalized} for {day.isoformat()} took more than {self._call_timeout} s"
            raise SourceTimeoutError(msg) from err

    def _fetch_day_sync(self, cinema_id: str, day: date, *, deadline: float | None = None) -> DayShowtimes:
        """Fetch and convert one day. Blocking: runs in the executor.

        Args:
            cinema_id (str): The normalized cinema id.
            day (date): The AlloCiné date to fetch.
            deadline (float | None): The ``time.monotonic()`` instant after which no request starts.

        Returns:
            DayShowtimes: The converted day.

        Raises:
            SourceTimeoutError: An HTTP request timed out.
            SourceConnectionError: allocine.fr could not be reached.
            SourceParseError: The response did not have the expected shape.
            ShowtimesError: Any other library failure.

        """
        try:
            if deadline is None:
                deadline = time.monotonic() + self._call_timeout
            pages = self._api.fetch_showtime_pages(cinema_id, day.isoformat(), deadline=deadline)
            return self._convert_day(cinema_id, day, pages)
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

    def _convert_day(self, cinema_id: str, day: date, pages: list[dict[str, Any]]) -> DayShowtimes:  # pylint: disable=too-many-locals
        """Convert the pages of one day into a ``DayShowtimes``.

        The same film (same id) twice in the day becomes one film: its first title and details, the showtimes merged.

        Args:
            cinema_id (str): The normalized cinema id.
            day (date): The AlloCiné date fetched.
            pages (list[dict[str, Any]]): The decoded pages, in order.

        Returns:
            DayShowtimes: The films with at least one showtime, sorted by title.

        Raises:
            SourceParseError: A required part of the data does not have the expected shape.

        """
        time_zone = ZoneInfo(self.source.time_zone)
        films: list[_ParsedFilm] = []
        by_ref: dict[str, _ParsedFilm] = {}
        unknown_keys: set[str] = set()
        noted: set[str] = set()
        non_films = 0
        for page in pages:
            results = _as_list(page.get("results"))
            if results is None:
                msg = f"Expected a list of results, got {type(page.get('results')).__name__}"
                raise SourceParseError(msg)
            for item in results:
                parsed = self._convert_result(item, time_zone, unknown_keys, noted)
                if parsed is None:
                    non_films += 1
                    continue
                target = by_ref.get(parsed.ref) if parsed.ref is not None else None
                if target is None:
                    films.append(parsed)
                    if parsed.ref is not None:
                        by_ref[parsed.ref] = parsed
                    continue
                _LOGGER.debug("The AlloCiné film %s appears twice on %s: merged", parsed.ref, day.isoformat())
                if target.details is None:
                    target.details = parsed.details
                for key, showtime in self._keyed_showtimes(parsed):
                    target.add(key, showtime)
        if non_films:
            _LOGGER.debug("Ignored %d non-film result(s) for %s on %s", non_films, cinema_id, day.isoformat())

        converted = [
            Film(
                title=film.title,
                showtimes=tuple(sorted(film.showtimes, key=lambda showtime: showtime.starts_at)),
                ref=film.ref,
                details=film.details,
            )
            for film in films
            if film.showtimes
        ]
        converted.sort(key=lambda film: film.title.casefold())
        return DayShowtimes(cinema_id=cinema_id, day=day, films=tuple(converted))

    @staticmethod
    def _keyed_showtimes(film: _ParsedFilm) -> list[tuple[int | str | None, Showtime]]:
        """Return a parsed film's showtimes with their ids, to merge them into another occurrence of the film.

        Args:
            film (_ParsedFilm): The later occurrence.

        Returns:
            list[tuple[int | str | None, Showtime]]: Each showtime and its id (``None`` when it has none).

        """
        keys: dict[int, int | str] = {position: key for key, position in film.index.items()}
        return [(keys.get(position), showtime) for position, showtime in enumerate(film.showtimes)]

    def _convert_result(  # pylint: disable=too-many-locals
        self, item: object, time_zone: ZoneInfo, unknown_keys: set[str], noted: set[str] | None = None
    ) -> _ParsedFilm | None:
        """Convert one item of a page's ``results``.

        Args:
            item (object): The ``{"movie", "showtimes"}`` object.
            time_zone (ZoneInfo): The zone of AlloCiné's naive datetimes.
            unknown_keys (set[str]): The unknown showtime list keys already logged for this day; updated.
            noted (set[str] | None): The showtime keys of an unexpected type already logged for this day; updated.

        Returns:
            _ParsedFilm | None: The film (possibly without showtimes), or ``None`` for a non-film event.

        Raises:
            SourceParseError: The item, its title, its showtimes or a start does not have the expected shape.

        """
        result = _as_dict(item)
        if result is None:
            msg = f"Expected a result object, got {type(item).__name__}"
            raise SourceParseError(msg)
        if "movie" in result and result["movie"] is None:
            return None
        movie = _as_dict(result.get("movie"))
        if movie is None:
            msg = "A result has no movie object"
            raise SourceParseError(msg)
        title = movie.get("title")
        if not isinstance(title, str) or not title.strip():
            msg = f"A film has no usable title: {title!r}"
            raise SourceParseError(msg)
        lists = _as_dict(result.get("showtimes"))
        if lists is None:
            msg = f"The film {title!r} has no showtimes object"
            raise SourceParseError(msg)

        try:
            ref = _film_ref(movie, title)
        except _ENRICHMENT_ERRORS as err:
            _LOGGER.debug("No usable AlloCiné film id for %r: %r", title, err)
            ref = None
        try:
            details = _film_details(movie, ref)
        except _ENRICHMENT_ERRORS as err:
            _LOGGER.debug("Ignoring the AlloCiné details of %r: %r", title, err)
            details = None
        languages = movie.get("languages")
        if languages is not None and not isinstance(languages, list):
            _LOGGER.debug("Unreadable AlloCiné languages of %r: %r", title, languages)
        french_only = languages == _FRENCH_ONLY

        film = _ParsedFilm(title=title, ref=ref, details=details)
        for list_key, entries in self._showtime_lists(lists, title, unknown_keys):
            for entry in entries:
                key, showtime = self._convert_showtime(
                    entry,
                    list_key=list_key,
                    french_only=french_only,
                    title=title,
                    time_zone=time_zone,
                    noted=noted,
                )
                film.add(key, showtime)
        return film

    @staticmethod
    def _showtime_lists(lists: dict[str, Any], title: str, unknown_keys: set[str]) -> list[tuple[str, list[Any]]]:
        """Return the showtime lists of a film: the known keys in a fixed order, then any other list.

        Args:
            lists (dict[str, Any]): The film's ``showtimes`` object.
            title (str): The film's title, for the error message.
            unknown_keys (set[str]): The unknown keys already logged for this day; updated.

        Returns:
            list[tuple[str, list[Any]]]: Each list key and its entries (``null`` is an empty list).

        Raises:
            SourceParseError: A known key holds something else than a list or ``null``.

        """
        ordered: list[tuple[str, list[Any]]] = []
        for list_key in _SHOWTIME_LISTS:
            raw = lists.get(list_key)
            if raw is None:
                continue
            entries = _as_list(raw)
            if entries is None:
                msg = f"The showtimes list {list_key!r} of {title!r} is not a list"
                raise SourceParseError(msg)
            ordered.append((list_key, entries))
        for list_key, raw in lists.items():
            if list_key in _SHOWTIME_LISTS or (entries := _as_list(raw)) is None:
                continue
            if list_key not in unknown_keys:
                unknown_keys.add(list_key)
                _LOGGER.debug("Reading the unknown AlloCiné showtimes list %r", list_key)
            ordered.append((list_key, entries))
        return ordered

    def _convert_showtime(  # noqa: PLR0913
        self,
        entry: object,
        *,
        list_key: str,
        french_only: bool,
        title: str,
        time_zone: ZoneInfo,
        noted: set[str] | None = None,
    ) -> tuple[int | str | None, Showtime]:
        """Convert one showtime entry.

        Args:
            entry (object): The showtime object.
            list_key (str): The ``showtimes`` list it came from.
            french_only (bool): Whether the film's languages are exactly ``["FRENCH"]``.
            title (str): The film's title, for the error messages.
            time_zone (ZoneInfo): The zone of AlloCiné's naive datetimes.
            noted (set[str] | None): The showtime keys of an unexpected type already logged for this day; updated.

        Returns:
            tuple[int | str | None, Showtime]: Its id (``None`` if unusable) and the showtime, aware in ``time_zone``.

        Raises:
            SourceParseError: The entry is not an object, or its start is missing or not an ISO datetime.

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

        version = self._convert_version(showtime.get("diffusionVersion"))
        if version is ShowtimeVersion.ORIGINAL and french_only:
            version = ShowtimeVersion.LOCAL
        try:
            extras = _showtime_extras(showtime, list_key, noted)
        except _ENRICHMENT_ERRORS as err:
            _LOGGER.debug("Ignoring the AlloCiné showtime details of %r: %r", title, err)
            extras = {}
        return _showtime_key(showtime), Showtime(starts_at=starts_at, version=version, **extras)

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

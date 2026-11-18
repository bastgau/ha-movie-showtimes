"""The contract every showtimes provider must honour, as a reusable test class.

A provider's test module subclasses ``ProviderContract`` (named ``Test...``) and overrides its fixtures.
"""

# pylint: disable=unidiomatic-typecheck

from collections.abc import Callable
from datetime import date
import re
from typing import ClassVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.client import (
    CinemaInfo,
    CinemaNotFoundError,
    FilmDetails,
    InvalidCinemaRefError,
    Showtime,
    ShowtimeFormats,
    ShowtimesError,
    ShowtimesProvider,
    ShowtimeVersion,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
)
import pytest

from .helpers import no_network

DAY = date(2026, 11, 12)

type Arrange = Callable[[str], None]

_FLAGS = ("subtitled", "hard_of_hearing_subtitles", "disabled_access", "audio_description", "preview", "weekly_outing")


def _is_http_url(value: str | None) -> bool:
    """Return whether an optional URL is absent or an absolute ``http(s)`` URL with a host."""
    if value is None:
        return True
    parts = urlsplit(value)
    return parts.scheme in {"http", "https"} and bool(parts.hostname)


def _check_texts(values: tuple[str, ...]) -> None:
    """Strings in tuples are non-empty and stripped."""
    assert isinstance(values, tuple)
    for value in values:
        assert isinstance(value, str)
        assert value
        assert value == value.strip()


def _check_details(details: FilmDetails | None) -> None:
    """``details`` is ``None`` or a ``FilmDetails`` that is not all-default, with the model's invariants."""
    if details is None:
        return
    assert isinstance(details, FilmDetails)
    assert details != FilmDetails()
    assert details.runtime is None or details.runtime > 0
    assert _is_http_url(details.url)
    assert _is_http_url(details.poster_url)
    for name in ("genres", "countries", "languages", "directors", "cast", "related_tags", "flags"):
        _check_texts(getattr(details, name))


def _check_showtime_extras(showtime: Showtime) -> None:
    """Check that the optional showtime fields keep the model's invariants."""
    for name in _FLAGS:
        assert getattr(showtime, name) is None or type(getattr(showtime, name)) is bool
    assert showtime.formats is None or showtime.formats != ShowtimeFormats()
    assert _is_http_url(showtime.ticket_url)


class ProviderContract:
    """Behaviour shared by every provider; not collected on its own (no ``Test`` prefix)."""

    source_id: ClassVar[str]

    @pytest.fixture
    def provider(self) -> ShowtimesProvider:
        """Return the provider under test."""
        raise NotImplementedError

    @pytest.fixture
    def valid_ref(self) -> str:
        """Return a reference that is not canonical yet."""
        raise NotImplementedError

    @pytest.fixture
    def canonical_id(self) -> str:
        """Return the canonical id ``valid_ref`` normalizes to."""
        raise NotImplementedError

    @pytest.fixture
    def invalid_refs(self) -> list[str]:
        """Return references the provider must reject."""
        raise NotImplementedError

    @pytest.fixture
    def arrange(self) -> Arrange:
        """Return a function making the next calls see one outcome.

        The outcomes are ``ok``, ``empty``, ``not_found``, ``connection``, ``timeout`` and ``malformed``.
        """
        raise NotImplementedError

    def test_source(self, provider: ShowtimesProvider) -> None:
        """The source description is well formed and its example is valid."""
        source = provider.source
        assert re.fullmatch(r"[a-z][a-z0-9]*", source.id)
        assert source.id == self.source_id
        assert source.name
        assert ZoneInfo(source.time_zone)
        assert provider.normalize_cinema_ref(source.ref_example)

    def test_normalize(self, provider: ShowtimesProvider, valid_ref: str, canonical_id: str) -> None:
        """A reference normalizes to the canonical id, idempotently."""
        assert provider.normalize_cinema_ref(valid_ref) == canonical_id
        assert provider.normalize_cinema_ref(canonical_id) == canonical_id

    def test_normalize_rejects(self, provider: ShowtimesProvider, invalid_refs: list[str]) -> None:
        """Every invalid reference raises ``InvalidCinemaRefError``."""
        assert invalid_refs
        for ref in invalid_refs:
            with pytest.raises(InvalidCinemaRefError):
                provider.normalize_cinema_ref(ref)

    def test_normalize_does_no_io(
        self, provider: ShowtimesProvider, valid_ref: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normalizing never opens a connection."""
        monkeypatch.setattr("socket.socket.connect", no_network)
        monkeypatch.setattr("requests.sessions.Session.request", no_network)
        provider.normalize_cinema_ref(valid_ref)

    async def test_day_ok(self, provider: ShowtimesProvider, arrange: Arrange, canonical_id: str) -> None:
        """A normal day is returned in the source's zone, sorted, with no empty film."""
        arrange("ok")

        result = await provider.async_get_day(canonical_id, DAY)

        assert result.cinema_id == canonical_id
        assert result.day == DAY
        assert result.films
        titles = [film.title.casefold() for film in result.films]
        assert titles == sorted(titles)
        for film in result.films:
            assert film.title.strip()
            assert film.showtimes
            starts = [showtime.starts_at for showtime in film.showtimes]
            assert starts == sorted(starts)
            assert film.ref is None or (isinstance(film.ref, str) and film.ref)
            _check_details(film.details)
            for showtime in film.showtimes:
                assert showtime.starts_at.tzinfo is not None
                assert (
                    showtime.starts_at.utcoffset()
                    == showtime.starts_at.astimezone(ZoneInfo(provider.source.time_zone)).utcoffset()
                )
                assert isinstance(showtime.version, ShowtimeVersion)
                _check_showtime_extras(showtime)

    async def test_day_empty(self, provider: ShowtimesProvider, arrange: Arrange, canonical_id: str) -> None:
        """An empty day is valid data."""
        arrange("empty")

        result = await provider.async_get_day(canonical_id, DAY)

        assert result.films == ()

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            ("not_found", CinemaNotFoundError),
            ("connection", SourceConnectionError),
            ("timeout", SourceTimeoutError),
            ("malformed", SourceParseError),
        ],
    )
    async def test_day_errors(
        self,
        provider: ShowtimesProvider,
        arrange: Arrange,
        canonical_id: str,
        kind: str,
        expected: type[ShowtimesError],
    ) -> None:
        """Each failure maps to its own exception, and nothing else escapes."""
        arrange(kind)

        with pytest.raises(ShowtimesError) as excinfo:
            await provider.async_get_day(canonical_id, DAY)

        assert type(excinfo.value) is expected

    async def test_connection_is_not_a_timeout(
        self, provider: ShowtimesProvider, arrange: Arrange, canonical_id: str
    ) -> None:
        """A plain connection failure is not reported as a timeout."""
        arrange("connection")

        with pytest.raises(SourceConnectionError) as excinfo:
            await provider.async_get_day(canonical_id, DAY)

        assert not isinstance(excinfo.value, SourceTimeoutError)

    @pytest.mark.parametrize("kind", ["ok", "empty"])
    async def test_validate(self, provider: ShowtimesProvider, arrange: Arrange, canonical_id: str, kind: str) -> None:
        """An existing cinema validates, even with nothing on."""
        arrange(kind)

        info = await provider.async_validate_cinema(canonical_id, DAY)

        assert isinstance(info, CinemaInfo)
        assert info.cinema_id == canonical_id

    async def test_validate_unknown(self, provider: ShowtimesProvider, arrange: Arrange, canonical_id: str) -> None:
        """An unknown cinema does not validate."""
        arrange("not_found")

        with pytest.raises(CinemaNotFoundError):
            await provider.async_validate_cinema(canonical_id, DAY)

    def test_cinema_url(self, provider: ShowtimesProvider, canonical_id: str) -> None:
        """The cinema page, if any, is an https URL."""
        url = provider.cinema_url(canonical_id)

        assert url is None or url.startswith("https://")

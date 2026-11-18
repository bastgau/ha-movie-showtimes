"""The AlloCiné provider: conversion, error mapping, reference parsing and the library override.

``requests.get`` is replaced everywhere: nothing here reaches allocine.fr. The ``showtimes_*`` fixtures used here are
synthetic (invented, with list keys such as ``dubbed`` / ``local`` that AlloCiné does not have), except
``showtimes_empty_real_shape.json``, reconstructed from the empty day AlloCiné really answers. The contract's ``ok``
day is the real C0159 capture of 2026-11-14 (three pages, trimmed by removing keys only).
"""

# pylint: disable=protected-access,unidiomatic-typecheck,arguments-differ

from datetime import date, timedelta
import inspect
import logging
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any

from allocineAPI.allocineAPI import allocineAPI
from custom_components.movie_showtimes.client import (
    CinemaNotFoundError,
    InvalidCinemaRefError,
    ShowtimesError,
    ShowtimeVersion,
    SourceAccessDeniedError,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
)
from custom_components.movie_showtimes.client.providers import allocine
from custom_components.movie_showtimes.client.providers.allocine import AllocineProvider
import pytest
import requests

from ..helpers import FakeResponse, install_requests, load_json
from ..provider_contract import DAY, Arrange, ProviderContract

CLIENT_DIR = Path(allocine.__file__).parents[1]
URL = "https://www.allocine.fr/seance/salle_gen_csalle=W0124.html"


def _page(name: str) -> FakeResponse:
    """Return a response whose body is a recorded fixture."""
    return FakeResponse.json_body(load_json(name))


class TestAllocineContract(ProviderContract):
    """Run the shared contract against the AlloCiné provider."""

    source_id = "allocine"

    @pytest.fixture
    def provider(self) -> AllocineProvider:
        """Return the provider."""
        return AllocineProvider()

    @pytest.fixture
    def valid_ref(self) -> str:
        """Return a reference to normalize."""
        return f" {URL.lower()} "

    @pytest.fixture
    def canonical_id(self) -> str:
        """Return the canonical id."""
        return "W0124"

    @pytest.fixture
    def invalid_refs(self) -> list[str]:
        """Return invalid references."""
        return ["", "W", "W0124/../x", "https://example.com/seance/salle_gen_csalle=W0124.html"]

    @pytest.fixture
    def arrange(self, monkeypatch: pytest.MonkeyPatch) -> Arrange:
        """Return the function programming ``requests.get``."""

        def _arrange(kind: str) -> None:
            outcomes: dict[str, FakeResponse | BaseException | list[FakeResponse]] = {
                "ok": [_page(f"allocine_C0159_2026-11-14_p{number}.json") for number in (1, 2, 3)],
                "empty": _page("showtimes_empty_real_shape.json"),
                "not_found": FakeResponse(404),
                "connection": requests.ConnectionError("down"),
                "timeout": requests.Timeout("slow"),
                "malformed": FakeResponse(200, "<html>changed</html>"),
            }
            outcome = outcomes[kind]
            install_requests(monkeypatch, *(outcome if isinstance(outcome, list) else [outcome]))

        return _arrange


class TestConversion:
    """What the library returns becomes the client's models."""

    async def test_synthetic_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Synthetic day: films sorted, duplicates and empty films dropped, versions mapped, starts aware in Paris."""
        install_requests(monkeypatch, _page("showtimes_synthetic.json"))

        result = await AllocineProvider().async_get_day("W0124", DAY)

        assert [film.title for film in result.films] == ["amélie", "Le Voyage de Chihiro"]
        chihiro = result.films[1]
        assert [(s.starts_at.isoformat(), s.version) for s in chihiro.showtimes] == [
            ("2026-11-12T14:00:00+01:00", ShowtimeVersion.DUBBED),
            ("2026-11-12T17:15:00+01:00", ShowtimeVersion.LOCAL),
            ("2026-11-12T20:30:00+01:00", ShowtimeVersion.DUBBED),
        ]
        assert result.films[0].showtimes[0].version is ShowtimeVersion.LOCAL

    async def test_synthetic_summer_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Synthetic day: a summer date is at +02:00."""
        install_requests(monkeypatch, _page("showtimes_summer.json"))

        result = await AllocineProvider().async_get_day("W0124", date(2026, 7, 14))

        assert result.films[0].showtimes[0].starts_at.isoformat() == "2026-07-14T21:45:00+02:00"

    async def test_synthetic_aware_start_is_converted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Synthetic day: an aware ``startsAt`` is converted to Paris time."""
        install_requests(monkeypatch, _page("showtimes_aware.json"))

        result = await AllocineProvider().async_get_day("W0124", DAY)

        assert result.films[0].showtimes[0].starts_at.isoformat() == "2026-11-12T20:00:00+01:00"

    async def test_empty_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No showtime at all is valid data (the reconstructed real shape: ``totalPages`` 0, one request)."""
        fake = install_requests(monkeypatch, _page("showtimes_empty_real_shape.json"))

        result = await AllocineProvider().async_get_day("W0124", DAY)

        assert not result.films
        assert result.cinema_id == "W0124"
        assert len(fake.calls) == 1

    async def test_synthetic_pagination(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Synthetic two pages: every page is requested and the results merged."""
        fake = install_requests(monkeypatch, _page("showtimes_two_pages_p1.json"), _page("showtimes_two_pages_p2.json"))

        result = await AllocineProvider().async_get_day("W0124", DAY)

        assert [url.rsplit("/", 3)[-3:] for url, _ in fake.calls] == [
            ["d-2026-11-12", "p-1", ""],
            ["d-2026-11-12", "p-2", ""],
        ]
        assert [film.title for film in result.films] == ["Film A", "Film B"]

    async def test_synthetic_null_movie_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Synthetic day: a non-film event (``movie: null``) is removed and the other films are kept."""
        install_requests(monkeypatch, _page("showtimes_null_movie.json"))

        with caplog.at_level(logging.DEBUG, logger=allocine.__name__):
            result = await AllocineProvider().async_get_day("W0124", DAY)

        assert [film.title for film in result.films] == ["Film C"]
        assert "Ignored 1 non-film" in caplog.text

    async def test_synthetic_versions_and_single_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Synthetic day: unknown versions are kept as ``UNKNOWN`` and warned about once per value."""
        install_requests(monkeypatch, _page("showtimes_original.json"))
        provider = AllocineProvider()

        with caplog.at_level(logging.WARNING, logger=allocine.__name__):
            first = await provider.async_get_day("W0124", DAY)
            await provider.async_get_day("W0124", DAY)

        assert [s.version for s in first.films[0].showtimes] == [
            ShowtimeVersion.ORIGINAL,
            ShowtimeVersion.UNKNOWN,
            ShowtimeVersion.UNKNOWN,
        ]
        warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert "'SIGNED'" in warnings[0].getMessage()
        assert "None" in warnings[1].getMessage()

    @pytest.mark.parametrize(
        ("pages", "message"),
        [
            ([{"results": {"not": "a list"}}], "Expected a list of results"),
            ([{"results": ["film"]}], "Expected a result object"),
            ([{"results": [{"movie": {"title": ""}, "showtimes": {}}]}], "no usable title"),
            ([{"results": [{"movie": {"title": None}, "showtimes": {}}]}], "no usable title"),
            ([{"results": [{"movie": {"title": "A"}, "showtimes": "x"}]}], "no showtimes object"),
            ([{"results": [{"movie": {"title": "A"}, "showtimes": {"original": ["x"]}}]}], "is not an object"),
            (
                [{"results": [{"movie": {"title": "A"}, "showtimes": {"original": [{"diffusionVersion": "LOCAL"}]}}]}],
                "has no start",
            ),
            (
                [{"results": [{"movie": {"title": "A"}, "showtimes": {"original": [{"startsAt": "soon"}]}}]}],
                "invalid start",
            ),
        ],
    )
    def test_malformed_conversion(self, pages: list[dict[str, Any]], message: str) -> None:
        """A required part of a page with an unexpected shape is a parse error."""
        with pytest.raises(SourceParseError, match=message):
            AllocineProvider()._convert_day("W0124", DAY, pages)

    def test_film_without_showtimes_is_dropped(self) -> None:
        """A film with an empty list of showtimes is left out."""
        pages = [{"results": [{"movie": {"title": "A"}, "showtimes": {"original": []}}]}]

        result = AllocineProvider()._convert_day("W0124", DAY, pages)

        assert not result.films


class TestRequest:
    """What is sent to allocine.fr."""

    async def test_only_the_user_agent_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The User-Agent is the only header sent (synthetic day)."""
        fake = install_requests(monkeypatch, _page("showtimes_synthetic.json"))

        await AllocineProvider().async_get_day("W0124", DAY)

        assert fake.calls
        for _, kwargs in fake.calls:
            assert kwargs["headers"] == {"User-Agent": allocine.USER_AGENT}
        assert allocine.USER_AGENT == "ha-movie-showtimes/0.1"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("https://x.test/a/b", "https://x.test/a/b/"),
            ("https://x.test/a/b/", "https://x.test/a/b/"),
            ("https://x.test/a/b?q=1", "https://x.test/a/b/?q=1"),
            ("https://x.test/a/b/?q=1", "https://x.test/a/b/?q=1"),
        ],
    )
    def test_trailing_slash(self, monkeypatch: pytest.MonkeyPatch, path: str, expected: str) -> None:
        """A missing trailing slash is added to the path, the query string and the parameters untouched."""
        fake = install_requests(monkeypatch, _page("showtimes_synthetic.json"))
        params = {"page": 2}

        allocine._AllocineAPIWithTimeout(connect_timeout=1, read_timeout=1)._get_json_request(path, params)

        assert fake.calls[0][0] == expected
        assert fake.calls[0][1]["params"] == params

    async def test_requested_urls_end_with_a_slash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The URLs the library builds end up canonical (synthetic day)."""
        fake = install_requests(monkeypatch, _page("showtimes_synthetic.json"))

        await AllocineProvider().async_get_day("W0124", DAY)

        assert all(url.endswith("/") for url, _ in fake.calls)


class TestErrors:
    """Library and HTTP failures become the client's exceptions, chained."""

    @pytest.mark.parametrize("status", [500, 502])
    async def test_http_status(self, monkeypatch: pytest.MonkeyPatch, status: int) -> None:
        """An unexpected status is a plain connection error."""
        install_requests(monkeypatch, FakeResponse(status))

        with pytest.raises(SourceConnectionError, match=str(status)) as excinfo:
            await AllocineProvider().async_get_day("W0124", DAY)

        assert not isinstance(excinfo.value, SourceTimeoutError | SourceAccessDeniedError)

    @pytest.mark.parametrize("status", [403, 429])
    async def test_access_denied(self, monkeypatch: pytest.MonkeyPatch, status: int) -> None:
        """HTTP 403 and 429 are an access refusal carrying the status."""
        install_requests(monkeypatch, FakeResponse(status))

        with pytest.raises(SourceAccessDeniedError) as excinfo:
            await AllocineProvider().async_get_day("W0124", DAY)

        assert excinfo.value.status_code == status
        assert str(excinfo.value) == f"allocine.fr refused the request (HTTP {status})"
        assert isinstance(excinfo.value, SourceConnectionError)

    def test_access_denied_without_status(self) -> None:
        """The status is optional."""
        assert SourceAccessDeniedError("refused").status_code is None
        assert issubclass(SourceAccessDeniedError, SourceConnectionError)

    async def test_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 404 is an unknown cinema."""
        install_requests(monkeypatch, FakeResponse(404))

        with pytest.raises(CinemaNotFoundError):
            await AllocineProvider().async_get_day("W0124", DAY)

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (requests.Timeout("slow"), SourceTimeoutError),
            (requests.exceptions.ReadTimeout("slow"), SourceTimeoutError),
            (requests.ConnectionError("down"), SourceConnectionError),
            (requests.exceptions.InvalidURL("odd"), SourceConnectionError),
            (RuntimeError("library bug"), ShowtimesError),
        ],
    )
    async def test_exceptions_are_mapped_and_chained(
        self, monkeypatch: pytest.MonkeyPatch, error: Exception, expected: type[ShowtimesError]
    ) -> None:
        """Each library exception maps to one of ours, keeping the original as the cause."""
        install_requests(monkeypatch, error)

        with pytest.raises(ShowtimesError) as excinfo:
            await AllocineProvider().async_get_day("W0124", DAY)

        assert type(excinfo.value) is expected
        assert excinfo.value.__cause__ is error

    @pytest.mark.parametrize(
        "response",
        [
            FakeResponse(200, "<html>Cloudflare</html>"),
            FakeResponse(200, "[1, 2]"),
            FakeResponse.json_body({"results": []}),
            FakeResponse.json_body({"pagination": {"page": 1, "totalPages": 1}}),
            FakeResponse.json_body({"pagination": {"page": 1, "totalPages": 1}, "results": ["oops"]}),
            FakeResponse.json_body(
                {"pagination": {"page": 1, "totalPages": 1}, "results": [{"movie": {}, "showtimes": {}}]}
            ),
            _page("showtimes_bad_datetime.json"),
        ],
        ids=["not_json", "not_object", "no_pagination", "no_results", "bad_item", "no_title", "bad_datetime"],
    )
    async def test_malformed_response(self, monkeypatch: pytest.MonkeyPatch, response: FakeResponse) -> None:
        """A page that is not what the site used to return is a parse error, never a crash."""
        install_requests(monkeypatch, response)

        with pytest.raises(SourceParseError):
            await AllocineProvider().async_get_day("W0124", DAY)

    async def test_non_json_cause(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The decoding error is chained."""
        install_requests(monkeypatch, FakeResponse(200, "<html>"))

        with pytest.raises(SourceParseError) as excinfo:
            await AllocineProvider().async_get_day("W0124", DAY)

        assert isinstance(excinfo.value.__cause__, ValueError)


class TestExecution:
    """Timeouts and threads."""

    async def test_request_timeouts_are_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every HTTP request carries a connect and a read timeout."""
        fake = install_requests(monkeypatch, _page("showtimes_empty_real_shape.json"))

        await AllocineProvider().async_get_day("W0124", DAY)
        await AllocineProvider(connect_timeout=1.5, read_timeout=2.5).async_get_day("W0124", DAY)

        assert [kwargs["timeout"] for _, kwargs in fake.calls] == [(10.0, 20.0), (1.5, 2.5)]

    async def test_runs_off_the_event_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The blocking call runs in a worker thread."""
        threads: list[int] = []

        def _get(url: str, **kwargs: Any) -> FakeResponse:
            threads.append(threading.get_ident())
            return _page("showtimes_empty_real_shape.json")

        monkeypatch.setattr(requests, "get", _get)

        await AllocineProvider().async_get_day("W0124", DAY)

        assert threads
        assert threads[0] != threading.get_ident()

    async def test_call_timeout_backstop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A call that never returns is cut by the asyncio timeout."""
        release = threading.Event()

        def _get(url: str, **kwargs: Any) -> FakeResponse:
            release.wait(5)
            return _page("showtimes_empty_real_shape.json")

        monkeypatch.setattr(requests, "get", _get)

        try:
            with pytest.raises(SourceTimeoutError) as excinfo:
                await AllocineProvider(call_timeout=0.05).async_get_day("W0124", DAY)
        finally:
            release.set()

        assert isinstance(excinfo.value.__cause__, TimeoutError)


class TestReferences:
    """Cinema ids and page URLs."""

    @pytest.mark.parametrize(
        "raw",
        [
            " w0124 ",
            "W0124",
            URL,
            URL.replace("https", "http"),
            URL.replace("www.", ""),
            URL.replace("www.", "m."),
            URL.replace("www.allocine", "WWW.AlloCine"),
            "www.allocine.fr/seance/salle_gen_csalle=W0124.html",
            "allocine.fr/seance/salle_gen_csalle=W0124.html",
            f"{URL[:-5]}.html/",
            f"{URL}?utm_source=x",
            f"{URL}#shwt_date=2026-11-12",
            URL.replace("W0124", "w0124"),
            f"  {URL}  ",
            URL.replace("allocine.fr", "allocine.fr:443"),
            URL.replace("https://", "HTTPS://"),
        ],
    )
    def test_accepted(self, raw: str) -> None:
        """Every accepted form gives the same canonical id."""
        assert AllocineProvider().normalize_cinema_ref(raw) == "W0124"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "W0124/../x",
            "é",
            "W",
            "ABCDEFGHIJK",
            "W\uff10\uff11\uff12\uff14",
            "W\u0131",
            "https://example.com/seance/salle_gen_csalle=W0124.html",
            "https://allocine.fr.evil.com/seance/salle_gen_csalle=W0124.html",
            "ftp://www.allocine.fr/seance/salle_gen_csalle=W0124.html",
            "https://www.allocine.fr/film/fichefilm_gen_cfilm=12345.html",
            "https://www.allocine.fr/seance/salle_gen_csalle=.html",
            "https://www.allocine.fr/seance/salle_gen_csalle=W0124.htm",
            "https://www.allocine.fr/seance/salle_gen_csalle=W01/24.html",
            "https://www.allocine.fr/seance/salle_gen_csalle=ABCDEFGHIJK.html",
            "https://www.allocine.fr/",
            "https://user:pass@www.allocine.fr/seance/salle_gen_csalle=W0124.html",
            "https://user@www.allocine.fr/seance/salle_gen_csalle=W0124.html",
            "https://www.allocine.fr:8443/seance/salle_gen_csalle=W0124.html",
            "http://www.allocine.fr:443/seance/salle_gen_csalle=W0124.html",
            "https://www.allocine.fr:99999/seance/salle_gen_csalle=W0124.html",
            "https://[::1/seance/salle_gen_csalle=W0124.html",
        ],
    )
    def test_rejected(self, raw: str) -> None:
        """Anything else is an invalid reference."""
        with pytest.raises(InvalidCinemaRefError):
            AllocineProvider().normalize_cinema_ref(raw)

    async def test_bad_id_raises_before_any_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A malformed id never reaches the network."""
        fake = install_requests(monkeypatch, _page("showtimes_empty_real_shape.json"))

        with pytest.raises(InvalidCinemaRefError):
            await AllocineProvider().async_get_day("not an id", DAY)

        assert not fake.calls

    async def test_url_is_accepted_by_get_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A page URL is normalized, and the canonical id is requested and returned."""
        fake = install_requests(monkeypatch, _page("showtimes_empty_real_shape.json"))

        result = await AllocineProvider().async_get_day(URL.lower(), DAY)

        assert result.cinema_id == "W0124"
        assert "theater-W0124/" in fake.calls[0][0]

    def test_cinema_url(self) -> None:
        """The cinema page is the one the user can paste back."""
        provider = AllocineProvider()

        assert provider.cinema_url("W0124") == URL
        assert provider.normalize_cinema_ref(provider.cinema_url("W0124") or "") == "W0124"
        assert provider.normalize_cinema_ref(provider.source.url_example) == "W0124"


class TestLibraryContract:
    """The override and the boundary."""

    def test_override_signature_matches_the_library(self) -> None:
        """A library bump renaming, reordering or re-defaulting a parameter fails here."""
        library = inspect.signature(allocineAPI._get_json_request).parameters
        ours = inspect.signature(allocine._AllocineAPIWithTimeout._get_json_request).parameters

        assert list(ours) == list(library)
        for name, parameter in library.items():
            assert ours[name].kind == parameter.kind
            assert ours[name].default == parameter.default

    def test_library_is_pinned_to_the_tested_version(self) -> None:
        """The pin in the manifest is the version these tests ran against."""
        from importlib.metadata import version  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        assert version("allocine-seances") == "0.0.14"

    def test_client_does_not_import_home_assistant(self) -> None:
        """Importing every client module, with the parent packages stubbed, loads no Home Assistant module."""
        script = """
import importlib, pkgutil, sys, types
directory = sys.argv[1]
parent = types.ModuleType("custom_components")
parent.__path__ = [directory + "/../.."]
sys.modules["custom_components"] = parent
integration = types.ModuleType("custom_components.movie_showtimes")
integration.__path__ = [directory + "/.."]
sys.modules["custom_components.movie_showtimes"] = integration
client = importlib.import_module("custom_components.movie_showtimes.client")
names = [m.name for m in pkgutil.walk_packages(client.__path__, client.__name__ + ".")]
for name in names:
    importlib.import_module(name)
loaded = sorted(m for m in sys.modules if m == "homeassistant" or m.startswith("homeassistant."))
print(len(names))
assert not loaded, loaded
"""
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-I", "-c", script, str(CLIENT_DIR)], capture_output=True, text=True, check=False
        )

        assert result.returncode == 0, result.stderr
        assert int(result.stdout) >= 6


def test_start_on_the_morning_of_the_spring_clock_change() -> None:
    """A start before the 02:00 jump of the last Sunday of March is still at +01:00."""
    provider = AllocineProvider()
    showtime = {"startsAt": "2026-03-29T01:30:00", "diffusionVersion": "LOCAL"}
    pages = [{"results": [{"movie": {"title": "A"}, "showtimes": {"multiple": [showtime]}}]}]

    result = provider._convert_day("W0124", date(2026, 3, 29), pages)

    assert result.films[0].showtimes[0].starts_at.utcoffset() == timedelta(hours=1)

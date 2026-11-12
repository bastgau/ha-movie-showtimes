"""The AlloCiné provider on three real days, trimmed by removing keys only (design §9.1).

Fixtures: ``allocine_C0159_2026-11-14_p1..p3.json`` (a UGC cinema, 3 pages), ``allocine_W7520_2026-11-11_p1..p2.json``
(a Pathé cinema, 2 pages) and ``allocine_W0124_2026-11-12.json`` (*La Gradiva* alone). They were captured outside the
repository with the integration's own User-Agent; ``requests.get`` is replaced, nothing reaches allocine.fr.
"""

# pylint: disable=protected-access

from collections import Counter
from collections.abc import Iterator
from datetime import date
import inspect
import threading
from typing import Any

from allocineAPI.allocineAPI import URLs, allocineAPI
from custom_components.movie_showtimes.client import DayShowtimes, Film, Showtime, ShowtimeFormats, ShowtimeVersion
from custom_components.movie_showtimes.client.providers import allocine
from custom_components.movie_showtimes.client.providers.allocine import AllocineProvider
import pytest
import requests

from tests import reference_films

from ..helpers import FakeResponse, install_requests, load_json

C0159_DAY = date(2026, 11, 14)
W7520_DAY = date(2026, 11, 11)
W0124_DAY = date(2026, 11, 12)
C0159_PAGES = [f"allocine_C0159_2026-11-14_p{number}.json" for number in (1, 2, 3)]
W7520_PAGES = [f"allocine_W7520_2026-11-11_p{number}.json" for number in (1, 2)]
W0124_PAGES = ["allocine_W0124_2026-11-12.json"]
BASE = "https://www.allocine.fr/_/showtimes"


def _responses(names: list[str]) -> list[FakeResponse]:
    """Return one response per real page."""
    return [FakeResponse.json_body(load_json(name)) for name in names]


def _showtimes(day: DayShowtimes) -> list[Showtime]:
    """Return every showtime of a day."""
    return [showtime for film in day.films for showtime in film.showtimes]


def _film(day: DayShowtimes, title: str) -> Film:
    """Return the film of a day with this title."""
    return next(film for film in day.films if film.title == title)


def _raw_entries(names: list[str]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield ``(title, list key, showtime entry)`` for every raw showtime of the pages."""
    for name in names:
        for result in load_json(name)["results"]:
            for list_key, entries in result["showtimes"].items():
                for entry in entries:
                    yield result["movie"]["title"], list_key, entry


def _urls(entry: dict[str, Any], provider: str) -> list[str]:
    """Return the ticketing URLs of one provider of a raw showtime."""
    return [url for item in entry["data"]["ticketing"] if item["provider"] == provider for url in item["urls"]]


@pytest.fixture(autouse=True)
def _library_day_calls_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_showtime`` and ``get_movies`` are never called by a day fetch (D25): both raise if they are."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        msg = "get_showtime / get_movies must not be called"
        raise AssertionError(msg)

    monkeypatch.setattr(allocineAPI, "get_showtime", _forbidden)
    monkeypatch.setattr(allocineAPI, "get_movies", _forbidden)


@pytest.fixture(scope="module", name="c0159")
def c0159_fixture() -> DayShowtimes:
    """Return the real C0159 day, parsed."""
    return AllocineProvider()._convert_day("C0159", C0159_DAY, [load_json(name) for name in C0159_PAGES])


@pytest.fixture(scope="module", name="w7520")
def w7520_fixture() -> DayShowtimes:
    """Return the real W7520 day, parsed."""
    return AllocineProvider()._convert_day("W7520", W7520_DAY, [load_json(name) for name in W7520_PAGES])


class TestRealPagination:
    """One request per page, in order, with only the User-Agent."""

    @pytest.mark.parametrize(
        ("cinema_id", "day", "pages", "films", "showtimes"),
        [("C0159", C0159_DAY, C0159_PAGES, 36, 161), ("W7520", W7520_DAY, W7520_PAGES, 26, 66)],
    )
    async def test_every_page_once(  # pylint: disable=too-many-arguments
        self,
        monkeypatch: pytest.MonkeyPatch,
        cinema_id: str,
        day: date,
        pages: list[str],
        films: int,
        showtimes: int,
    ) -> None:
        """C0159: exactly 3 calls; W7520: exactly 2; the string page numbers are accepted."""
        fake = install_requests(monkeypatch, *_responses(pages))

        result = await AllocineProvider().async_get_day(cinema_id, day)

        assert [url for url, _ in fake.calls] == [
            f"{BASE}/theater-{cinema_id}/d-{day.isoformat()}/p-{number}/" for number in range(1, len(pages) + 1)
        ]
        for _, kwargs in fake.calls:
            assert kwargs["headers"] == {"User-Agent": allocine.USER_AGENT}
            assert kwargs["params"] is None
        assert len(result.films) == films
        assert len(_showtimes(result)) == showtimes

    def test_two_concurrent_days_keep_no_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two day fetches running at once on one provider, in two threads, each return their own day."""
        barrier = threading.Barrier(2, timeout=10)
        documents = {
            "C0159": [load_json(name) for name in C0159_PAGES],
            "W7520": [load_json(name) for name in W7520_PAGES],
        }

        def _get(url: str, **_kwargs: Any) -> FakeResponse:
            cinema_id = url.split("theater-")[1].split("/", maxsplit=1)[0]
            number = int(url.rstrip("/").rsplit("p-", 1)[1])
            if number <= len(W7520_PAGES):
                barrier.wait()  # Both threads are in the middle of their pagination at once.
            return FakeResponse.json_body(documents[cinema_id][number - 1])

        monkeypatch.setattr(requests, "get", _get)
        provider = AllocineProvider()
        results: dict[str, DayShowtimes] = {}

        def _run(cinema_id: str, day: date) -> None:
            results[cinema_id] = provider._fetch_day_sync(cinema_id, day)

        threads = [
            threading.Thread(target=_run, args=("C0159", C0159_DAY)),
            threading.Thread(target=_run, args=("W7520", W7520_DAY)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)

        assert not barrier.broken
        assert results["C0159"].cinema_id == "C0159"
        assert results["W7520"].cinema_id == "W7520"
        assert len(results["C0159"].films) == 36
        assert len(results["W7520"].films) == 26
        assert {showtime.starts_at.date() for showtime in _showtimes(results["W7520"])} == {W7520_DAY}
        assert not vars(provider._api).keys() - {"_timeout"}


class TestShowtimeUrlGuard:
    """The library's public URL builder is pinned (design §4.2)."""

    def test_static_method_signature(self) -> None:
        """A library bump renaming, reordering or re-defaulting a parameter fails here."""
        assert isinstance(inspect.getattr_static(URLs, "showtime_url"), staticmethod)
        parameters = inspect.signature(URLs.showtime_url).parameters
        assert list(parameters) == ["id_cinema", "date_str", "page"]
        for parameter in parameters.values():
            assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            assert parameter.default is inspect.Parameter.empty

    def test_format(self) -> None:
        """The URL format is the one the fixtures were captured with (the override adds the slash)."""
        assert (
            URLs.showtime_url("C0159", "2026-11-14", 3)
            == "https://www.allocine.fr/_/showtimes/theater-C0159/d-2026-11-14/p-3"
        )


class TestGoldenCounts:
    """The counts of design §9.2, on the real days."""

    def test_c0159(self, c0159: DayShowtimes) -> None:
        """UGC: VOST via the Localization.Subtitle.French tag, VF as DUBBED, PMR on 145, default booking links."""
        showtimes = _showtimes(c0159)
        assert Counter(showtime.version for showtime in showtimes) == {
            ShowtimeVersion.ORIGINAL: 64,
            ShowtimeVersion.DUBBED: 97,
        }
        assert sum(showtime.subtitled is True for showtime in showtimes) == 64
        assert all(showtime.subtitled is (showtime.version is ShowtimeVersion.ORIGINAL) for showtime in showtimes)
        assert Counter(showtime.disabled_access for showtime in showtimes) == {True: 145, False: 16}
        assert not any(showtime.hard_of_hearing_subtitles for showtime in showtimes)
        assert all(showtime.audio_description is False for showtime in showtimes)
        assert all((showtime.ticket_url or "").startswith("https://www.ugc.fr/") for showtime in showtimes)
        assert {showtime.formats for showtime in showtimes} == {ShowtimeFormats(projection=("DIGITAL",))}
        assert sorted(film.title for film in c0159.films if film.details and film.details.runtime is None) == [
            "Ce qui nous mène à toi",
            "Les Yeux Verts",
        ]
        assert [film.title for film in c0159.films if film.details and film.details.certificate is None] == [
            "Comment braquer une banque"
        ]
        assert all(film.ref and film.details for film in c0159.films)

    def test_c0159_subtitles_come_from_the_tag_only(self, c0159: DayShowtimes) -> None:
        """Every C0159 VOST is in ``original`` with ``Localization.Subtitle.French``, never ``*_st`` nor ``Subtitled``."""
        original = [entry for _, key, entry in _raw_entries(C0159_PAGES) if entry["diffusionVersion"] == "ORIGINAL"]
        assert len(original) == 64
        assert {key for _, key, entry in _raw_entries(C0159_PAGES) if entry["diffusionVersion"] == "ORIGINAL"} == {
            "original"
        }
        for entry in original:
            assert "Localization.Subtitle.French" in entry["tags"]
            assert "Showtime.Accessibility.Subtitled" not in entry["tags"]
        assert len(_showtimes(c0159)) == 161

    def test_w7520(self, w7520: DayShowtimes) -> None:
        """Pathé: VOST in original_st, LOCAL French films, PMR on 48, Greta on 16, real formats."""
        showtimes = _showtimes(w7520)
        assert Counter(showtime.version for showtime in showtimes) == {
            ShowtimeVersion.ORIGINAL: 19,
            ShowtimeVersion.DUBBED: 34,
            ShowtimeVersion.LOCAL: 13,
        }
        assert sum(showtime.subtitled is True for showtime in showtimes) == 19
        assert Counter(showtime.disabled_access for showtime in showtimes) == {True: 48, False: 18}
        assert not any(showtime.hard_of_hearing_subtitles for showtime in showtimes)
        assert all((showtime.ticket_url or "").startswith("https://s.pathe.fr/fr/") for showtime in showtimes)
        codes = Counter(
            (kind, code)
            for showtime in showtimes
            if showtime.formats
            for kind in ("projection", "experience", "picture", "sound", "comfort")
            for code in getattr(showtime.formats, kind)
        )
        assert codes == {
            ("projection", "DIGITAL"): 61,
            ("projection", "IMAX"): 3,
            ("projection", "F_3D"): 3,
            ("experience", "SCREEN_X"): 3,
            ("experience", "PLF"): 6,
            ("experience", "E_4DX"): 3,
        }
        assert sum(showtime.formats == ShowtimeFormats(projection=("F_3D", "IMAX")) for showtime in showtimes) == 1
        assert [film.title for film in w7520.films if film.details and film.details.runtime is None] == ["Kraken"]
        assert sorted(film.title for film in w7520.films if film.details and film.details.certificate is None) == [
            "Comment braquer une banque",
            "Peppa fête Noël",
        ]

    def test_w7520_audio_description(self, w7520: DayShowtimes) -> None:
        """The Greta tag gives ``audio_description`` on exactly 16 showtimes of 6 films; the relay code adds nothing."""
        by_film = Counter(
            film.title for film in w7520.films for showtime in film.showtimes if showtime.audio_description is True
        )
        assert by_film == {
            "Clayface": 6,
            "L'île des souvenirs": 4,
            "Malfaisante": 3,
            "Ducobu et le fantôme de Saint-Potache": 1,
            "Karma": 1,
            "Les Misérables": 1,
        }
        assert all(showtime.audio_description is not None for showtime in _showtimes(w7520))
        greta = [entry for _, _, entry in _raw_entries(W7520_PAGES) if "GRETA" in _urls(entry, "relay")[0]]
        assert len(greta) == 16

    @pytest.mark.parametrize(("pages", "expected"), [(C0159_PAGES, 4), (W7520_PAGES, 5)])
    def test_cast_from_the_original_voice(self, pages: list[str], expected: int) -> None:
        """Animated films have ``actor: null`` and their voice in ``originalVoiceActor``: it is read."""
        day = AllocineProvider()._convert_day("X1", C0159_DAY, [load_json(name) for name in pages])
        voiced = 0
        for name in pages:
            for result in load_json(name)["results"]:
                nodes = [edge["node"] for edge in result["movie"]["cast"]["edges"]]
                if not any(node["actor"] is None and node["originalVoiceActor"] for node in nodes):
                    continue
                voiced += 1
                first = nodes[0]["actor"] or nodes[0]["originalVoiceActor"]
                details = _film(day, result["movie"]["title"]).details
                assert details is not None
                assert details.cast[0] == " ".join(part for part in (first["firstName"], first["lastName"]) if part)
        assert voiced == expected

    def test_other_facts(self, c0159: DayShowtimes, w7520: DayShowtimes) -> None:
        """Dune's release among 54, Ramayana without visa nor synopsis, Peppa without rating."""
        dune = _film(c0159, "Dune").details
        assert dune is not None
        assert (dune.release_date, dune.visa_number, dune.certificate) == ("2026-11-11", "155420", "Tout public")
        ramayana = _film(w7520, "Ramayana : L'avènement d'une légende").details
        assert ramayana is not None
        assert ramayana.visa_number is None
        assert ramayana.release_date == "2026-11-06"
        assert ramayana.synopsis is None
        assert ramayana.synopsis_full
        assert ramayana.runtime == 195
        peppa = _film(w7520, "Peppa fête Noël").details
        assert peppa is not None
        assert peppa.user_rating is None
        assert peppa.runtime == 49

    def test_dune_has_54_releases(self) -> None:
        """The release choice runs on the complete list (not trimmed)."""
        dune = next(
            result["movie"]
            for name in W7520_PAGES
            for result in load_json(name)["results"]
            if result["movie"]["title"] == "Dune"
        )
        assert len(dune["releases"]) == 54
        assert dune["releases"][0]["visaNumber"] in {None, ""}

    def test_non_boolean_flags_are_ignored(self, c0159: DayShowtimes) -> None:
        """``isClubApproved: []`` and ``hasClubNews: []`` are not flags."""
        raw = load_json(C0159_PAGES[0])["results"][0]["movie"]["flags"]
        assert [] in raw.values()
        for film in c0159.films:
            assert film.details is not None
            assert "isClubApproved" not in film.details.flags
            assert "hasClubNews" not in film.details.flags


class TestGoldenFilms:
    """Four complete films of design §6.1, written out in ``tests/reference_films.py``."""

    @pytest.mark.parametrize(
        ("which", "title", "expected"),
        [
            ("c0159", "Comment braquer une banque", reference_films.COMMENT_BRAQUER),
            ("c0159", "Le Corset", reference_films.LE_CORSET),
            ("w7520", "Dune", reference_films.DUNE),
            ("w7520", "Ramayana : L'avènement d'une légende", reference_films.RAMAYANA),
        ],
    )
    def test_film(self, request: pytest.FixtureRequest, which: str, title: str, expected: Film) -> None:
        """The parsed film equals the reference, field by field."""
        day: DayShowtimes = request.getfixturevalue(which)

        assert _film(day, title) == expected

    def test_la_gradiva(self) -> None:
        """W0124: the French rule makes an ORIGINAL showtime of a ["FRENCH"] film LOCAL; the relay link is verbatim."""
        day = AllocineProvider()._convert_day("W0124", W0124_DAY, [load_json(name) for name in W0124_PAGES])
        (entry,) = (entry for _, _, entry in _raw_entries(W0124_PAGES))

        (film,) = day.films
        (showtime,) = film.showtimes
        assert film.title == "La Gradiva"
        assert film.ref == "318225"
        assert entry["diffusionVersion"] == "ORIGINAL"
        assert showtime.version is ShowtimeVersion.LOCAL
        assert showtime.subtitled is True
        assert showtime.disabled_access is True
        assert showtime.ticket_url == _urls(entry, "relay")[0]
        assert " " in (showtime.ticket_url or "")
        assert film.details is not None
        assert film.details.runtime == 145
        assert film.details.user_rating is not None
        assert film.details.user_rating.count == 1610


class TestRealAccessibilityAndBooking:
    """PMR, the relay code and the booking link against the raw showtimes."""

    def test_pmr_follows_service_and_ignores_accessible(self) -> None:
        """``Accessible`` without PMR stays False (W7520), PMR without ``Accessible`` is True (C0159, Scrooge)."""
        for pages, cinema_id in ((C0159_PAGES, "C0159"), (W7520_PAGES, "W7520")):
            day = AllocineProvider()._convert_day(cinema_id, C0159_DAY, [load_json(name) for name in pages])
            by_url = {showtime.ticket_url: showtime for showtime in _showtimes(day)}
            seen: set[tuple[bool, bool]] = set()
            for _, _, entry in _raw_entries(pages):
                showtime = by_url[_urls(entry, "default")[0]]
                accessible = "Showtime.Accessibility.Accessible" in entry["tags"]
                pmr = entry["service"] is not None and "DISABLED_ACCESS" in entry["service"]
                assert showtime.disabled_access is pmr
                seen.add((accessible, pmr))
            assert (False, True) in seen if cinema_id == "C0159" else (True, False) in seen

    def test_relay_code_never_sets_a_flag(self, c0159: DayShowtimes) -> None:
        """C0159's relay ``code=`` says SME and AUDIO on most showtimes; no flag follows it."""
        codes = [_urls(entry, "relay")[0].split("code=")[-1] for _, _, entry in _raw_entries(C0159_PAGES)]
        assert sum("SME" in code for code in codes) == 131
        assert sum("AUDIO" in code for code in codes) == 137
        for showtime in _showtimes(c0159):
            assert showtime.hard_of_hearing_subtitles is False
            assert showtime.audio_description is False

    @pytest.mark.parametrize(
        ("pages", "providers"), [(C0159_PAGES, {"relay", "default"}), (W7520_PAGES, {"en", "relay", "default"})]
    )
    def test_default_is_preferred(self, pages: list[str], providers: set[str]) -> None:
        """``default`` wins over ``relay`` (C0159) and over ``en`` and ``relay`` (W7520)."""
        day = AllocineProvider()._convert_day("X1", C0159_DAY, [load_json(name) for name in pages])
        expected = set()
        for _, _, entry in _raw_entries(pages):
            assert {item["provider"] for item in entry["data"]["ticketing"]} == providers
            expected.add(_urls(entry, "default")[0])
        assert {showtime.ticket_url for showtime in _showtimes(day)} == expected

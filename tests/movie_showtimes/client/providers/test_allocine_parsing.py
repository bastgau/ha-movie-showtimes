"""The AlloCiné parsing rules on INVENTED data (design §4, §9.2).

Everything here is invented: the inline pages, ``showtimes_versions.json`` (what no capture has: SME, a plain VO,
duplicates across lists, unknown keys…), ``showtimes_paged_p1/p2.json`` (one film on two pages) and
``showtimes_enrichment_broken.json`` (one film per broken optional field). AlloCiné never sent an SME showtime in
the captures: the SME cases are invented only. ``requests.get`` is replaced, nothing reaches allocine.fr.
"""

# pylint: disable=protected-access,too-many-lines

from collections.abc import Callable
import copy
from datetime import date
import logging
from typing import Any

from custom_components.movie_showtimes.client import (
    DayShowtimes,
    Film,
    FilmDetails,
    Rating,
    Showtime,
    ShowtimeFormats,
    ShowtimeVersion,
    SourceParseError,
)
from custom_components.movie_showtimes.client.providers import allocine
from custom_components.movie_showtimes.client.providers.allocine import AllocineProvider, parse_runtime
import pytest

from ..helpers import FakeResponse, install_requests, load_json
from ..provider_contract import DAY

SUBTITLED = "Showtime.Accessibility.Subtitled"
PMR_TAG = "Theater.Service.DisabledAccess"
GRETA = "Showtime.Accessibility.Greta"
ACCESSIBLE = "Showtime.Accessibility.Accessible"
LOGGER = allocine.__name__


def _entry(**fields: Any) -> dict[str, Any]:
    """Return an invented showtime entry, at 20:00 on ``DAY``, ``ORIGINAL`` unless given."""
    return {"startsAt": "2026-11-12T20:00:00", "diffusionVersion": "ORIGINAL", **fields}


def _result(lists: dict[str, Any], *, title: str = "Invented", **movie: Any) -> dict[str, Any]:
    """Return an invented result: a ``movie`` object and its showtime lists."""
    return {"movie": {"title": title, **movie}, "showtimes": lists}


def _day(*results: dict[str, Any], provider: AllocineProvider | None = None) -> DayShowtimes:
    """Convert one invented page."""
    return (provider or AllocineProvider())._convert_day("W0124", DAY, [{"results": list(results)}])


def _one(list_key: str = "original", **fields: Any) -> Showtime:
    """Convert a page with a single showtime and return it."""
    (film,) = _day(_result({list_key: [_entry(**fields)]}, languages=["ENGLISH"])).films
    (showtime,) = film.showtimes
    return showtime


def _details(**movie: Any) -> FilmDetails | None:
    """Convert a page with a single film with these ``movie`` fields and return its details."""
    (film,) = _day(_result({"original": [_entry()]}, **movie)).films
    return film.details


def _page(results: list[Any], page: object = 1, total: object = 1) -> FakeResponse:
    """Return an invented showtimes page."""
    return FakeResponse.json_body({"results": results, "pagination": {"page": page, "totalPages": total}})


def _debug_messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the DEBUG messages of the provider's logger."""
    return [
        record.getMessage() for record in caplog.records if record.name == LOGGER and record.levelno == logging.DEBUG
    ]


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return the records at WARNING or above."""
    return [record for record in caplog.records if record.levelno >= logging.WARNING]


ONE_FILM = [_result({"original": [_entry()]})]


class TestPaginationEdgeCases:
    """Our own pagination (design §4.2), on invented pages."""

    @pytest.mark.parametrize("total", [0, 1, "1"])
    async def test_single_request(self, monkeypatch: pytest.MonkeyPatch, total: object) -> None:
        """``totalPages`` 0 or 1: exactly one request."""
        fake = install_requests(monkeypatch, _page(ONE_FILM if total else [], total=total))

        await AllocineProvider().async_get_day("W0124", DAY)

        assert len(fake.calls) == 1

    async def test_page_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A second page answering ``"1"`` is an error, not a loop."""
        fake = install_requests(monkeypatch, _page(ONE_FILM, "1", 3), _page(ONE_FILM, "1", 3))

        with pytest.raises(SourceParseError, match="Asked for page 2"):
            await AllocineProvider().async_get_day("W0124", DAY)

        assert len(fake.calls) == 2

    async def test_first_page_is_not_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The first page must say it is page 1."""
        install_requests(monkeypatch, _page(ONE_FILM, 2, 2))

        with pytest.raises(SourceParseError, match="Asked for page 1"):
            await AllocineProvider().async_get_day("W0124", DAY)

    @pytest.mark.parametrize(
        "document",
        [
            {"results": []},
            {"results": [], "pagination": None},
            {"results": [], "pagination": [1, 1]},
            {"results": [], "pagination": {"page": 1, "totalPages": "x"}},
            {"results": [], "pagination": {"page": 1, "totalPages": -1}},
            {"results": [], "pagination": {"page": 1, "totalPages": True}},
            {"results": [], "pagination": {"page": 1, "totalPages": 1.0}},
            {"results": [], "pagination": {"page": 1}},
            {"results": [], "pagination": {"page": "\u0661", "totalPages": 1}},
            {"results": [], "pagination": {"page": "-1", "totalPages": 1}},
        ],
        ids=["missing", "null", "list", "x", "negative", "bool", "float", "no_total", "arabic_digit", "minus_string"],
    )
    async def test_unreadable_pagination(self, monkeypatch: pytest.MonkeyPatch, document: dict[str, Any]) -> None:
        """Pagination missing, not an object, or a number that is not a non-negative integer: parse error."""
        fake = install_requests(monkeypatch, FakeResponse.json_body(document))

        with pytest.raises(SourceParseError):
            await AllocineProvider().async_get_day("W0124", DAY)

        assert len(fake.calls) == 1

    async def test_implausible_page_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``totalPages: 21``: parse error after exactly one request."""
        fake = install_requests(monkeypatch, _page(ONE_FILM, "1", 21))

        with pytest.raises(SourceParseError, match="Implausible pagination"):
            await AllocineProvider().async_get_day("W0124", DAY)

        assert len(fake.calls) == 1

    async def test_twenty_pages_are_fetched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """20 pages is the limit, still fetched, one request each."""
        pages = [_page([_result({"original": [_entry()]}, title=f"Film {n:02d}")], str(n), 20) for n in range(1, 21)]
        fake = install_requests(monkeypatch, *pages)

        result = await AllocineProvider().async_get_day("W0124", DAY)

        assert len(fake.calls) == 20
        assert len(result.films) == 20
        assert fake.calls[-1][0].endswith("/p-20/")

    async def test_paged_fixture_merges_the_same_film(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invented: one film (same id) on two pages is one film, first title and details, showtimes OR-merged."""
        fake = install_requests(
            monkeypatch,
            FakeResponse.json_body(load_json("showtimes_paged_p1.json")),
            FakeResponse.json_body(load_json("showtimes_paged_p2.json")),
        )

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            result = await AllocineProvider().async_get_day("W0124", DAY)

        assert len(fake.calls) == 2
        merged = next(film for film in result.films if film.ref == "900100")
        assert merged.title == "Invented Paged Film"
        assert merged.details is not None
        assert merged.details.original_title == "First Occurrence"
        assert [showtime.starts_at.strftime("%H:%M") for showtime in merged.showtimes] == ["14:00", "18:00"]
        first = merged.showtimes[0]
        assert (first.subtitled, first.disabled_access) == (True, True)
        assert any("appears twice" in message for message in _debug_messages(caplog))
        # Films without an id are never merged, even with the same title; entries without an id are kept.
        no_id = [film for film in result.films if film.ref is None]
        assert [film.title for film in no_id] == ["Invented No Id", "Invented No Id"]
        assert [film.showtimes[0].starts_at.hour for film in no_id] == [15, 16]


class TestListsAndDeduplication:
    """``showtimes_versions.json`` (invented) and inline cases for the six lists (design §4.3)."""

    @pytest.fixture
    def versions(self, caplog: pytest.LogCaptureFixture) -> Callable[[], DayShowtimes]:
        """Return a function converting the invented versions day, logs captured at DEBUG."""
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        return lambda: AllocineProvider()._convert_day("W0124", DAY, [load_json("showtimes_versions.json")])

    @staticmethod
    def _film(day: DayShowtimes, title: str) -> Film:
        """Return a film of the day."""
        return next(film for film in day.films if film.title == title)

    def test_duplicates_and_sme(self, versions: Callable[[], DayShowtimes]) -> None:
        """Duplicates across lists merge with OR; SME entries are SME, never subtitled; a plain VO is a VO."""
        day = versions()
        film = self._film(day, "Invented Lists")
        rows = [
            (s.starts_at.strftime("%H:%M"), s.version, s.subtitled, s.hard_of_hearing_subtitles) for s in film.showtimes
        ]
        assert rows == [
            ("10:00", ShowtimeVersion.ORIGINAL, True, False),  # original + original_st: one, subtitled
            ("11:00", ShowtimeVersion.ORIGINAL, False, False),  # the plain VO
            ("12:00", ShowtimeVersion.ORIGINAL, True, True),  # original_st + original_sme: VOST and SME
            ("13:00", ShowtimeVersion.ORIGINAL, False, True),  # original_sme with the Subtitled tag: still not
            ("14:00", ShowtimeVersion.DUBBED, False, True),  # multiple_sme
        ]

    def test_versions(self, versions: Callable[[], DayShowtimes], caplog: pytest.LogCaptureFixture) -> None:
        """A co-production stays ORIGINAL; an unknown version is UNKNOWN with one warning."""
        day = versions()
        assert self._film(day, "Invented Co-production").showtimes[0].version is ShowtimeVersion.ORIGINAL
        assert self._film(day, "Invented Unknown Version").showtimes[0].version is ShowtimeVersion.UNKNOWN
        assert ["'SIGNED'" in record.getMessage() for record in _warnings(caplog)] == [True]

    def test_unknown_and_null_lists(
        self, versions: Callable[[], DayShowtimes], caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown list keys are read (subtitled only with a tag, SME unknown); a null list is empty."""
        day = versions()
        film = self._film(day, "Invented Unknown Lists")
        assert [(s.subtitled, s.hard_of_hearing_subtitles) for s in film.showtimes] == [(True, None), (None, None)]
        messages = _debug_messages(caplog)
        assert sum("unknown AlloCiné showtimes list 'imax_st'" in message for message in messages) == 1
        assert sum("unknown AlloCiné showtimes list 'imax'" in message for message in messages) == 1
        assert not any("'notes'" in message for message in messages)

    def test_non_films_and_empty_films(
        self, versions: Callable[[], DayShowtimes], caplog: pytest.LogCaptureFixture
    ) -> None:
        """``movie: null`` is skipped with one debug line; a film whose lists are all empty is dropped."""
        day = versions()
        titles = [film.title for film in day.films]
        assert "Invented Empty Lists" not in titles
        assert len(titles) == 5
        assert sum("Ignored 1 non-film result(s)" in message for message in _debug_messages(caplog)) == 1

    def test_service_shapes(self, versions: Callable[[], DayShowtimes]) -> None:
        """``service`` missing or a string: PMR unknown."""
        day = versions()
        film = self._film(day, "Invented Service Shapes")
        assert [showtime.disabled_access for showtime in film.showtimes] == [None, None]

    def test_known_key_with_a_string(self) -> None:
        """A known list key holding a string means the shape changed: parse error."""
        with pytest.raises(SourceParseError, match="is not a list"):
            _day(_result({"original_st": "oops"}))

    def test_entries_without_usable_id_are_never_merged(self) -> None:
        """No ``internalId`` (or a blank one): kept, even at the same minute; string ids merge."""
        day = _day(
            _result(
                {
                    "original": [_entry(), _entry(internalId=" "), _entry(internalId="a1"), _entry(internalId=True)],
                    "original_st": [_entry(internalId="a1")],
                }
            )
        )
        (film,) = day.films
        assert len(film.showtimes) == 4
        assert sum(showtime.subtitled is True for showtime in film.showtimes) == 1

    @pytest.mark.parametrize(
        ("flags", "expected"),
        [((True, None), True), ((None, False), False), ((None, None), None), ((False, True), True)],
    )
    def test_or_merge_of_the_flags(self, flags: tuple[bool | None, bool | None], expected: bool | None) -> None:
        """``True`` if any is ``True``, else ``False`` if any is ``False``, else ``None``."""
        start = allocine.datetime(2026, 11, 12, 20, tzinfo=allocine.ZoneInfo("Europe/Paris"))
        kept, duplicate = (
            Showtime(starts_at=start, version=ShowtimeVersion.ORIGINAL, disabled_access=flag, audio_description=flag)
            for flag in flags
        )

        merged = allocine._merge_showtime(kept, duplicate)

        assert merged.disabled_access is expected
        assert merged.audio_description is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(133392, "133392"), ("133392", "133392"), (0, None), (-5, None), (True, None), ("0", None), ("abc", None)],
    )
    def test_film_ref(self, raw: object, expected: str | None) -> None:
        """The film id is a positive int or a string of digits."""
        (film,) = _day(_result({"original": [_entry()]}, internalId=raw)).films

        assert film.ref == expected
        assert (film.details is not None and film.details.url is not None) is (expected is not None)


class TestVersionsAndSubtitles:
    """Design §4.4, each rule on its own (invented entries)."""

    @pytest.mark.parametrize(
        ("list_key", "tags", "expected"),
        [
            ("original_st", [], True),
            ("multiple_st", [], True),
            ("original", [SUBTITLED], True),
            ("original", ["Localization.Subtitle.French"], True),
            ("original", ["Localization.Subtitle.English"], True),
            ("original", ["Localization.Version.Original"], False),
            ("multiple", [], False),
            ("original_sme", [SUBTITLED, "Localization.Subtitle.French"], False),
            ("multiple_sme", [SUBTITLED], False),
            ("elsewhere", [], None),
        ],
    )
    def test_each_subtitle_signal_alone(self, list_key: str, tags: list[str], expected: bool | None) -> None:
        """The list, the Subtitled tag and a Localization.Subtitle.* tag each set ``subtitled``; SME never does."""
        assert _one(list_key, tags=tags).subtitled is expected

    @pytest.mark.parametrize(
        ("languages", "version", "expected"),
        [
            (["FRENCH"], "ORIGINAL", ShowtimeVersion.LOCAL),
            (["FRENCH", "ITALIAN"], "ORIGINAL", ShowtimeVersion.ORIGINAL),
            (["FRENCH", "FRENCH"], "ORIGINAL", ShowtimeVersion.ORIGINAL),
            ("FRENCH", "ORIGINAL", ShowtimeVersion.ORIGINAL),
            (None, "ORIGINAL", ShowtimeVersion.ORIGINAL),
            (["FRENCH"], "DUBBED", ShowtimeVersion.DUBBED),
            (["ENGLISH"], "DUBBED", ShowtimeVersion.DUBBED),
            (["FRENCH"], "LOCAL", ShowtimeVersion.LOCAL),
            (["ENGLISH"], "LOCAL", ShowtimeVersion.LOCAL),
        ],
    )
    def test_french_rule(self, languages: object, version: str, expected: ShowtimeVersion) -> None:
        """Only an ORIGINAL showtime of a film whose languages are exactly ["FRENCH"] becomes LOCAL."""
        (film,) = _day(_result({"original": [_entry(diffusionVersion=version)]}, languages=languages)).films

        assert film.showtimes[0].version is expected

    def test_french_rule_without_languages(self) -> None:
        """``languages`` absent: the rule is off."""
        (film,) = _day(_result({"original": [_entry()]})).films

        assert film.showtimes[0].version is ShowtimeVersion.ORIGINAL

    def test_unreadable_languages_only_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """A string ``languages`` disables the rule with a debug line, nothing louder."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _day(_result({"original": [_entry()]}, languages="FRENCH"))

        assert any("Unreadable AlloCiné languages" in message for message in _debug_messages(caplog))
        assert not _warnings(caplog)


class TestAccessibility:
    """PMR, SME and audio description (design §4.7), invented entries."""

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"service": ["DISABLED_ACCESS"]}, True),
            ({"service": ["OTHER", "DISABLED_ACCESS"]}, True),
            ({"tags": [PMR_TAG]}, True),
            ({"service": None, "tags": [PMR_TAG]}, True),
            ({"service": "DISABLED_ACCESS", "tags": [PMR_TAG]}, True),
            ({"service": None}, False),
            ({"service": []}, False),
            ({"service": None, "tags": [ACCESSIBLE]}, False),
            ({}, None),
            ({"tags": [ACCESSIBLE]}, None),
            ({"service": 42}, None),
            ({"service": "DISABLED_ACCESS"}, None),
        ],
    )
    def test_pmr(self, fields: dict[str, Any], expected: bool | None) -> None:
        """PMR from ``service`` or the tag; ``null`` service is False; missing is None; ``Accessible`` is ignored."""
        assert _one(**fields).disabled_access is expected

    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"tags": [GRETA]}, True),
            ({"tags": ["Localization.Version.Original"]}, False),
            ({"tags": []}, False),
            ({"tags": None}, None),
            ({}, None),
            ({"tags": "Showtime.Accessibility.Greta"}, None),
            (
                {
                    "tags": [],
                    "data": {
                        "ticketing": [
                            {
                                "type": "DESKTOP",
                                "provider": "relay",
                                "urls": ["https://relay.example.invalid/x?code=GRETA; AUDIO; SME"],
                            }
                        ]
                    },
                },
                False,
            ),
        ],
    )
    def test_audio_description(self, fields: dict[str, Any], expected: bool | None) -> None:
        """The Greta tag only; the relay URL's ``code=`` has no effect."""
        assert _one(**fields).audio_description is expected

    @pytest.mark.parametrize(
        ("list_key", "expected"),
        [("original_sme", True), ("multiple_sme", True), ("original", False), ("multiple_st", False), ("x", None)],
    )
    def test_sme_from_the_lists_only(self, list_key: str, expected: bool | None) -> None:
        """SME comes from the ``*_sme`` lists only (invented: never seen in a capture)."""
        assert _one(list_key, tags=["Showtime.Accessibility.SME"]).hard_of_hearing_subtitles is expected


def _ticketing(*entries: dict[str, Any]) -> dict[str, Any]:
    """Return a showtime ``data`` object with these ticketing entries."""
    return {"ticketing": list(entries)}


def _ticket(provider: str, *urls: object, kind: str = "DESKTOP") -> dict[str, Any]:
    """Return one ticketing entry."""
    return {"type": kind, "provider": provider, "urls": list(urls)}


class TestBookingLink:
    """One DESKTOP link per showtime (design §4.6), invented entries; never an exception."""

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (
                _ticketing(_ticket("relay", "https://r.example/1"), _ticket("default", "https://d.example/1")),
                "https://d.example/1",
            ),
            (
                _ticketing(_ticket("en", "https://en.example/1"), _ticket("relay", "https://r.example/1")),
                "https://r.example/1",
            ),
            (_ticketing(_ticket("en", "https://en.example/1")), "https://en.example/1"),
            (
                _ticketing(_ticket("x", "https://x.example/1"), _ticket("y", "https://y.example/1")),
                "https://x.example/1",
            ),
            (_ticketing(_ticket("default"), _ticket("relay", "https://r.example/1")), "https://r.example/1"),
            (_ticketing(_ticket("default", "/booking/1", "https://d.example/2")), "https://d.example/2"),
            (_ticketing(_ticket("default", "javascript:alert(1)", 42, "http://[::1")), None),
            (_ticketing(_ticket("default", "https://d.example/1", kind="MOBILE")), None),
            (_ticketing({"type": "DESKTOP", "provider": "default", "urls": "https://d.example/1"}), None),
            (_ticketing("not an entry"), None),
            ({"ticketing": None}, None),
            ({"ticketing": "x"}, None),
            ({}, None),
            (None, None),
        ],
        ids=[
            "default_over_relay",
            "relay_over_en",
            "only_en",
            "other_providers_in_order",
            "default_without_urls",
            "relative_skipped",
            "no_valid_url",
            "no_desktop",
            "urls_not_a_list",
            "entry_not_an_object",
            "ticketing_null",
            "ticketing_string",
            "no_ticketing",
            "data_null",
        ],
    )
    def test_choice(self, data: object, expected: str | None) -> None:
        """``default``, else ``relay``, else any other DESKTOP provider in order; first valid http(s) URL."""
        assert _one(data=data).ticket_url == expected

    def test_raw_spaces_are_kept(self) -> None:
        """A URL is never re-encoded."""
        url = "https://relay.example/t?perft=20:30&code=VO; SUBTITLE"

        assert _one(data=_ticketing(_ticket("relay", url))).ticket_url == url


class TestRuntime:  # pylint: disable=too-few-public-methods
    """``parse_runtime``: the table of design §4.5."""

    @pytest.mark.parametrize(
        ("raw", "expected", "logged"),
        [
            ("2h 25min", 145, False),
            ("3h 15min", 195, False),
            ("2h 01min", 121, False),
            ("2h 00min", 120, False),
            ("0h 49min", 49, False),
            ("0h 00min", None, False),
            ("2h25min", 145, False),
            (" 2h  25min ", 145, False),
            ("45min", 45, False),
            ("2h", 120, False),
            (None, None, False),
            ("", None, False),
            ("   ", None, False),
            ("1h30", None, True),
            ("145", None, True),
            ("abc", None, True),
            (145, None, True),
            (2.5, None, True),
            ([], None, True),
        ],
    )
    def test_table(self, caplog: pytest.LogCaptureFixture, raw: object, expected: int | None, logged: bool) -> None:
        """Minutes > 0, or ``None``; a debug line only for an unreadable value."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            assert parse_runtime(raw) == expected

        assert bool(_debug_messages(caplog)) is logged


class TestReleasesAndFields:
    """The release choice and the other extractors (design §4.6), invented movies."""

    @staticmethod
    def _release(**fields: Any) -> dict[str, Any]:
        """Return an invented release."""
        return {"releaseDate": {"date": "2026-01-01"}, "certificate": {"label": "Tout public"}, **fields}

    def test_first_release_with_a_visa_gives_all_three(self) -> None:
        """Date, visa and certificate come from the same release, the first with a visa (an int is converted)."""
        details = _details(
            releases=[
                self._release(visaNumber=""),
                {"releaseDate": {"date": "2026-11-11"}, "certificate": {"code": "U"}, "visaNumber": 155420},
                self._release(visaNumber="999"),
            ]
        )

        assert details is not None
        assert (details.release_date, details.visa_number, details.certificate) == ("2026-11-11", "155420", "U")

    def test_without_any_visa_each_field_from_the_first_that_has_it(self) -> None:
        """No visa: each field comes from the first release that has it."""
        details = _details(
            releases=[
                "junk",
                {"releaseDate": None},
                {"releaseDate": {"date": "2026-11-06"}},
                self._release(visaNumber=True),
            ]
        )

        assert details is not None
        assert (details.release_date, details.visa_number, details.certificate) == ("2026-11-06", None, "Tout public")

    @pytest.mark.parametrize("releases", [[], None, {"visaNumber": "1"}])
    def test_no_usable_releases(self, releases: object) -> None:
        """``releases`` empty, null or not a list: all three ``None`` (the case that crashes ``get_movies``)."""
        details = _details(releases=releases, originalTitle="X")

        assert details is not None
        assert (details.release_date, details.visa_number, details.certificate) == (None, None, None)

    def test_every_field(self) -> None:
        """A complete invented movie: every extractor, duplicates removed, order kept."""
        details = _details(
            internalId=42,
            type="FEATURE_FILM",
            originalTitle=" Original ",
            data={"productionYear": 1999},
            runtime="1h 05min",
            genres=[{"translate": "Drame"}, {"translate": "Drame"}, {"translate": " "}, "x", {"translate": "Action"}],
            countries=[{"localizedName": "Italie", "name": "Italy"}, {"name": "France"}, {"localizedName": None}],
            languages=["ITALIAN", 3, " ", "ITALIAN"],
            credits=[
                {"person": {"firstName": "Ann", "lastName": "Example"}, "position": {"name": "DIRECTOR"}},
                {"person": {"firstName": "Ann", "lastName": "Example"}, "position": {"name": "DIRECTOR"}},
                {"person": {"firstName": None, "lastName": "Solo"}, "position": {"name": " WRITER "}},
                {"person": {"firstName": "No", "lastName": "Role"}},
                {"person": {"firstName": " ", "lastName": ""}, "position": {"name": "DIRECTOR"}},
                {"person": "x", "position": {"name": "DIRECTOR"}},
                "junk",
            ],
            cast={
                "edges": [
                    {"node": {"actor": {"firstName": "Bob", "lastName": "Sample"}}},
                    {"node": {"actor": None, "originalVoiceActor": None, "voiceActor": {"lastName": "Voice"}}},
                    {"node": {"actor": None}},
                    {"node": None},
                    "junk",
                ]
            },
            relatedTags=[{"name": "Tag"}, {"data": {}}],
            poster={"url": "http://img.example/p.jpg"},
            synopsis=" ",
            synopsisFull=" <p>Full</p> ",
            stats={
                "userRating": {"score": 4, "count": None},
                "userReview": {"count": 0},
                "pressReview": None,
                "wantToSeeCount": 3,
                "metric": {"hits": 5, "sessions": True},
            },
            customFlags={"isPremiere": True, "weeklyOuting": "yes"},
            flags={"hasTrailer": False, "isPlayingNow": True, "isClubApproved": [], "hasNews": 1},
        )

        assert details == FilmDetails(
            url="https://www.allocine.fr/film/fichefilm_gen_cfilm=42.html",
            film_type="FEATURE_FILM",
            original_title="Original",
            year=1999,
            runtime=65,
            genres=("Drame", "Action"),
            countries=("Italie", "France"),
            languages=("ITALIAN",),
            directors=("Ann Example",),
            poster_url="http://img.example/p.jpg",
            synopsis_full="<p>Full</p>",
            cast=("Bob Sample", "Voice"),
            credits=(
                allocine.Credit(name="Ann Example", role="DIRECTOR"),
                allocine.Credit(name="Solo", role="WRITER"),
            ),
            related_tags=("Tag",),
            user_rating=Rating(score=4.0),
            user_review_count=0,
            want_to_see_count=3,
            hits=5,
            premiere=True,
            has_trailer=False,
            flags=("isPlayingNow",),
        )

    @pytest.mark.parametrize("year", [1869, 2101, True])
    def test_implausible_year(self, year: object) -> None:
        """The production year must be an int in 1870 to 2100."""
        details = _details(data={"productionYear": year}, originalTitle="X")

        assert details is not None
        assert details.year is None

    def test_no_details_at_all(self) -> None:
        """A movie with nothing readable but its title has ``details=None``, ``ref=None``."""
        (film,) = _day(_result({"original": [_entry()]})).films

        assert film.ref is None
        assert film.details is None

    def test_formats(self) -> None:
        """Codes verbatim; ``null`` is empty; all five empty is ``None``."""
        showtime = _one(projection=["F_3D", "IMAX"], experience=["SCREEN_X", "PLF"], picture=None, sound=[])

        assert showtime.formats == ShowtimeFormats(projection=("F_3D", "IMAX"), experience=("SCREEN_X", "PLF"))
        assert _one(projection=None, comfort=[]).formats is None

    @pytest.mark.parametrize(("raw", "expected"), [(True, True), (False, False), ("true", None), (None, None)])
    def test_showtime_booleans(self, raw: object, expected: bool | None) -> None:
        """Only real ``bool`` values count."""
        showtime = _one(isPreview=raw, isWeeklyMovieOuting=raw)

        assert showtime.preview is expected
        assert showtime.weekly_outing is expected

    def test_editorial_reviews_are_ignored(self, caplog: pytest.LogCaptureFixture) -> None:
        """A non-empty ``editorialReviews`` changes nothing in the model and logs nothing."""
        page = load_json("allocine_W0124_2026-11-12.json")
        changed = copy.deepcopy(page)
        changed["results"][0]["movie"]["editorialReviews"] = [{"title": "Invented review", "rating": 5}]
        provider = AllocineProvider()

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            before = provider._convert_day("W0124", DAY, [page])
            logged = len(caplog.records)
            after = provider._convert_day("W0124", DAY, [changed])

        assert after == before
        assert len(caplog.records) == 2 * logged


def _broken_film(slug: str) -> tuple[DayShowtimes, Film]:
    """Convert the one film of ``showtimes_enrichment_broken.json`` named ``Broken <slug>``."""
    page = load_json("showtimes_enrichment_broken.json")
    page["results"] = [result for result in page["results"] if result["movie"]["title"] == f"Broken {slug}"]
    assert len(page["results"]) == 1
    day = AllocineProvider()._convert_day("W0124", DAY, [page])
    return day, day.films[0]


def _d(getter: Callable[[FilmDetails], object]) -> Callable[[Film], object]:
    """Read a details field of a film."""
    return lambda film: getter(film.details) if film.details is not None else None


def _s(getter: Callable[[Showtime], object]) -> Callable[[Film], object]:
    """Read a field of the film's only showtime."""
    return lambda film: getter(film.showtimes[0])


BROKEN: list[tuple[str, Callable[[Film], object], object, bool]] = [
    ("runtime int", _d(lambda d: d.runtime), None, True),
    ("genres not a list", _d(lambda d: d.genres), (), True),
    ("genre without translate", _d(lambda d: d.genres), (), True),
    ("stats null", _d(lambda d: (d.user_rating, d.press_rating, d.hits, d.want_to_see_count)), (None,) * 4, False),
    ("userRating score string", _d(lambda d: d.user_rating), None, True),
    ("userRating score bool", _d(lambda d: d.user_rating), None, True),
    ("userRating score 7", _d(lambda d: d.user_rating), None, True),
    ("hits negative", _d(lambda d: d.hits), None, True),
    ("hits string", _d(lambda d: d.hits), None, True),
    ("poster null", _d(lambda d: d.poster_url), None, False),
    ("poster javascript", _d(lambda d: d.poster_url), None, True),
    ("certificate null", _d(lambda d: d.certificate), None, False),
    ("type int", _d(lambda d: d.film_type), None, True),
    ("data null", _d(lambda d: d.year), None, False),
    ("productionYear string", _d(lambda d: d.year), None, True),
    ("synopsisFull object", _d(lambda d: d.synopsis_full), None, True),
    ("cast missing", _d(lambda d: d.cast), (), False),
    ("cast edges null", _d(lambda d: d.cast), (), False),
    ("credit without person", _d(lambda d: (d.credits, d.directors)), ((), ()), False),
    ("relatedTags object", _d(lambda d: d.related_tags), (), True),
    ("customFlags null", _d(lambda d: (d.premiere, d.weekly_outing)), (None, None), False),
    ("flags missing", _d(lambda d: (d.flags, d.has_trailer)), ((), None), False),
    ("flags list", _d(lambda d: (d.flags, d.has_trailer)), ((), None), True),
    ("projection string", _s(lambda s: s.formats), None, True),
    ("comfort object", _s(lambda s: s.formats and s.formats.comfort), (), True),
    ("service int", _s(lambda s: s.disabled_access), None, True),
    ("tags null", _s(lambda s: (s.subtitled, s.audio_description)), (True, None), False),
    ("internalId missing", lambda film: (film.ref, film.details and film.details.url), (None, None), True),
    ("internalId letters", lambda film: (film.ref, film.details and film.details.url), (None, None), True),
]


class TestEnrichmentNeverFailsTheDay:
    """D28: one odd optional field never invalidates the day (invented ``showtimes_enrichment_broken.json``)."""

    @pytest.mark.parametrize(
        ("slug", "read", "expected"),
        [(slug, read, value) for slug, read, value, _ in BROKEN],
        ids=[b[0] for b in BROKEN],
    )
    def test_field_is_dropped(
        self, caplog: pytest.LogCaptureFixture, slug: str, read: Callable[[Film], object], expected: object
    ) -> None:
        """The day parses, the showtime is there, the field is ``None`` / ``()``, no warning."""
        with caplog.at_level(logging.DEBUG):
            day, film = _broken_film(slug)

        assert len(day.films) == 1
        assert len(film.showtimes) == 1
        assert read(film) == expected
        assert not _warnings(caplog)

    @pytest.mark.parametrize(
        ("slug", "logged"), [(slug, logged) for slug, _, _, logged in BROKEN], ids=[b[0] for b in BROKEN]
    )
    def test_logging_rule(self, caplog: pytest.LogCaptureFixture, slug: str, logged: bool) -> None:
        """An unexpected type leaves exactly one DEBUG record; ``null`` or a missing key leaves none; never a warning."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _broken_film(slug)

        assert len(_debug_messages(caplog)) == (1 if logged else 0)
        assert not _warnings(caplog)

    def test_the_other_fields_survive(self) -> None:
        """Only the broken field goes: the rest of the film is read (control: one broken field, many kept)."""
        _, film = _broken_film("runtime int")

        assert film.details is not None
        assert film.details.genres == ("Drame",)
        assert film.showtimes[0].ticket_url == "https://example.invalid/book"
        assert film.showtimes[0].audio_description is True

    def test_details_that_raise(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A ``_film_details`` that raises gives ``details=None`` and a debug line; the day is fine."""

        def _boom(*_args: object) -> FilmDetails:
            msg = "boom"
            raise KeyError(msg)

        monkeypatch.setattr(allocine, "_film_details", _boom)

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _, film = _broken_film("runtime int")

        assert film.details is None
        assert film.ref is not None
        assert any("Ignoring the AlloCiné details" in message for message in _debug_messages(caplog))
        assert not _warnings(caplog)

    def test_showtime_extras_that_raise(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A ``_showtime_extras`` that raises gives a showtime with every optional field unknown."""

        def _boom(*_args: object) -> dict[str, Any]:
            msg = "boom"
            raise TypeError(msg)

        monkeypatch.setattr(allocine, "_showtime_extras", _boom)

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _, film = _broken_film("runtime int")

        showtime = film.showtimes[0]
        assert showtime == Showtime(starts_at=showtime.starts_at, version=ShowtimeVersion.ORIGINAL)
        assert any("showtime details" in message for message in _debug_messages(caplog))


class TestStillFatal:
    """Only the required fields of design §4.3 fail a day."""

    @pytest.mark.parametrize(
        ("page", "message"),
        [
            ({"pagination": {}}, "Expected a list of results"),
            ({"results": [{"movie": {"title": "  "}, "showtimes": {}}]}, "no usable title"),
            ({"results": [{"movie": {"title": "A"}, "showtimes": None}]}, "no showtimes object"),
            ({"results": [{"movie": {"title": "A"}}]}, "no showtimes object"),
            ({"results": [{"movie": "A", "showtimes": {}}]}, "no movie object"),
            ({"results": [{"showtimes": {}}]}, "no movie object"),
            ({"results": [_result({"original": [{"diffusionVersion": "ORIGINAL"}]})]}, "has no start"),
            ({"results": [_result({"original": [{"startsAt": 20}]})]}, "has no start"),
        ],
    )
    def test_parse_error(self, page: dict[str, Any], message: str) -> None:
        """A missing ``results``, blank title, null ``showtimes`` or missing ``startsAt`` is a parse error."""
        with pytest.raises(SourceParseError, match=message):
            AllocineProvider()._convert_day("W0124", DAY, [page])

    async def test_key_error_in_conversion_is_a_parse_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unexpected ``KeyError`` while converting maps to ``SourceParseError``, chained."""

        def _boom(*_args: object) -> DayShowtimes:
            msg = "results"
            raise KeyError(msg)

        monkeypatch.setattr(AllocineProvider, "_convert_day", _boom)
        install_requests(monkeypatch, _page(ONE_FILM))

        with pytest.raises(SourceParseError) as excinfo:
            await AllocineProvider().async_get_day("W0124", date(2026, 11, 12))

        assert isinstance(excinfo.value.__cause__, KeyError)


class _Clock:  # pylint: disable=too-few-public-methods
    """A ``time.monotonic`` stand-in, moved by the test."""

    def __init__(self, now: float) -> None:
        """Start the clock at ``now``."""
        self.now = now

    def __call__(self) -> float:
        """Return the current instant."""
        return self.now


class TestDeadline:
    """The whole-call deadline is checked before every page request (invented pages)."""

    def test_slow_first_page_stops_the_pagination(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Page 1 ends after the deadline: ``SourceTimeoutError`` and no request for page 2."""
        clock = _Clock(0.0)
        monkeypatch.setattr(allocine.time, "monotonic", clock)
        fake = install_requests(monkeypatch, _page(ONE_FILM, "1", 2))

        def _slow_get(url: str, **kwargs: Any) -> FakeResponse:
            response = fake(url, **kwargs)
            clock.now = 100.0
            return response

        monkeypatch.setattr(allocine.requests, "get", _slow_get)

        with pytest.raises(allocine.SourceTimeoutError, match="page 2"):
            AllocineProvider()._fetch_day_sync("W0124", DAY, deadline=50.0)

        assert len(fake.calls) == 1

    def test_deadline_already_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A deadline already behind us: no request at all."""
        monkeypatch.setattr(allocine.time, "monotonic", _Clock(10.0))
        fake = install_requests(monkeypatch, _page(ONE_FILM))

        with pytest.raises(allocine.SourceTimeoutError, match="page 1"):
            AllocineProvider()._fetch_day_sync("W0124", DAY, deadline=5.0)

        assert not fake.calls

    def test_default_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without a deadline, ``_fetch_day_sync`` uses now plus the call timeout."""
        monkeypatch.setattr(allocine.time, "monotonic", _Clock(1000.0))
        seen: list[float | None] = []
        provider = AllocineProvider(call_timeout=7.0)

        def _pages(_cinema_id: str, _date: str, *, deadline: float | None = None) -> list[dict[str, Any]]:
            seen.append(deadline)
            return [{"results": []}]

        monkeypatch.setattr(provider._api, "fetch_showtime_pages", _pages)

        provider._fetch_day_sync("W0124", DAY)

        assert seen == [1007.0]

    async def test_async_get_day_passes_its_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``async_get_day`` hands a deadline to the worker thread."""
        seen: list[float | None] = []

        def _fetch(
            _self: AllocineProvider, cinema_id: str, day: date, *, deadline: float | None = None
        ) -> DayShowtimes:
            seen.append(deadline)
            return DayShowtimes(cinema_id=cinema_id, day=day, films=())

        monkeypatch.setattr(AllocineProvider, "_fetch_day_sync", _fetch)
        before = allocine.time.monotonic()

        await AllocineProvider(call_timeout=30.0).async_get_day("W0124", DAY)

        assert len(seen) == 1
        assert seen[0] is not None
        assert before + 30.0 <= seen[0] <= allocine.time.monotonic() + 30.0


class TestFilmReferences:
    """Film ids of unusual size or shape (invented)."""

    def test_huge_digit_string(self) -> None:
        """A 5000-digit id is kept verbatim and the day parses."""
        huge = "9" * 5000
        (film,) = _day(_result({"original": [_entry()]}, internalId=huge)).films

        assert film.ref == huge

    def test_all_zeros(self) -> None:
        """``"000"`` is not a usable id."""
        (film,) = _day(_result({"original": [_entry()]}, internalId="000")).films

        assert film.ref is None

    def test_ref_reader_that_raises(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        """A ``_film_ref`` that raises gives ``ref=None``, a debug line, and the day is fine."""

        def _boom(*_args: object) -> str:
            msg = "boom"
            raise ValueError(msg)

        monkeypatch.setattr(allocine, "_film_ref", _boom)

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            (film,) = _day(_result({"original": [_entry()]}, internalId=1)).films

        assert film.ref is None
        assert len(film.showtimes) == 1
        assert any("No usable AlloCiné film id" in message for message in _debug_messages(caplog))


class TestLoggingRule:
    """Unexpected type: one DEBUG line (per key and day for showtimes); ``null`` / missing: silent."""

    @pytest.mark.parametrize(
        "movie",
        [
            *({key: bad} for key in ("stats", "customFlags", "poster", "data", "cast", "flags") for bad in (42, [1])),
            {"credits": 42},
            {"credits": {"person": None}},
            {"cast": {"edges": 42}},
            {"cast": {"edges": {"node": 1}}},
            {"genres": [{"name": "Drame"}]},
            {"genres": ["Drame"]},
        ],
    )
    def test_film_level_unexpected_type(self, caplog: pytest.LogCaptureFixture, movie: dict[str, Any]) -> None:
        """Exactly one DEBUG line, no warning."""
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _day(_result({"original": [_entry()]}, internalId=1, originalTitle="X", **movie))

        assert len(_debug_messages(caplog)) == 1, _debug_messages(caplog)
        assert not _warnings(caplog)

    @pytest.mark.parametrize(
        "fields",
        [
            {"tags": 42},
            {"service": 42},
            {"data": 42},
            {"data": {"ticketing": 42}},
            {"projection": "DIGITAL"},
        ],
    )
    def test_showtime_level_once_per_key_and_day(
        self, caplog: pytest.LogCaptureFixture, fields: dict[str, Any]
    ) -> None:
        """Several showtimes of several films: one line per key and day, a new one on the next day."""
        results = [
            _result(
                {"original": [_entry(**fields), _entry(startsAt="2026-11-12T21:00:00", **fields)]},
                title=title,
                internalId=ref,
            )
            for ref, title in ((1, "A"), (2, "B"))
        ]
        provider = AllocineProvider()

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            day = _day(*results, provider=provider)
            first = len(_debug_messages(caplog))
            _day(*results, provider=provider)

        assert sum(len(film.showtimes) for film in day.films) == 4
        assert first == 1
        assert len(_debug_messages(caplog)) == 2
        assert not _warnings(caplog)

    @pytest.mark.parametrize(
        "movie",
        [
            dict.fromkeys(("stats", "customFlags", "poster", "data", "cast", "credits", "flags", "genres")),
            {"cast": {"edges": None}},
            {"credits": [{"position": {"name": "DIRECTOR"}}]},
            {"stats": {"userRating": None, "pressReview": None, "metric": None}},
        ],
    )
    def test_null_and_missing_are_silent(self, caplog: pytest.LogCaptureFixture, movie: dict[str, Any]) -> None:
        """``null`` or missing optional keys, at film and showtime level: no log line at all."""
        entry = _entry(internalId=1, tags=None, service=None, data=None, projection=None)
        entry.pop("internalId")

        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            _day(_result({"original": [entry, _entry()]}, internalId=1, originalTitle="X", **movie))

        assert not _debug_messages(caplog)
        assert not _warnings(caplog)


class TestUrlValidation:
    """``_is_http_url``: no leading space, no control character; inner and final spaces kept (real relay URLs)."""

    @pytest.mark.parametrize(
        "url",
        [
            " https://d.example/1",
            "https://d.example/\n1",
            "https://d.example/\t1",
            "https://d.example/\x001",
            "https://d.example/\x851",
            "https://d.example/1\n",
        ],
    )
    def test_rejected(self, url: str) -> None:
        """A leading space or any control character: the URL is refused."""
        assert _one(data=_ticketing(_ticket("default", url))).ticket_url is None

    @pytest.mark.parametrize(
        "url",
        ["https://relay.example/t?code=VO; SUBTITLE", "https://relay.example/t?code=vf; pmr; "],
    )
    def test_accepted(self, url: str) -> None:
        """Inner spaces and a final space are kept verbatim."""
        assert _one(data=_ticketing(_ticket("relay", url))).ticket_url == url

    def test_real_relay_urls_with_a_final_space(self) -> None:
        """Real: keeping only the relay entries of C0159 and W7520, every relay URL is accepted, final spaces included."""
        final = 0
        for name in [f"allocine_C0159_2026-11-14_p{n}.json" for n in (1, 2, 3)] + [
            f"allocine_W7520_2026-11-11_p{n}.json" for n in (1, 2)
        ]:
            page = load_json(name)
            expected = []
            for result in page["results"]:
                for entries in result["showtimes"].values():
                    for entry in entries:
                        entry["data"]["ticketing"] = [t for t in entry["data"]["ticketing"] if t["provider"] == "relay"]
                        expected.append(entry["data"]["ticketing"][0]["urls"][0])
            day = AllocineProvider()._convert_day("X1", DAY, [page])
            got = sorted(showtime.ticket_url or "" for film in day.films for showtime in film.showtimes)
            assert got == sorted(expected)
            final += sum(url.endswith(" ") for url in expected)
        assert final > 0

    def test_invalid_default_falls_back_to_relay(self) -> None:
        """An invalid ``default`` URL makes the relay one chosen."""
        data = _ticketing(_ticket("default", " https://d.example/1"), _ticket("relay", "https://r.example/1"))

        assert _one(data=data).ticket_url == "https://r.example/1"


class TestSameFilmOnTwoPages:
    """Which details win when one ``ref`` appears on two pages (invented pages)."""

    @staticmethod
    def _merged(first: dict[str, Any], second: dict[str, Any]) -> Film:
        """Convert two pages holding film ``7`` with these movie fields, and return the merged film."""
        pages = [
            {"results": [_result({"original": [_entry(internalId=1)]}, internalId=7, **first)]},
            {
                "results": [
                    _result(
                        {"original": [_entry(internalId=2, startsAt="2026-11-12T22:00:00")]}, internalId=7, **second
                    )
                ]
            },
        ]
        (film,) = AllocineProvider()._convert_day("W0124", DAY, pages).films
        assert len(film.showtimes) == 2
        return film

    def test_first_without_details(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Page 1 without details (its reader fails), page 2 enriched: page 2's details."""
        original = allocine._film_details
        calls: list[int] = []

        def _first_fails(movie: dict[str, Any], ref: str | None) -> FilmDetails | None:
            calls.append(1)
            if len(calls) == 1:
                msg = "boom"
                raise ValueError(msg)
            return original(movie, ref)

        monkeypatch.setattr(allocine, "_film_details", _first_fails)

        film = self._merged({"originalTitle": "First"}, {"originalTitle": "Second"})

        assert film.details is not None
        assert film.details.original_title == "Second"

    def test_both_enriched(self) -> None:
        """Both enriched: page 1's details."""
        film = self._merged({"originalTitle": "First"}, {"originalTitle": "Second"})

        assert film.details is not None
        assert film.details.original_title == "First"

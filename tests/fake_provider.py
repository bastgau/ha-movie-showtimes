"""A fake showtimes provider for the Home Assistant tests: they never run the AlloCiné code."""

from datetime import date, datetime
import re
from typing import ClassVar, override
from zoneinfo import ZoneInfo

import aiohttp
from custom_components.movie_showtimes.client import (
    CinemaInfo,
    DayShowtimes,
    Film,
    InvalidCinemaRefError,
    Showtime,
    ShowtimesError,
    ShowtimesProvider,
    ShowtimeVersion,
    SourceInfo,
)

PARIS = ZoneInfo("Europe/Paris")
_REF = re.compile(r"[A-Z0-9]{1,10}")


def paris(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Return an aware Europe/Paris datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=PARIS)


def make_film(title: str, *showtimes: tuple[datetime, ShowtimeVersion]) -> Film:
    """Build a film."""
    return Film(
        title=title,
        showtimes=tuple(
            Showtime(starts_at=starts_at, version=version)
            for starts_at, version in sorted(showtimes, key=lambda s: s[0])
        ),
    )


def make_day(cinema_id: str, day: date, *films: Film) -> DayShowtimes:
    """Build a day of showtimes."""
    return DayShowtimes(
        cinema_id=cinema_id, day=day, films=tuple(sorted(films, key=lambda film: film.title.casefold()))
    )


class FakeProvider(ShowtimesProvider):
    """A programmable provider.

    The state lives on the class, because the integration creates its own instances: ``reset`` it before a test.
    """

    source: ClassVar[SourceInfo] = SourceInfo(
        id="fake", name="Fake Cinemas", time_zone="Europe/Paris", ref_example="C1", url_example=""
    )
    days: ClassVar[dict[date, DayShowtimes | ShowtimesError]] = {}
    error: ClassVar[ShowtimesError | None] = None
    calls: ClassVar[list[tuple[str, date]]] = []
    validate_calls: ClassVar[list[tuple[str, date]]] = []
    url: ClassVar[str | None] = "https://fake.example/C1"

    def __init__(self, *, session: aiohttp.ClientSession | None = None) -> None:
        """Create the provider."""
        super().__init__(session=session)
        self.session = session

    @classmethod
    def reset(cls) -> None:
        """Forget the programming and the recorded calls."""
        cls.days = {}
        cls.error = None
        cls.calls = []
        cls.validate_calls = []

    @override
    def normalize_cinema_ref(self, raw: str) -> str:
        """Strip and upper-case the reference; ``fake:<id>`` stands for a pasted URL."""
        value = raw.strip().upper().removeprefix("FAKE:")
        if _REF.fullmatch(value) is None:
            msg = f"Invalid reference {raw!r}"
            raise InvalidCinemaRefError(msg)
        return value

    @override
    async def async_get_day(self, cinema_id: str, day: date) -> DayShowtimes:
        """Return the programmed day, or raise the programmed error."""
        self.calls.append((cinema_id, day))
        outcome = self.days.get(day, self.error)
        if isinstance(outcome, ShowtimesError):
            raise outcome
        return outcome or DayShowtimes(cinema_id=cinema_id, day=day, films=())

    @override
    async def async_validate_cinema(self, cinema_id: str, day: date) -> CinemaInfo:
        """Record the validation, then validate as the base class does."""
        self.validate_calls.append((cinema_id, day))
        return await super().async_validate_cinema(cinema_id, day)

    @override
    def cinema_url(self, cinema_id: str) -> str | None:
        """Return the programmed URL."""
        return self.url


class FakeProvider2(FakeProvider):
    """A second source, with other metadata and no cinema page."""

    source: ClassVar[SourceInfo] = SourceInfo(
        id="fake2",
        name="Other Cinemas",
        time_zone="Europe/London",
        ref_example="X9",
        url_example="https://o.example/X9",
    )
    url: ClassVar[str | None] = None

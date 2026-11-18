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
    FilmDetails,
    InvalidCinemaRefError,
    Showtime,
    ShowtimeFormats,
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


def make_showtime(  # pylint: disable=too-many-arguments
    starts_at: datetime,
    version: ShowtimeVersion,
    *,
    subtitled: bool | None = None,
    hard_of_hearing_subtitles: bool | None = None,
    disabled_access: bool | None = None,
    audio_description: bool | None = None,
    formats: ShowtimeFormats | None = None,
    preview: bool | None = None,
    weekly_outing: bool | None = None,
    ticket_url: str | None = None,
) -> Showtime:
    """Build a showtime; every optional field defaults to unknown."""
    return Showtime(
        starts_at=starts_at,
        version=version,
        subtitled=subtitled,
        hard_of_hearing_subtitles=hard_of_hearing_subtitles,
        disabled_access=disabled_access,
        audio_description=audio_description,
        formats=formats,
        preview=preview,
        weekly_outing=weekly_outing,
        ticket_url=ticket_url,
    )


def make_film(
    title: str,
    *showtimes: tuple[datetime, ShowtimeVersion] | Showtime,
    ref: str | None = None,
    details: FilmDetails | None = None,
) -> Film:
    """Build a film from ``(start, version)`` pairs or ready showtimes, sorted by start."""
    built = [item if isinstance(item, Showtime) else Showtime(starts_at=item[0], version=item[1]) for item in showtimes]
    return Film(
        title=title,
        showtimes=tuple(sorted(built, key=lambda showtime: showtime.starts_at)),
        ref=ref,
        details=details,
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

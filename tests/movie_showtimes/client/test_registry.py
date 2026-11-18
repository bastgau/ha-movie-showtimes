"""The registry of providers, the provider ABC and the models."""

from datetime import date
import inspect

import aiohttp
from custom_components.movie_showtimes.client import (
    PROVIDERS,
    CinemaInfo,
    DayShowtimes,
    ShowtimesError,
    ShowtimesProvider,
    SourceConnectionError,
    SourceInfo,
    SourceTimeoutError,
    UnknownSourceError,
    create_provider,
    get_provider_class,
)
from custom_components.movie_showtimes.client.providers.allocine import AllocineProvider
import pytest

from .provider_contract import ProviderContract


def _contract_classes() -> set[type[ProviderContract]]:
    """Return every class implementing the contract, at any depth."""
    found: set[type[ProviderContract]] = set()
    todo = list(ProviderContract.__subclasses__())
    while todo:
        cls = todo.pop()
        found.add(cls)
        todo.extend(cls.__subclasses__())
    return found


def test_allocine_is_registered() -> None:
    """AlloCiné is the default source."""
    assert PROVIDERS["allocine"] is AllocineProvider
    assert next(iter(PROVIDERS)) == "allocine"


@pytest.mark.parametrize("source_id", list(PROVIDERS))
def test_registered_providers_are_concrete(source_id: str) -> None:
    """Each registered provider is instantiable and filed under its own id."""
    cls = PROVIDERS[source_id]

    assert issubclass(cls, ShowtimesProvider)
    assert not inspect.isabstract(cls)
    assert cls.source.id == source_id
    assert isinstance(cls(), cls)


def test_every_registered_provider_has_a_contract_test() -> None:
    """A provider added to the registry must be run through the contract."""
    # Importing the modules registers the subclasses.
    from . import test_fake_contract  # noqa: F401, PLC0415  # pylint: disable=unused-import,import-outside-toplevel
    from .providers import test_allocine  # noqa: F401, PLC0415  # pylint: disable=unused-import,import-outside-toplevel

    tested = {cls.source_id for cls in _contract_classes()}

    assert set(PROVIDERS) <= tested


def test_get_provider_class() -> None:
    """The class is returned for a known id."""
    assert get_provider_class("allocine") is AllocineProvider


def test_unknown_source() -> None:
    """An unknown id is a typed error, from both entry points."""
    with pytest.raises(UnknownSourceError):
        get_provider_class("nope")
    with pytest.raises(UnknownSourceError):
        create_provider("nope")
    assert issubclass(UnknownSourceError, ShowtimesError)


async def test_create_provider_passes_the_session() -> None:
    """The shared session reaches the provider."""
    seen: list[aiohttp.ClientSession | None] = []

    class Recording(AllocineProvider):
        """Record the session."""

        def __init__(self, *, session: aiohttp.ClientSession | None = None) -> None:
            """Record the session."""
            super().__init__(session=session)
            seen.append(session)

    async with aiohttp.ClientSession() as session:
        PROVIDERS["recording"] = Recording
        try:
            provider = create_provider("recording", session=session)
        finally:
            del PROVIDERS["recording"]

    assert isinstance(provider, Recording)
    assert seen == [session]


def test_abstract_methods_are_enforced() -> None:
    """A provider missing an abstract method cannot be created."""

    class Incomplete(ShowtimesProvider):
        """No ``async_get_day``."""

        source = SourceInfo(id="x", name="X", time_zone="UTC", ref_example="1", url_example="")

        def normalize_cinema_ref(self, raw: str) -> str:
            """Return the input."""
            return raw

    with pytest.raises(TypeError):
        Incomplete()  # pylint: disable=abstract-class-instantiated  # pyright: ignore[reportAbstractUsage]


async def test_default_validate_and_url() -> None:
    """The defaults validate by fetching the day and know no cinema page."""
    fetched: list[tuple[str, date]] = []

    class Minimal(ShowtimesProvider):
        """Only what is abstract."""

        source = SourceInfo(id="min", name="Min", time_zone="UTC", ref_example="1", url_example="")

        def normalize_cinema_ref(self, raw: str) -> str:
            """Return the input."""
            return raw

        async def async_get_day(self, cinema_id: str, day: date) -> DayShowtimes:
            """Record the call."""
            fetched.append((cinema_id, day))
            return DayShowtimes(cinema_id=cinema_id, day=day, films=())

    provider = Minimal()

    info = await provider.async_validate_cinema("A1", date(2026, 11, 12))

    assert info == CinemaInfo(cinema_id="A1", name=None)
    assert fetched == [("A1", date(2026, 11, 12))]
    assert provider.cinema_url("A1") is None


def test_exception_hierarchy() -> None:
    """A timeout is a connection error; every error is a ``ShowtimesError``."""
    assert issubclass(SourceTimeoutError, SourceConnectionError)
    assert issubclass(SourceConnectionError, ShowtimesError)

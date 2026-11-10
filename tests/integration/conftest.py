"""Fixtures of the Home Assistant tests: the registry holds fake providers, never AlloCiné."""

from collections.abc import Callable, Iterator
from unittest.mock import patch
from zoneinfo import ZoneInfo

from custom_components.movie_showtimes.client import registry
import pytest

from homeassistant.util import dt as dt_util
from tests.fake_provider import FakeProvider, FakeProvider2


@pytest.fixture(autouse=True)
def fake() -> Iterator[type[FakeProvider]]:
    """Register the fake as the only source, with a clean programming.

    Yields:
        type[FakeProvider]: The fake, whose class holds the programming and the recorded calls.

    """
    FakeProvider.reset()
    FakeProvider2.reset()
    with patch.dict(registry.PROVIDERS, {"fake": FakeProvider}, clear=True):
        yield FakeProvider
    FakeProvider.reset()
    FakeProvider2.reset()


@pytest.fixture
def two_sources() -> Iterator[None]:
    """Register both fakes.

    Yields:
        None: Once both are registered.

    """
    with patch.dict(registry.PROVIDERS, {"fake": FakeProvider, "fake2": FakeProvider2}, clear=True):
        yield


@pytest.fixture(name="set_time_zone")
def set_time_zone_fixture() -> Iterator[Callable[[str], None]]:
    """Return a function setting Home Assistant's time zone, restored afterwards.

    Yields:
        Callable[[str], None]: The function, given an IANA name.

    """
    original = dt_util.get_default_time_zone()

    def _set(name: str) -> None:
        dt_util.set_default_time_zone(ZoneInfo(name))

    yield _set
    dt_util.set_default_time_zone(original)


@pytest.fixture(autouse=True)
def paris_time_zone(set_time_zone: Callable[[str], None]) -> None:
    """Use Europe/Paris unless a test chooses another zone.

    Args:
        set_time_zone (Callable[[str], None]): Sets Home Assistant's time zone.

    """
    set_time_zone("Europe/Paris")

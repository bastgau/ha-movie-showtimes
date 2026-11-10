"""The fake provider of the Home Assistant tests honours the provider contract too."""

from collections.abc import Iterator

from custom_components.movie_showtimes.client import (
    CinemaNotFoundError,
    ShowtimesProvider,
    ShowtimeVersion,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
)
import pytest

from tests.fake_provider import FakeProvider, make_day, make_film, paris

from .provider_contract import DAY, Arrange, ProviderContract


class TestFakeContract(ProviderContract):
    """Run the contract against the fake."""

    source_id = "fake"

    @pytest.fixture(autouse=True)
    def _reset(self) -> Iterator[None]:
        """Start from a clean fake and leave one behind."""
        FakeProvider.reset()
        yield
        FakeProvider.reset()

    @pytest.fixture
    def provider(self) -> ShowtimesProvider:
        """Return a fake provider."""
        return FakeProvider()

    @pytest.fixture
    def valid_ref(self) -> str:
        """Return a reference to normalize."""
        return " fake:c1 "

    @pytest.fixture
    def canonical_id(self) -> str:
        """Return the canonical id."""
        return "C1"

    @pytest.fixture
    def invalid_refs(self) -> list[str]:
        """Return invalid references."""
        return ["", "  ", "C 1", "TOOLONGREFERENCE", "é"]

    @pytest.fixture
    def arrange(self) -> Arrange:
        """Return the function programming the fake."""

        def _arrange(kind: str) -> None:
            errors = {
                "not_found": CinemaNotFoundError("unknown"),
                "connection": SourceConnectionError("down"),
                "timeout": SourceTimeoutError("slow"),
                "malformed": SourceParseError("odd"),
            }
            if kind == "ok":
                FakeProvider.days[DAY] = make_day(
                    "C1",
                    DAY,
                    make_film("Zorro", (paris(2026, 11, 12, 20), ShowtimeVersion.DUBBED)),
                    make_film("amélie", (paris(2026, 11, 12, 14), ShowtimeVersion.LOCAL)),
                )
            elif kind != "empty":
                FakeProvider.error = errors[kind]

        return _arrange

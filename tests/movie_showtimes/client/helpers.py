"""Helpers shared by the client tests."""

# pylint: disable=too-few-public-methods

import json
from pathlib import Path
from typing import Any, NoReturn, Self

import pytest
import requests

PROVIDERS_FIXTURES = Path(__file__).parent / "providers" / "fixtures"


def load_json(name: str) -> Any:
    """Load a JSON fixture of the provider tests."""
    return json.loads((PROVIDERS_FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    """The part of ``requests.Response`` the provider reads."""

    def __init__(self, status_code: int = 200, text: str = "") -> None:
        """Create the response."""
        self.status_code = status_code
        self.text = text

    @classmethod
    def json_body(cls, document: Any, status_code: int = 200) -> Self:
        """Build a response whose body is a JSON document."""
        return cls(status_code, json.dumps(document))


class FakeRequests:
    """A queue of outcomes standing in for ``requests.get``, recording every call."""

    def __init__(self, *outcomes: FakeResponse | BaseException) -> None:
        """Create the queue."""
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> FakeResponse:
        """Answer one call."""
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def install_requests(monkeypatch: pytest.MonkeyPatch, *outcomes: FakeResponse | BaseException) -> FakeRequests:
    """Replace ``requests.get`` by a ``FakeRequests``."""
    fake = FakeRequests(*outcomes)
    monkeypatch.setattr(requests, "get", fake)
    return fake


def no_network(*_args: object, **_kwargs: object) -> NoReturn:
    """Fail the test if it is called: stands in for anything that would use the network."""
    msg = "The network must not be used"
    raise AssertionError(msg)

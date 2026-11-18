"""The translation files stay consistent and carry the access refusal messages."""

import json
from pathlib import Path
from typing import Any

from custom_components.movie_showtimes import __file__ as integration_file
import pytest

COMPONENT = Path(integration_file).parent
FILES = {
    "strings": COMPONENT / "strings.json",
    "en": COMPONENT / "translations" / "en.json",
    "fr": COMPONENT / "translations" / "fr.json",
}


def _load(name: str) -> dict[str, Any]:
    """Load one translation file."""
    document: dict[str, Any] = json.loads(FILES[name].read_text(encoding="utf-8"))
    return document


def _keys(node: object, prefix: str = "") -> set[str]:
    """Return the dotted paths of every leaf."""
    if isinstance(node, dict):
        return {path for key, value in node.items() for path in _keys(value, f"{prefix}{key}.")}
    return {prefix.rstrip(".")}


@pytest.mark.parametrize("name", FILES)
def test_access_denied_is_translated(name: str) -> None:
    """The flow error and the exception message exist, the latter showing the placeholders."""
    document = _load(name)

    assert document["config"]["error"]["access_denied"]
    message = document["exceptions"]["access_denied"]["message"]
    assert "{source}" in message
    assert "{status}" in message


@pytest.mark.parametrize("name", ["en", "fr"])
def test_key_sets_match_strings(name: str) -> None:
    """Every translation has exactly the keys of ``strings.json``."""
    assert _keys(_load(name)) == _keys(_load("strings"))


@pytest.mark.parametrize("name", FILES)
def test_name_is_optional_and_not_required(name: str) -> None:
    """The flow has no ``name_required`` error any more."""
    document = _load(name)

    assert "name_required" not in document["config"]["error"]
    assert "name_required" not in json.dumps(document)

"""Run the card's JavaScript checks from pytest, and feed its contract test with a real snapshot (design D38, 9.2)."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from unittest.mock import patch

from custom_components.movie_showtimes.client import Film, registry
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from tests import reference_films
from tests.fake_provider import FakeProvider, make_day, paris

ROOT = Path(__file__).parents[2]
CARD = ROOT / "custom_components" / "movie_showtimes" / "frontend" / "movie-showtimes-card.js"
UNIT_TESTS = ROOT / "tests" / "card" / "card.test.mjs"
CONTRACT = ROOT / "tests" / "card" / "contract.mjs"
MIN_NODE_MAJOR = 22
TIMEOUT = 120
TODAY = date(2026, 11, 12)


def _node() -> str:
    """Return the path of a Node.js >= 22, skipping locally and failing in CI when there is none."""
    path = shutil.which("node")
    problem = "node is not installed"
    if path is not None:
        output = subprocess.run(  # noqa: S603
            [path, "--version"], check=False, capture_output=True, text=True, timeout=TIMEOUT
        ).stdout
        match = re.match(r"v(\d+)\.", output)
        if match is not None and int(match.group(1)) >= MIN_NODE_MAJOR:
            return path
        problem = f"node {output.strip()} is older than {MIN_NODE_MAJOR}"
    if os.environ.get("CI"):
        pytest.fail(f"{problem}: the card's tests cannot run in CI")
    return pytest.skip(problem)


@pytest.fixture(name="node", scope="module")
def node_fixture() -> str:
    """Return the Node.js executable."""
    return _node()


def _run(*command: str) -> subprocess.CompletedProcess[str]:
    """Run a command without a shell, with a timeout."""
    return subprocess.run(  # noqa: S603
        command, check=False, capture_output=True, text=True, timeout=TIMEOUT, cwd=ROOT
    )


def test_card_syntax(node: str) -> None:
    """``node --check`` accepts the card."""
    result = _run(node, "--check", str(CARD))
    assert result.returncode == 0, result.stderr


def test_card_unit_tests(node: str) -> None:
    """The card's unit tests pass under ``node --test``."""
    result = _run(node, "--test", str(UNIT_TESTS))
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(autouse=True)
def _fake_source() -> Iterator[None]:
    """Register the fake as the only source, with a clean programming."""
    FakeProvider.reset()
    with patch.dict(registry.PROVIDERS, {"fake": FakeProvider}, clear=True):
        yield
    FakeProvider.reset()


def _on(film: Film, day: date) -> Film:
    """Return the film with its showtimes moved to ``day``, same times."""
    return replace(
        film,
        showtimes=tuple(
            replace(
                showtime,
                starts_at=paris(day.year, day.month, day.day, showtime.starts_at.hour, showtime.starts_at.minute),
            )
            for showtime in film.showtimes
        ),
    )


async def test_contract_with_a_real_snapshot(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path: Path, node: str
) -> None:
    """Every field the backend exposes with data is rendered by the card, on the real attributes."""
    freezer.move_to("2026-11-12T06:00:00+01:00")
    await hass.config.async_set_time_zone("Europe/Paris")
    films = (reference_films.COMMENT_BRAQUER, reference_films.LE_CORSET, reference_films.DUNE, reference_films.RAMAYANA)
    for offset in range(8):
        day = TODAY + timedelta(days=offset)
        FakeProvider.days[day] = make_day("C1", day, *(_on(film, day) for film in films))
    entry = MockConfigEntry(
        domain="movie_showtimes",
        data={"source": "fake", "cinema_id": "C1"},
        unique_id="fake_C1",
        title="Cinema Test",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = {
        item.entity_id: {
            "entity_id": item.entity_id,
            "device_id": item.device_id,
            "platform": item.platform,
            "translation_key": item.translation_key,
        }
        for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    assert len(entities) == 7
    snapshot: dict[str, Any] = {
        "states": {
            state.entity_id: {"entity_id": state.entity_id, "state": state.state, "attributes": dict(state.attributes)}
            for state in hass.states.async_all("sensor")
        },
        "entities": entities,
        "devices": {
            device.id: {"name": device.name, "name_by_user": device.name_by_user, "manufacturer": device.manufacturer}
            for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        },
        "locale": {"language": "en"},
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot, default=str), encoding="utf-8")

    result = _run(node, str(CONTRACT), str(path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "contract ok (1 device(s))" in result.stdout

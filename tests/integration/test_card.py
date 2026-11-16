"""The Lovelace card's registration (card.py) and the contract the card relies on (design D38, section 9.3)."""

from collections.abc import Iterator
import hashlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.movie_showtimes import card
from custom_components.movie_showtimes.card import CARD_PATH, CARD_URL_PATH, card_version
from custom_components.movie_showtimes.const import DOMAIN
from custom_components.movie_showtimes.sensor import SENSOR_DESCRIPTIONS
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.components.http import StaticPathConfig  # pyright: ignore[reportPrivateImportUsage]
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .helpers import ENTRY_ID, make_entry, program_week, setup_entry

NOW = "2026-11-12T10:00:00+01:00"
CARD_LOGGER = "custom_components.movie_showtimes.card"
SENSORS = 7


@pytest.fixture(autouse=True)
def _week(freezer: FrozenDateTimeFactory) -> None:
    """Freeze the clock and program the week."""
    freezer.move_to(NOW)
    program_week()


@pytest.fixture(name="add_js")
def add_js_fixture() -> Iterator[MagicMock]:
    """Patch ``add_extra_js_url`` where the card calls it."""
    with patch.object(card, "add_extra_js_url") as mock:
        yield mock


@pytest.fixture(name="http")
def http_fixture(hass: HomeAssistant) -> AsyncMock:
    """Make Home Assistant look as if http and frontend were loaded, with a mocked http server."""
    hass.config.components.add("http")
    hass.config.components.add("frontend")
    register = AsyncMock()
    hass.http = MagicMock(async_register_static_paths=register)
    return register


def _entry_sensors(hass: HomeAssistant) -> list[er.RegistryEntry]:
    """Return the registry entries of the integration."""
    return er.async_entries_for_config_entry(er.async_get(hass), ENTRY_ID)


def _card_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Return the log records of the card module."""
    return [record for record in caplog.records if record.name == CARD_LOGGER]


def test_card_url_path() -> None:
    """The card is served under the integration's own namespace."""
    assert CARD_URL_PATH == "/movie_showtimes/movie-showtimes-card.js"
    assert CARD_PATH.is_file()


async def test_registered_once_for_two_entries(hass: HomeAssistant, http: AsyncMock, add_js: MagicMock) -> None:
    """Two entries, one static path and one extra module; reload, unload and setup add nothing."""
    first = await setup_entry(hass)
    second = make_entry(
        entry_id="entryc2", unique_id="fake_C2", data={"source": "fake", "cinema_id": "C2"}, title="Cinema Two"
    )
    await setup_entry(hass, second)

    version = hashlib.sha256(CARD_PATH.read_bytes()).hexdigest()[:8]
    http.assert_awaited_once_with([StaticPathConfig(CARD_URL_PATH, str(CARD_PATH), cache_headers=True)])
    add_js.assert_called_once_with(hass, f"{CARD_URL_PATH}?v={version}")
    assert len(version) == 8
    int(version, 16)

    assert await hass.config_entries.async_reload(first.entry_id)
    assert await hass.config_entries.async_unload(second.entry_id)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    assert (first.state, second.state) == (ConfigEntryState.LOADED, ConfigEntryState.LOADED)
    assert http.await_count == 1
    assert add_js.call_count == 1


def test_card_version_is_the_content_hash(tmp_path: Path) -> None:
    """The version is the first 8 hex characters of the SHA-256 of the bytes, and follows the content."""
    assert card_version(CARD_PATH) == hashlib.sha256(CARD_PATH.read_bytes()).hexdigest()[:8]
    other = tmp_path / "other.js"
    other.write_bytes(b"export const other = 1;\n")
    assert card_version(other) == hashlib.sha256(b"export const other = 1;\n").hexdigest()[:8]
    assert card_version(other) != card_version(CARD_PATH)


@pytest.mark.parametrize("missing", ["frontend", "http"])
async def test_without_frontend_or_http(
    hass: HomeAssistant,
    http: AsyncMock,
    add_js: MagicMock,
    caplog: pytest.LogCaptureFixture,
    missing: str,
) -> None:
    """Without one of the two components: nothing registered, one debug line, the entry loads."""
    hass.config.components.remove(missing)
    assert missing not in hass.config.components

    with caplog.at_level(logging.DEBUG, logger=CARD_LOGGER):
        entry = await setup_entry(hass)

    http.assert_not_awaited()
    add_js.assert_not_called()
    records = _card_records(caplog)
    assert [record.levelno for record in records] == [logging.DEBUG]
    assert entry.state is ConfigEntryState.LOADED
    assert len(_entry_sensors(hass)) == SENSORS


async def test_missing_card_file(
    hass: HomeAssistant,
    http: AsyncMock,
    add_js: MagicMock,
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    """An unreadable card: one warning, nothing registered, the entry still loads."""
    with (
        patch.object(card, "CARD_PATH", tmp_path / "missing.js"),
        caplog.at_level(logging.DEBUG, logger=CARD_LOGGER),
    ):
        entry = await setup_entry(hass)

    http.assert_not_awaited()
    add_js.assert_not_called()
    assert [record.levelno for record in _card_records(caplog)] == [logging.WARNING]
    assert entry.state is ConfigEntryState.LOADED
    assert len(_entry_sensors(hass)) == SENSORS


async def test_card_is_served_over_http(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator, add_js: MagicMock
) -> None:
    """A real GET of the card path answers 200 with the file and cache headers."""
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")

    await setup_entry(hass)
    client = await hass_client_no_auth()
    response = await client.get(CARD_URL_PATH)

    assert response.status == 200
    assert await response.read() == CARD_PATH.read_bytes()
    assert "max-age" in response.headers["Cache-Control"]
    add_js.assert_called_once()


async def test_config_schema_accepts_yaml_and_returns_true(hass: HomeAssistant) -> None:
    """YAML configuration is ignored (config entries only), and the component still sets up."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {"x": 1}})


async def test_translation_key_contract(hass: HomeAssistant) -> None:
    """The card resolves sensors by translation key and platform: both are stable."""
    assert [description.translation_key for description in SENSOR_DESCRIPTIONS] == [
        "today",
        "tomorrow",
        *(f"day_{offset}" for offset in range(2, 7)),
    ]

    await setup_entry(hass)

    entries = _entry_sensors(hass)
    assert len(entries) == SENSORS
    assert {entry.platform for entry in entries} == {DOMAIN}
    devices = {entry.device_id for entry in entries}
    assert len(devices) == 1
    device = dr.async_get(hass).async_get(next(iter(devices)))
    assert device is not None
    assert {entry.translation_key for entry in entries} == {
        description.translation_key for description in SENSOR_DESCRIPTIONS
    }


async def test_path_already_registered(
    hass: HomeAssistant,
    http: AsyncMock,
    add_js: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A static path that is already registered: one warning, the module is still added, the entry loads."""
    http.side_effect = RuntimeError("Path already registered")

    with caplog.at_level(logging.DEBUG, logger=CARD_LOGGER):
        entry = await setup_entry(hass)

    http.assert_awaited_once()
    add_js.assert_called_once()
    records = _card_records(caplog)
    assert [record.levelno for record in records] == [logging.WARNING]
    assert "already registered" in records[0].getMessage()
    assert entry.state is ConfigEntryState.LOADED
    assert len(_entry_sensors(hass)) == SENSORS

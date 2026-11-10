"""The config flow: source (when there are several), then the cinema."""

from datetime import date
import logging
from typing import Any

from custom_components.movie_showtimes.client import (
    CinemaNotFoundError,
    SourceAccessDeniedError,
    SourceConnectionError,
    SourceParseError,
    SourceTimeoutError,
)
from custom_components.movie_showtimes.const import DOMAIN
from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.fake_provider import FakeProvider, FakeProvider2

from .helpers import make_entry, program_week

NOW = "2026-11-12T10:00:00+01:00"


async def _start(hass: HomeAssistant) -> dict[str, Any]:
    """Start the flow."""
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def _submit(hass: HomeAssistant, flow_id: str, cinema_id: str = "C1", name: str = "My cinema") -> dict[str, Any]:
    """Submit the cinema form."""
    return await hass.config_entries.flow.async_configure(flow_id, {"cinema_id": cinema_id, "name": name})


async def test_one_source_skips_the_source_step(hass: HomeAssistant) -> None:
    """With a single source, the first form is the cinema one, described with the source's metadata."""
    result = await _start(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cinema"
    assert result["description_placeholders"] == {"source_name": "Fake Cinemas", "ref_example": "C1", "url_example": ""}


async def test_create_entry(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """A valid cinema creates the entry with the canonical id, and the validated day is today."""
    freezer.move_to(NOW)
    program_week()
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], " c1 ", "  My cinema  ")
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My cinema"
    assert result["data"] == {"source": "fake", "cinema_id": "C1"}
    entry = result["result"]
    assert entry.unique_id == "fake_C1"
    assert entry.state is ConfigEntryState.LOADED
    assert FakeProvider.validate_calls == [("C1", date(2026, 11, 12))]


async def test_validated_day_is_today_in_the_home_assistant_zone(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, set_time_zone: Any
) -> None:
    """It is Friday in Auckland while it is still Thursday in UTC."""
    set_time_zone("Pacific/Auckland")
    freezer.move_to("2026-11-12T11:30:00+00:00")
    result = await _start(hass)

    await _submit(hass, result["flow_id"])
    await hass.async_block_till_done()

    assert FakeProvider.validate_calls == [("C1", date(2026, 11, 13))]


async def test_pasted_reference_gives_the_same_entry(hass: HomeAssistant) -> None:
    """An alternative reference form (standing for a pasted URL) stores the canonical id."""
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], "fake:c1")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"source": "fake", "cinema_id": "C1"}
    assert result["result"].unique_id == "fake_C1"


async def test_empty_day_is_a_success(hass: HomeAssistant) -> None:
    """A cinema with nothing on today still exists."""
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("cinema_id", "name", "title"),
    [
        ("C1", "", "Fake Cinemas - C1"),
        ("c1", "   ", "Fake Cinemas - C1"),
        (" fake:c1 ", "", "Fake Cinemas - C1"),
        ("C1", " My cinema ", "My cinema"),
    ],
)
async def test_title_is_the_name_or_the_source_and_id(
    hass: HomeAssistant, cinema_id: str, name: str, title: str
) -> None:
    """A blank name gives "<source> - <canonical id>", also from a pasted reference; a name is kept, stripped."""
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], cinema_id, name)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == title
    assert result["data"] == {"source": "fake", "cinema_id": "C1"}


async def test_name_can_be_left_out(hass: HomeAssistant) -> None:
    """The name field is optional: submitting only the cinema creates the entry."""
    result = await _start(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"cinema_id": "C1"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Fake Cinemas - C1"


@pytest.mark.parametrize(
    ("cinema_id", "name", "error", "errors"),
    [
        ("not valid!", "Name", None, {"cinema_id": "invalid_cinema_id"}),
        ("bad ref", " ", None, {"cinema_id": "invalid_cinema_id"}),
        ("C1", "Name", CinemaNotFoundError("unknown"), {"cinema_id": "invalid_cinema_id"}),
        ("C1", "Name", SourceConnectionError("down"), {"base": "cannot_connect"}),
        ("C1", "Name", SourceTimeoutError("slow"), {"base": "cannot_connect"}),
        ("C1", "Name", SourceAccessDeniedError("refused", status_code=403), {"base": "access_denied"}),
        ("C1", "Name", SourceParseError("changed"), {"base": "unknown"}),
    ],
)
async def test_errors_then_recovery(
    hass: HomeAssistant, cinema_id: str, name: str, error: Exception | None, errors: dict[str, str]
) -> None:
    """Each error shows the form again with its message, and the corrected input creates the entry."""
    result = await _start(hass)
    FakeProvider.error = error  # type: ignore[assignment]

    result = await _submit(hass, result["flow_id"], cinema_id, name)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cinema"
    assert result["errors"] == errors
    if "invalid_cinema_id" in errors.values() and error is None:
        assert not FakeProvider.validate_calls
    FakeProvider.error = None

    result = await _submit(hass, result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("error", "error_key", "expected_log"),
    [
        (SourceAccessDeniedError("refused", status_code=429), "access_denied", "HTTP 429"),
        (SourceAccessDeniedError("refused"), "access_denied", "HTTP None"),
        (SourceConnectionError("socket closed"), "cannot_connect", "socket closed"),
    ],
)
async def test_connection_errors_log_one_warning(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    error_key: str,
    expected_log: str,
) -> None:
    """A refusal or a connection failure shows its error, logs one warning with the cause, and recovers."""
    result = await _start(hass)
    FakeProvider.error = error  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING, logger="custom_components.movie_showtimes.config_flow"):
        result = await _submit(hass, result["flow_id"])

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error_key}
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "config_flow" in r.name]
    assert len(warnings) == 1
    assert expected_log in warnings[0].getMessage()
    FakeProvider.error = None

    result = await _submit(hass, result["flow_id"])

    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("cinema_id", ["C1", " c1 ", "fake:c1"])
async def test_duplicate_aborts_without_any_request(hass: HomeAssistant, cinema_id: str) -> None:
    """A cinema already configured aborts, however it is typed, before asking the source."""
    make_entry().add_to_hass(hass)
    result = await _start(hass)

    result = await _submit(hass, result["flow_id"], cinema_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert not FakeProvider.validate_calls


async def test_two_sources_show_the_source_step(hass: HomeAssistant, two_sources: None) -> None:
    """With two sources, the user chooses one; the entry records it."""
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source": "fake2"})
    assert result["step_id"] == "cinema"
    assert result["description_placeholders"]["source_name"] == "Other Cinemas"
    assert result["description_placeholders"]["url_example"] == "https://o.example/X9"

    result = await _submit(hass, result["flow_id"], "x9")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"source": "fake2", "cinema_id": "X9"}
    assert result["result"].unique_id == "fake2_X9"
    assert FakeProvider2.validate_calls
    assert not FakeProvider.validate_calls


async def test_same_cinema_id_under_two_sources(hass: HomeAssistant, two_sources: None) -> None:
    """The same id under two sources makes two entries."""
    unique_ids: list[str | None] = []
    for source in ("fake", "fake2"):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"source": source})
        result = await _submit(hass, result["flow_id"])
        assert result["type"] is FlowResultType.CREATE_ENTRY
        unique_ids.append(result["result"].unique_id)
        await hass.async_block_till_done()

    assert unique_ids == ["fake_C1", "fake2_C1"]
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2

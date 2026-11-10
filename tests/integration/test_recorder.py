"""What the recorder keeps of a day sensor."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .helpers import TODAY_ID, program_week, setup_entry

NOW = "2026-11-12T10:00:00+01:00"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_db_url: str, enable_custom_integrations: None) -> None:
    """Prepare the recorder's database before Home Assistant starts, then enable the integration."""


async def test_films_are_not_recorded(
    hass: HomeAssistant, recorder_mock: Recorder, freezer: FrozenDateTimeFactory
) -> None:
    """``films`` is absent from the recorded attributes; ``date`` and ``fetched_at`` are present."""
    freezer.move_to(NOW)
    program_week()
    await setup_entry(hass)
    assert "films" in hass.states.get(TODAY_ID).attributes
    await async_wait_recording_done(hass)

    states = await recorder_mock.async_add_executor_job(
        get_significant_states, hass, dt_util.utcnow() - timedelta(days=1), None, [TODAY_ID]
    )

    recorded = states[TODAY_ID][-1].attributes
    assert "films" not in recorded
    assert recorded["date"] == "2026-11-12"
    assert "fetched_at" in recorded

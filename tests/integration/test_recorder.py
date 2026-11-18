"""What the recorder keeps of a day sensor."""

from dataclasses import replace
from datetime import timedelta
import json

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.components.recorder.common import async_wait_recording_done

from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests import reference_films
from tests.fake_provider import FakeProvider, make_day

from .helpers import TODAY, TODAY_ID, at, program_week, setup_entry

NOW = "2026-11-12T10:00:00+01:00"


@pytest.fixture(autouse=True)
def paris_time_zone(recorder_db_url: str, paris_time_zone: None) -> None:  # pylint: disable=redefined-outer-name
    """Prepare the recorder's database before ``hass`` exists, then set the time zone as every other test.

    The conftest's autouse fixture of the same name is the one requested here: it creates ``hass``, which the
    recorder's database fixture refuses to follow.
    """


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


async def test_a_day_the_size_of_c0159_is_not_recorded(
    hass: HomeAssistant, recorder_mock: Recorder, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """36 enriched films, 161 showtimes on every sensor: recorded attributes are date, fetched_at, friendly_name."""
    freezer.move_to(NOW)
    sources = [
        reference_films.COMMENT_BRAQUER,
        reference_films.LE_CORSET,
        reference_films.DUNE,
        reference_films.RAMAYANA,
    ]
    for offset in range(8):
        day = TODAY + timedelta(days=offset)
        films = []
        for index in range(36):
            source = sources[index % len(sources)]
            showtimes = tuple(
                replace(source.showtimes[0], starts_at=at(day, 12, index) + timedelta(minutes=40 * number))
                for number in range(5 if index < 17 else 4)
            )
            films.append(replace(source, title=f"{source.title} {index}", ref=str(index), showtimes=showtimes))
        FakeProvider.days[day] = make_day("C1", day, *films)
    await setup_entry(hass)
    state = hass.states.get(TODAY_ID)
    assert sum(len(film["details"]["showtimes"]) for film in state.attributes["films"]) == 161
    assert len(json.dumps(state.attributes["films"])) > 100_000
    await async_wait_recording_done(hass)

    states = await recorder_mock.async_add_executor_job(
        get_significant_states, hass, dt_util.utcnow() - timedelta(days=1), None, [TODAY_ID]
    )

    assert set(states[TODAY_ID][-1].attributes) == {"date", "fetched_at", "friendly_name"}
    assert "exceed maximum size" not in caplog.text

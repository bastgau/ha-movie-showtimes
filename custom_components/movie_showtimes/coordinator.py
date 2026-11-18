"""Coordinator of the Movie Showtimes integration: one per config entry, i.e. per cinema."""

from datetime import date, datetime, timedelta
from itertools import chain
import logging
from typing import Final, override

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    CinemaNotFoundError,
    DayShowtimes,
    ShowtimesError,
    ShowtimesProvider,
    SourceAccessDeniedError,
    SourceConnectionError,
)
from .const import CONF_CINEMA_ID, DAYS_FETCHED, DOMAIN, RETRY_AFTER_CONNECTION_ERROR, UPDATE_INTERVAL
from .showtimes import day_data_expiry, is_day_usable, showtime_expiry
from .store import CachedDay, ShowtimesStore, StoredSnapshot, unify_film_details

_LOGGER = logging.getLogger(__name__)

_KEY_ACCESS_DENIED: Final = "access_denied"
_KEY_CANNOT_CONNECT: Final = "cannot_connect"
_KEY_CINEMA_NOT_FOUND: Final = "cinema_not_found"
_KEY_INVALID_RESPONSE: Final = "invalid_response"

type MovieShowtimesConfigEntry = ConfigEntry[MovieShowtimesCoordinator]
type ShowtimesData = dict[date, CachedDay]


class MovieShowtimesCoordinator(DataUpdateCoordinator[ShowtimesData]):
    """Fetch the cinema's showtimes twice a day, keep them across restarts, and re-render when they expire.

    Attributes:
        config_entry (MovieShowtimesConfigEntry): The entry of the cinema.
        last_refresh (datetime | None): The end of the last successful refresh, aware UTC; restored at setup.
        restored_from_store (bool): Whether the data in use came from the store at setup.
        _provider (ShowtimesProvider): The showtimes source.
        _store (ShowtimesStore): The persisted snapshot.
        _parse_failing (bool): Whether the last refresh had a day that could not be parsed.
        _unsub_showtime (CALLBACK_TYPE | None): Cancels the pending showtime timer, if any.

    """

    config_entry: MovieShowtimesConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MovieShowtimesConfigEntry,
        provider: ShowtimesProvider,
        store: ShowtimesStore,
    ) -> None:
        """Create the coordinator.

        Args:
            hass (HomeAssistant): The Home Assistant instance.
            config_entry (MovieShowtimesConfigEntry): The entry of the cinema.
            provider (ShowtimesProvider): The showtimes source.
            store (ShowtimesStore): The entry's store.

        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {config_entry.unique_id}",
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self._provider = provider
        self._store = store
        self.last_refresh: datetime | None = None
        self.restored_from_store = False
        self._unsub_showtime: CALLBACK_TYPE | None = None
        self._parse_failing = False

    @property
    def cinema_id(self) -> str:
        """The provider's canonical id of the entry's cinema.

        Returns:
            str: The id, e.g. ``W0124``.

        """
        cinema_id: str = self.config_entry.data[CONF_CINEMA_ID]
        return cinema_id

    @property
    def provider(self) -> ShowtimesProvider:
        """The showtimes source of the entry.

        Returns:
            ShowtimesProvider: The provider.

        """
        return self._provider

    async def async_initialize(self) -> None:
        """Restore the stored data and refresh only if it is not fresh.

        Fresh stored data (younger than the update interval) makes no request, and the next refresh is due at
        ``last_refresh + UPDATE_INTERVAL``. Otherwise a refresh runs; if it fails and the store held something
        usable, that is served instead.

        ``ConfigEntryNotReady`` is raised when the refresh failed and nothing usable was stored.

        """
        now = dt_util.utcnow()
        today = dt_util.now().date()
        snapshot = await self._store.async_load_snapshot(self._provider.source, self.cinema_id)
        if snapshot is not None:
            # Past days are of no use: drop them so that the showtime timer does not carry them.
            snapshot = StoredSnapshot(
                last_refresh=snapshot.last_refresh,
                days={day: cached for day, cached in snapshot.days.items() if day >= today},
            )
        usable = snapshot is not None and any(is_day_usable(cached, now) for cached in snapshot.days.values())
        if snapshot is not None and usable:
            self.async_set_updated_data(snapshot.days)
            self.last_refresh = snapshot.last_refresh
            self.restored_from_store = True
            self._async_schedule_next_showtime(self.data)
            age = now - snapshot.last_refresh
            if timedelta(0) <= age < UPDATE_INTERVAL:
                # One-shot: the first listener schedules the refresh with this interval, then
                # _async_update_data puts the normal one back.
                self.update_interval = UPDATE_INTERVAL - age
                return

        try:
            await self.async_config_entry_first_refresh()
        except ConfigEntryNotReady:
            if not usable:
                raise
            if isinstance(self.last_exception, UpdateFailed) and self.last_exception.retry_after is not None:
                # HA ignores retry_after during setup: do the same one-shot as for fresh data.
                self.update_interval = timedelta(seconds=self.last_exception.retry_after)
            _LOGGER.warning(
                "%s is unreachable, showing the showtimes fetched at %s",
                self._provider.source.name,
                self.last_refresh.isoformat() if self.last_refresh else "an unknown time",
            )

    def _refresh_failure(
        self, translation_key: str, status_code: int | None = None, *, retry_soon: bool = False
    ) -> UpdateFailed:
        """Build the translated ``UpdateFailed`` of a refresh failure.

        Args:
            translation_key (str): The key under ``exceptions`` in the translations.
            status_code (int | None): The HTTP status of an access refusal, shown in the message.
            retry_soon (bool): Whether to ask for an early retry (``RETRY_AFTER_CONNECTION_ERROR``).

        Returns:
            UpdateFailed: The exception, ready to be raised.

        """
        return UpdateFailed(
            translation_domain=DOMAIN,
            translation_key=translation_key,
            translation_placeholders={
                "source": self._provider.source.name,
                "status": str(status_code) if status_code is not None else "?",
            },
            retry_after=RETRY_AFTER_CONNECTION_ERROR.total_seconds() if retry_soon else None,
        )

    @override
    async def _async_update_data(self) -> ShowtimesData:
        """Fetch today to today + 7, one day after the other, then persist the result.

        A connection failure or an unknown cinema stops the refresh at once. A day that cannot be parsed keeps its
        previous copy if that is still young enough, and is left out otherwise; if every day fails to parse, the
        refresh fails.

        Returns:
            ShowtimesData: The days, keyed by date.

        ``UpdateFailed`` is raised when the source is unreachable, the cinema is unknown, or no day could be
        parsed.

        """
        self.update_interval = UPDATE_INTERVAL
        now = dt_util.utcnow()
        today = dt_util.now().date()
        previous = self.data or {}
        result: ShowtimesData = {}
        failed: list[date] = []
        for offset in range(DAYS_FETCHED):
            day = today + timedelta(days=offset)
            try:
                showtimes: DayShowtimes = await self._provider.async_get_day(self.cinema_id, day)
            except SourceAccessDeniedError as err:
                if self.last_update_success:  # Only when it starts failing: not on every refresh.
                    _LOGGER.warning(
                        "%s refused the request for cinema %s (HTTP %s)",
                        self._provider.source.name,
                        self.cinema_id,
                        err.status_code,
                    )
                raise self._refresh_failure(_KEY_ACCESS_DENIED, err.status_code) from err
            except SourceConnectionError as err:
                raise self._refresh_failure(_KEY_CANNOT_CONNECT, retry_soon=True) from err
            except CinemaNotFoundError as err:
                raise self._refresh_failure(_KEY_CINEMA_NOT_FOUND) from err
            except ShowtimesError as err:
                # One warning per episode (on the first failing refresh), debug afterwards.
                _LOGGER.log(
                    logging.DEBUG if self._parse_failing or failed else logging.WARNING,
                    "Ignoring the showtimes of %s for %s: %s",
                    self.cinema_id,
                    day.isoformat(),
                    err,
                )
                failed.append(day)
            else:
                result[day] = CachedDay(showtimes=showtimes, fetched_at=now)

        self._parse_failing = bool(failed)
        if len(failed) == DAYS_FETCHED:
            raise self._refresh_failure(_KEY_INVALID_RESPONSE)

        for day in failed:
            cached = previous.get(day)
            if cached is not None and is_day_usable(cached, now):
                result[day] = cached

        # A refetched film's details replace the older ones on the days kept from before, so memory and store agree.
        result, _ = unify_film_details(result)

        if self.config_entry.state in (ConfigEntryState.SETUP_IN_PROGRESS, ConfigEntryState.LOADED):
            # Not while unloading or removing: it would recreate the file the removal just deleted.
            await self._store.async_save_snapshot(
                self._provider.source, self.cinema_id, StoredSnapshot(last_refresh=now, days=result)
            )
        self.last_refresh = now
        self._async_schedule_next_showtime(result)
        return result

    @callback
    def async_handle_midnight(self, now: datetime) -> None:
        """Re-render the entities so that each day sensor moves to its new date.

        Args:
            now (datetime): The time the listener fired.

        """
        self.async_update_listeners()
        self._async_schedule_next_showtime(self.data)

    @callback
    def _async_handle_showtime_started(self, now: datetime) -> None:
        """Re-render the entities so that the showtime that just expired drops out, then re-arm.

        Args:
            now (datetime): The time the timer fired.

        """
        self._unsub_showtime = None
        self.async_update_listeners()
        self._async_schedule_next_showtime(self.data)

    @callback
    def _async_schedule_next_showtime(self, data: ShowtimesData | None) -> None:
        """Arm the showtime timer at the earliest expiry strictly after now, cancelling the pending one.

        Args:
            data (ShowtimesData | None): The data the entities render.

        """
        self._async_cancel_showtime_timer()
        if not data:
            return
        now = dt_util.utcnow()
        expiries = (
            expiry
            for cached in data.values()
            for film in cached.showtimes.films
            for showtime in film.showtimes
            if (expiry := showtime_expiry(showtime)) > now
        )
        age_limits = (limit for cached in data.values() if (limit := day_data_expiry(cached)) > now)
        next_expiry = min(chain(expiries, age_limits), default=None)
        if next_expiry is not None:
            self._unsub_showtime = async_track_point_in_time(
                self.hass, self._async_handle_showtime_started, next_expiry
            )

    @callback
    def _async_cancel_showtime_timer(self) -> None:
        """Cancel the pending showtime timer, if any."""
        if self._unsub_showtime is not None:
            self._unsub_showtime()
            self._unsub_showtime = None

    @override
    async def async_shutdown(self) -> None:
        """Cancel the showtime timer, then shut the coordinator down."""
        self._async_cancel_showtime_timer()
        await super().async_shutdown()

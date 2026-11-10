"""Exceptions raised by the showtimes client, whatever the source.

Every error leaving a provider is one of these: no library, ``requests`` or ``aiohttp`` exception crosses the
client boundary. The original exception, when there is one, is chained as ``__cause__``.
"""


class ShowtimesError(Exception):
    """Base of every client error."""


class SourceConnectionError(ShowtimesError):
    """The source is unreachable, or answered an unexpected status."""


class SourceTimeoutError(SourceConnectionError):
    """A request, or the whole call, exceeded its timeout."""


class SourceAccessDeniedError(SourceConnectionError):
    """The source refused the request (HTTP 403 or 429): blocked or rate-limited, not unreachable.

    Attributes:
        status_code (int | None): The HTTP status of the refusal, when known.

    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        """Store the status.

        Args:
            message (str): The error message.
            status_code (int | None): The HTTP status of the refusal.

        """
        super().__init__(message)
        self.status_code = status_code


class CinemaNotFoundError(ShowtimesError):
    """The source does not know this cinema."""


class SourceParseError(ShowtimesError):
    """The source's response did not have the expected shape: the site probably changed."""


class InvalidCinemaRefError(ShowtimesError):
    """The cinema reference is malformed. Checked locally, before any request."""


class UnknownSourceError(ShowtimesError):
    """No provider is registered under this source id."""

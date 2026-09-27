"""Public import transport: sequential requests, bounded waits, no credentials."""
from contextlib import contextmanager
import io
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from chesswizard_version import VERSION

REQUEST_TIMEOUT_SECONDS = 30
RATE_LIMIT_PAUSE_SECONDS = 60
_network_lock = threading.Lock()
_retry_after = 0.0


class ImportConnectionError(ValueError):
    """A user-readable provider failure; previously committed games remain valid."""


@contextmanager
def open_text(url, accept="application/x-chess-pgn"):
    global _retry_after
    with _network_lock:
        remaining = _retry_after - time.monotonic()
        if remaining > 0:
            raise ImportConnectionError(f"Source rate limit: wait {int(remaining) + 1} seconds before trying again.")
        request = Request(url, headers={"Accept": accept,
            "User-Agent": f"ChessWizard/{VERSION} (open-source chess training project)"})
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                with io.TextIOWrapper(response, encoding="utf-8-sig") as stream:
                    yield stream
        except HTTPError as error:
            error.close()
            if error.code == 429:
                try:
                    delay = max(RATE_LIMIT_PAUSE_SECONDS, int(error.headers.get("Retry-After", str(RATE_LIMIT_PAUSE_SECONDS))))
                except (ValueError, TypeError):
                    delay = RATE_LIMIT_PAUSE_SECONDS
                _retry_after = time.monotonic() + delay
                raise ImportConnectionError(f"Source rate limit. Wait at least {delay} seconds before importing again.") from error
            if error.code == 404:
                raise ImportConnectionError("Account or game archive was not found. Check the username and source.") from error
            raise ImportConnectionError(f"Source request failed (HTTP {error.code}). Try again later.") from error
        except (URLError, OSError, UnicodeError) as error:
            raise ImportConnectionError("Connection failed or download was interrupted. Check your internet connection and try again.") from error


def read_text(url):
    with open_text(url) as stream:
        return stream.read()


def read_json(url):
    with open_text(url, "application/json") as stream:
        try:
            return json.load(stream)
        except (ValueError, UnicodeError) as error:
            raise ImportConnectionError("The source returned an unexpected archive response.") from error

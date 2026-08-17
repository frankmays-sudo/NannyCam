import logging
import socket
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_COMMANDS = b"get battery\nget battery_charging\nget battery_power_plugged\n"


@dataclass(frozen=True)
class BatteryStatus:
    percent: float
    charging: bool
    power_plugged: bool


def read_battery_status(socket_path: str, timeout: float = 3.0) -> BatteryStatus | None:
    """Query pisugar-server's line protocol over its Unix domain socket.

    Returns None if pisugar-server isn't reachable (not installed, not running,
    or an unexpected response) -- callers should treat that as "unknown", not
    raise.
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(_COMMANDS)
            buf = b""
            while buf.count(b"\n") < 3:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except (OSError, AttributeError):
        # AttributeError covers platforms without socket.AF_UNIX at all
        # (e.g. some Windows Python builds) -- battery status is always
        # best-effort, never a hard requirement.
        logger.warning("Could not reach pisugar-server at %s", socket_path)
        return None

    values: dict[str, str] = {}
    for line in buf.decode(errors="replace").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip()

    try:
        return BatteryStatus(
            percent=float(values["battery"]),
            charging=values["battery_charging"] == "true",
            power_plugged=values["battery_power_plugged"] == "true",
        )
    except (KeyError, ValueError):
        logger.warning("Unexpected pisugar-server response: %r", buf)
        return None


class BatteryMonitor:
    """Periodically polls battery status and logs a warning each time it drops
    below threshold while running on battery power.

    Edge-triggered: only logs on the low -> not-low transition, not on every
    poll while it stays low, to avoid spamming the journal.
    """

    def __init__(
        self,
        socket_path: str,
        low_battery_percent: float,
        poll_interval: float = 60.0,
    ):
        self._socket_path = socket_path
        self._low_battery_percent = low_battery_percent
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._was_low = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(
            "BatteryMonitor started (threshold=%.0f%%, poll=%.0fs)",
            self._low_battery_percent, self._poll_interval,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("BatteryMonitor stopped")

    def _watch_loop(self) -> None:
        while True:
            try:
                self._check_once()
            except Exception:
                logger.exception("Battery check error")
            if self._stop_event.wait(timeout=self._poll_interval):
                break  # stop() was called

    def _check_once(self) -> None:
        status = read_battery_status(self._socket_path)
        if status is None:
            return
        is_low = status.percent < self._low_battery_percent and not status.power_plugged
        if is_low and not self._was_low:
            logger.warning(
                "Battery low: %.1f%% (threshold %.0f%%), charging=%s",
                status.percent, self._low_battery_percent, status.charging,
            )
        self._was_low = is_low

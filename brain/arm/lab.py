"""CAN bus handoff with MakerMods Lab (tools/makermodslab, run via tools/lab.sh).

Lab is used to set the arms up (calibrate, teleoperate, check cameras) and it owns the CAN
bus while a session runs. Two programs commanding the same Damiao motors is a safety
problem, so the real arm's connect() calls ensure_bus_free() first.
"""

import json
import os
import urllib.error
import urllib.request

LAB_URL = os.environ.get("MAKERMODSLAB_URL", "http://localhost:8000")


class ArmBusBusy(RuntimeError):
    pass


def lab_session(base_url: str = LAB_URL, timeout_s: float = 0.5) -> str | None:
    """Kind of the session Lab is running ("teleoperate", "calibrate", ...), or None.

    None also when Lab isn't running at all, which is the normal case during a game.
    """
    try:
        with urllib.request.urlopen(f"{base_url}/api/v1/sessions/current", timeout=timeout_s) as resp:
            session = json.loads(resp.read()).get("session")
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return None
    return session.get("kind", "unknown") if session else None


def ensure_bus_free(base_url: str = LAB_URL) -> None:
    """Raise ArmBusBusy if a MakerMods Lab session is holding the arms."""
    kind = lab_session(base_url)
    if kind:
        raise ArmBusBusy(
            f"MakerMods Lab has a {kind!r} session on the arms ({base_url}). "
            "Stop it in the Lab UI and quit tools/lab.sh before starting the hub."
        )

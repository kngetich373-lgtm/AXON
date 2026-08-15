"""Desktop entry point for AXON."""
from __future__ import annotations

import os
import sys


def ensure_graphical_session():
    """Fail before Tk initialises when AXON is launched without a display."""
    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        print(
            "AXON desktop UI needs a graphical session; no DISPLAY or "
            "WAYLAND_DISPLAY is available.\n\n"
            "Launch it from a logged-in Linux desktop terminal, or connect "
            "with X11 forwarding (ssh -X) and ensure an X server is running.\n"
            "Then run: ./run.sh",
            file=sys.stderr,
        )
        return False
    return True

if __name__ == "__main__":
    if not ensure_graphical_session():
        raise SystemExit(2)
    try:
        from axon.app import AXONApp
        app = AXONApp()
        app.mainloop()
    except Exception as exc:
        # A stale DISPLAY or unavailable Tk backend should still be actionable
        # instead of producing a long raw Tcl traceback for desktop users.
        if exc.__class__.__name__ == "TclError":
            print(
                "AXON could not open the desktop display. Start it from an "
                "active graphical session (or use ssh -X with a working X server) "
                "and run ./run.sh.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        raise

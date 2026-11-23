"""Opt-in labwc/wlrctl display focus adapter, feature OFF by default.

This is NOT a compositor frame-present observer. It performs a focus change
only after the trusted kiosk has independently witnessed a matching MPV
surface and playback progress via OfflineHandover. A failed focus change
attempts to restore Chromium and leaves the policy in Chromium mode.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable

from .mpv_handover import OfflineHandover, HandoverError


class WaylandSwitchError(RuntimeError):
    pass


_ID = re.compile(r"[a-zA-Z0-9_.-]{1,90}")
_MPV_ID = re.compile(r"pi-player-mpv-[a-f0-9]{32}")


def _app_id(value: str, *, mpv: bool = False) -> str:
    if type(value) is not str or not (_MPV_ID if mpv else _ID).fullmatch(value):
        raise WaylandSwitchError("Untrusted Wayland application identity")
    return value


@dataclass(frozen=True)
class FocusResult:
    app_id: str
    focused: bool


class WlrctlFocus:
    """Minimal compositor focus request with active-window readback.

    The caller supplies a trusted, pre-verified app_id and ensures there is
    exactly one matching MPV surface. wlrctl does not prove first-frame
    presentation or a surface's process PID; use a real Wayland observer
    before issuing an MPV handover.
    """

    def __init__(self, binary: str = "/usr/bin/wlrctl",
                 runner: Callable = subprocess.run):
        if type(binary) is not str or not binary.startswith("/"):
            raise WaylandSwitchError("Trusted absolute wlrctl path required")
        self.binary = binary
        self.runner = runner

    def focus(self, app_id: str) -> FocusResult:
        target = _app_id(app_id)
        try:
            self.runner([self.binary, "toplevel", "focus", f"app_id:{target}"],
                        capture_output=True, text=True, timeout=2, check=True)
            report = self.runner(
                [self.binary, "toplevel", "list", "state:active"],
                capture_output=True, text=True, timeout=2, check=True)
        except (OSError, subprocess.CalledProcessError,
                subprocess.TimeoutExpired) as exc:
            raise WaylandSwitchError("Wayland focus command failed") from exc
        # wlrctl prints each entry's application id followed by a colon.
        # Matching only an exact app_id avoids a substring/title collision.
        active_ids = [line.split(":", 1)[0].strip()
                      for line in report.stdout.splitlines()
                      if ":" in line]
        return FocusResult(target, active_ids == [target])


class WaylandHandoverActuator:
    """One-way, explicitly reversible compositor focus policy."""

    def __init__(self, gate: OfflineHandover, focus: WlrctlFocus,
                 *, chromium_app_id: str):
        if not isinstance(gate, OfflineHandover) or not isinstance(focus, WlrctlFocus):
            raise WaylandSwitchError("Trusted kiosk gate and focus adapter required")
        self.gate, self.focus = gate, focus
        self.chromium_app_id = _app_id(chromium_app_id)

    def to_mpv(self, slot_id: str, child_id: str, entry_id: str,
               *, mpv_app_id: str) -> bool:
        target = _app_id(mpv_app_id, mpv=True)
        if not self.gate.ready(slot_id, child_id, entry_id):
            return False
        try:
            focused = self.focus.focus(target)
            if not focused.focused:
                raise WaylandSwitchError("MPV focus not confirmed")
            self.gate.commit_visible(slot_id, child_id, entry_id)
            return True
        except (WaylandSwitchError, HandoverError):
            self.restore_chromium()
            return False

    def restore_chromium(self) -> bool:
        """Attempt Chromium focus; never claim successful focus without proof."""
        try:
            result = self.focus.focus(self.chromium_app_id)
            return result.focused
        except WaylandSwitchError:
            return False
        finally:
            self.gate.rollback()

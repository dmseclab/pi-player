"""Phase 2B-4 offline display handover interlock. No graphical side effects.

Future compositor-side observers MUST construct the witnessed surface evidence.
Browser events, MPV progress telemetry or user-supplied JSON never prove it.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass


class HandoverError(ValueError):
    pass


@dataclass(frozen=True)
class SurfaceWitness:
    """Trusted kiosk/compositor observation; not an authentication token."""
    slot_id: str
    child_id: str
    surface_id: str
    visible: bool


class OfflineHandover:
    """Strict single-generation gate for fade/focus switching.

    Chromium remains authoritative until real process, media, and compositor
    evidence are independently correlated. This module makes NO UI calls.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._ticket = None
        self._progress = False
        self._surface = None
        self._state = "chromium"

    def begin(self, slot_id: str, child_id: str, entry_id: str) -> None:
        with self._lock:
            for value in (slot_id, child_id, entry_id):
                try:
                    if type(value) is not str or str(uuid.UUID(value)) != value:
                        raise ValueError()
                except ValueError as exc:
                    raise HandoverError("Invalid playback identity") from exc
            if self._state != "chromium" or self._ticket is not None:
                raise HandoverError("Another handover is in progress")
            self._ticket = (slot_id, child_id, entry_id)
            self._progress = False
            self._surface = None

    def note_progress(self, slot_id: str, child_id: str, entry_id: str,
                      *, advanced: bool) -> None:
        with self._lock:
            if self._ticket != (slot_id, child_id, entry_id):
                raise HandoverError("Stale playback progress evidence")
            if type(advanced) is not bool:
                raise HandoverError("Invalid progress evidence")
            self._progress = self._progress or advanced

    def note_surface(self, evidence: SurfaceWitness) -> None:
        with self._lock:
            if (not isinstance(evidence, SurfaceWitness)
                    or self._ticket is None
                    or (evidence.slot_id, evidence.child_id) != self._ticket[:2]
                    or type(evidence.visible) is not bool
                    or not evidence.visible or not evidence.surface_id):
                raise HandoverError("Untrusted or stale Wayland surface")
            self._surface = evidence.surface_id

    def ready(self, slot_id: str, child_id: str, entry_id: str) -> bool:
        with self._lock:
            if self._ticket != (slot_id, child_id, entry_id):
                return False
            return self._state == "chromium" and self._progress and self._surface is not None

    def commit_visible(self, slot_id: str, child_id: str, entry_id: str) -> None:
        """Trusted kiosk confirms compositor transition after readiness."""
        with self._lock:
            if not self.ready(slot_id, child_id, entry_id):
                raise HandoverError("MPV display takeover is not authorized")
            self._state = "mpv"

    def rollback(self) -> None:
        """Kiosk must actually restore Chromium; this only resets policy."""
        with self._lock:
            self._state = "chromium"
            self._ticket = None
            self._surface = None
            self._progress = False

    def snapshot(self):
        with self._lock:
            return {"display_owner": self._state, "pending": self._ticket is not None,
                    "progress": self._progress, "surface_ready": self._surface is not None}

"""Single-slot playback lifecycle for the existing playlist controller.

Transport-independent: no listener, process creation, or feature activation.
The trusted renderer owner supplies start/inspect/retire callbacks. Retirement
must prove the entire renderer is gone, not merely the helper's exit.
"""
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Callable
from uuid import uuid4


@dataclass
class Slot:
    ticket: str
    item_id: str
    generation: int
    lease_deadline: float
    startup_deadline: float
    handle: object = None
    phase: str = "starting"


class PlaybackBridge:
    def __init__(self, start: Callable, inspect: Callable, retire: Callable,
                 eligible: Callable, *, clock=monotonic):
        self.start_renderer = start
        self.inspect_renderer = inspect
        self.retire_renderer = retire
        self.eligible = eligible
        self.clock = clock
        self.lock = RLock()
        self.slot = None
        self.generation = -1
        self.owner = None

    def bind(self):
        """Trusted transport calls this after authenticating the kiosk."""
        with self.lock:
            if self.slot and not self._retire():
                raise RuntimeError("Renderer cleanup unverified")
            self.owner = uuid4().hex
            self.generation = -1
            return self.owner

    def _authorize(self, owner):
        if self.owner is None or owner != self.owner:
            raise PermissionError("Stale kiosk owner")

    def _retire(self):
        slot = self.slot
        if slot is None:
            return True
        slot.phase = "quarantined"
        try:
            clean = self.retire_renderer(slot.handle) is True
        except Exception:
            clean = False
        if clean:
            self.slot = None
        return clean

    def begin(self, owner, generation, item_id):
        with self.lock:
            self._authorize(owner)
            if type(generation) is not int or generation <= self.generation:
                raise ValueError("Stale playback generation")
            if self.slot is not None and not self._retire():
                raise RuntimeError("Renderer cleanup unverified")
            self.generation = generation
            grant = self.eligible(item_id)
            if grant is None:
                return {"state": "fallback", "clean": True}
            now = self.clock()
            slot = Slot(uuid4().hex, item_id, generation, now+15, now+30)
            self.slot = slot
            try:
                slot.handle = self.start_renderer(grant)
            except Exception:
                # Unknown launch outcome: retire callback must reconcile even
                # a missing handle before any fallback is authorized.
                clean = self._retire()
                return {"state": "fallback" if clean else "quarantined",
                        "clean": clean}
            return {"state": "starting", "ticket": slot.ticket}

    def _current(self, owner, ticket):
        self._authorize(owner)
        if self.slot is None or ticket != self.slot.ticket:
            raise ValueError("Stale playback ticket")
        return self.slot

    def poll(self, owner, ticket):
        with self.lock:
            slot = self._current(owner, ticket)
            now = self.clock()
            if slot.phase == "quarantined" or now >= slot.lease_deadline:
                return self._finish("fallback")
            try:
                if self.eligible(slot.item_id) is None:
                    return self._finish("cancelled")
                evidence = self.inspect_renderer(slot.handle)
                if evidence.get("failed") is True:
                    return self._finish("fallback")
                if evidence.get("eof") is True:
                    return self._finish("completed" if slot.phase == "playing" else "fallback")
                if slot.phase == "starting":
                    if now >= slot.startup_deadline:
                        return self._finish("fallback")
                    if evidence.get("progress") is True and evidence.get("surface") is True:
                        slot.phase = "playing"
                slot.lease_deadline = now+15
                return {"state": slot.phase, "ticket": ticket}
            except Exception:
                return self._finish("fallback")

    def _finish(self, state):
        clean = self._retire()
        return {"state": state if clean else "quarantined", "clean": clean}

    def cancel(self, owner, ticket):
        with self.lock:
            self._current(owner, ticket)
            return self._finish("cancelled")

    def tick(self):
        """Trusted owner timer MUST call independently of browser traffic."""
        with self.lock:
            if self.slot and (self.slot.phase == "quarantined" or
                              self.clock() >= self.slot.lease_deadline):
                return self._finish("fallback")
            return None

    def disconnect(self, owner):
        with self.lock:
            self._authorize(owner)
            self.owner = None
            return self._finish("cancelled")

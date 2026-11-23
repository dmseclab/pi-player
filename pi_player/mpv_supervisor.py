"""Offline MPV supervisor protocol and session state machine (NOT deployed).

There is deliberately no socket listener, HTTP endpoint, command executor,
browser bridge or service unit. A future trusted broker must authenticate peers
and construct authorised video grants before this logic can be used.
"""
from __future__ import annotations

import json
import math
import time
import uuid
import threading
from functools import wraps
from collections import deque
from dataclasses import dataclass
from typing import Literal

MAX_MESSAGE_BYTES = 4096
MAX_STARTUP_SECONDS = 30.0


class ProtocolError(ValueError):
    """Reject malformed, stale or unauthorised operations fail-closed."""


def _uuid(value: object, label: str) -> str:
    if type(value) is not str:
        raise ProtocolError(f"{label} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ProtocolError(f"{label} must be a UUID") from exc
    if str(parsed) != value:
        raise ProtocolError(f"{label} must use canonical UUID form")
    return value


def _revision(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise ProtocolError("Invalid playlist revision")
    if not all(ch.isalnum() or ch in "-_." for ch in value):
        raise ProtocolError("Invalid playlist revision")
    return value


def _generation(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ProtocolError("Invalid player generation")
    return value


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("Duplicate JSON field")
        result[key] = value
    return result


@dataclass(frozen=True)
class StartRequest:
    request_id: str
    item_id: str
    playlist_revision: str
    generation: int


@dataclass(frozen=True)
class StopRequest:
    request_id: str
    session_id: str
    playlist_revision: str
    generation: int


@dataclass(frozen=True)
class StatusRequest:
    request_id: str
    session_id: str


def parse_request(message: bytes) -> StartRequest | StopRequest | StatusRequest:
    """Strictly parse one bounded, versioned JSON message, without media paths."""
    if type(message) is not bytes or not 0 < len(message) <= MAX_MESSAGE_BYTES:
        raise ProtocolError("Invalid control message size")
    try:
        body = json.loads(message.decode("utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError("Invalid control message JSON") from exc
    if type(body) is not dict or body.get("version") != 1 or type(body.get("version")) is not int:
        raise ProtocolError("Unsupported control protocol version")
    action = body.get("action")
    if action == "start":
        if set(body) != {"version", "action", "request_id", "item_id", "playlist_revision", "generation"}:
            raise ProtocolError("Unexpected start fields")
        return StartRequest(_uuid(body["request_id"], "Request"),
                            _uuid(body["item_id"], "Item"),
                            _revision(body["playlist_revision"]),
                            _generation(body["generation"]))
    if action == "stop":
        if set(body) != {"version", "action", "request_id", "session_id", "playlist_revision", "generation"}:
            raise ProtocolError("Unexpected stop fields")
        return StopRequest(_uuid(body["request_id"], "Request"),
                           _uuid(body["session_id"], "Session"),
                           _revision(body["playlist_revision"]),
                           _generation(body["generation"]))
    if action == "status":
        if set(body) != {"version", "action", "request_id", "session_id"}:
            raise ProtocolError("Unexpected status fields")
        return StatusRequest(_uuid(body["request_id"], "Request"),
                             _uuid(body["session_id"], "Session"))
    raise ProtocolError("Unsupported control action")


@dataclass(frozen=True)
class AuthorizedVideo:
    """Broker result ONLY; constructing this object is not authentication."""
    item_id: str
    playlist_revision: str
    valid_until: float
    video: bool = True
    enabled: bool = True


@dataclass
class Session:
    session_id: str
    request: StartRequest
    loop: bool
    started_at: float
    startup_deadline: float
    state: Literal["starting", "playing"] = "starting"
    entry_id: int | None = None
    observed_progress: bool = False
    observed_surface: bool = False


def serialized(method):
    """All offline policy transitions share one owner lock."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return guarded


class OfflineSupervisor:
    """Side-effect-free policy engine for one MPV session.

    No process is launched; every observation must eventually come from the
    authenticated kiosk agent, not remote browser telemetry.
    """

    def __init__(self, *, startup_seconds: float = MAX_STARTUP_SECONDS):
        if type(startup_seconds) not in (int, float) or not 0 < startup_seconds <= 60 or not math.isfinite(startup_seconds):
            raise ValueError("Invalid startup deadline")
        self._lock = threading.RLock()
        self.startup_seconds = float(startup_seconds)
        self.active: Session | None = None
        self.last_terminal: dict | None = None
        self._used_requests: dict[str, str] = {}
        self._order = deque(maxlen=64)
        self._highest_generation = -1
        self._last_tick = None

    @staticmethod
    def _now(value: float | None) -> float:
        result = time.monotonic() if value is None else value
        if type(result) not in (int, float) or not 0 <= result <= 1e15 or not math.isfinite(result):
            raise ProtocolError("Invalid monotonic timestamp")
        return float(result)

    def _ordered_tick(self, tick: float) -> None:
        """Decisions use ordered, supervisor-owned monotonic time."""
        if self._last_tick is not None and tick < self._last_tick:
            raise ProtocolError("Backward monotonic supervisor timestamp")
        self._last_tick = tick

    @serialized
    def begin(self, request: StartRequest, grant: AuthorizedVideo, *,
              loop: bool = False, now: float | None = None) -> dict:
        tick = self._now(now)
        if not isinstance(request, StartRequest) or not isinstance(grant, AuthorizedVideo):
            raise ProtocolError("Start requires a broker grant")
        # Also validate callers that bypass the JSON parser (trusted Python code).
        _uuid(request.request_id, "Request")
        _uuid(request.item_id, "Item")
        _revision(request.playlist_revision)
        _generation(request.generation)
        if (type(loop) is not bool or type(grant.video) is not bool
                or type(grant.enabled) is not bool):
            raise ProtocolError("Invalid trusted playback options")
        _uuid(grant.item_id, "Grant item")
        _revision(grant.playlist_revision)
        if (type(grant.valid_until) not in (float, int)
                or not 0 <= grant.valid_until <= 1e15
                or not math.isfinite(grant.valid_until)):
            raise ProtocolError("Invalid broker grant deadline")
        if (not grant.video or not grant.enabled
                or grant.item_id != request.item_id
                or grant.playlist_revision != request.playlist_revision
                or tick >= grant.valid_until):
            raise ProtocolError("Video not authorised by current playlist")
        self._ordered_tick(tick)
        if request.request_id in self._used_requests:
            if (self.active and self.active.request == request
                    and self.active.loop == loop):
                if self.active.state == "starting" and tick >= self.active.startup_deadline:
                    self._finish("failed", "startup_timeout")
                    raise ProtocolError("MPV startup deadline expired")
                return self.snapshot(self.active.session_id)
            raise ProtocolError("Replayed or conflicting start request")
        if self.active is not None:
            raise ProtocolError("Renderer busy")
        # A bounded request cache is not an anti-replay guarantee. A monotonic
        # generation watermark survives eviction for this owner lifetime.
        if request.generation <= self._highest_generation:
            raise ProtocolError("Stale or replayed player generation")
        self.active = Session(uuid.uuid4().hex, request, loop, tick, tick + self.startup_seconds)
        # Store canonical UUID for the public session identity.
        self.active.session_id = str(uuid.UUID(hex=self.active.session_id))
        if len(self._order) == self._order.maxlen:
            self._used_requests.pop(self._order.popleft(), None)
        self._order.append(request.request_id)
        self._used_requests[request.request_id] = self.active.session_id
        self._highest_generation = request.generation
        return self.snapshot(self.active.session_id)

    def _session(self, session_id: str) -> Session:
        if self.active is None or self.active.session_id != session_id:
            raise ProtocolError("Stale or unknown supervisor session")
        return self.active

    @serialized
    def snapshot(self, session_id: str) -> dict:
        _uuid(session_id, "Session")
        current = self._session(session_id)
        return {"session_id": current.session_id, "item_id": current.request.item_id,
                "playlist_revision": current.request.playlist_revision,
                "generation": current.request.generation,
                "state": current.state, "ready": current.state == "playing",
                "eof": False}

    @serialized
    def observe_file(self, session_id: str, entry_id: int) -> None:
        _uuid(session_id, "Session")
        current = self._session(session_id)
        if type(entry_id) is not int or entry_id < 0:
            raise ProtocolError("Invalid MPV entry ID")
        if current.entry_id is not None and current.entry_id != entry_id:
            raise ProtocolError("Unexpected MPV entry change")
        current.entry_id = entry_id

    @serialized
    def observe_readiness(self, session_id: str, *, entry_id: int | None = None,
                          progressed: bool = False, surface_ready: bool = False,
                          now: float | None = None) -> dict:
        _uuid(session_id, "Session")
        tick = self._now(now)
        current = self._session(session_id)
        if type(progressed) is not bool or type(surface_ready) is not bool:
            raise ProtocolError("Invalid readiness evidence")
        if type(entry_id) is not int or current.entry_id is None or entry_id != current.entry_id:
            raise ProtocolError("Readiness does not match MPV file entry")
        self._ordered_tick(tick)
        if current.state == "starting" and tick >= current.startup_deadline:
            self._finish("failed", "startup_timeout")
            raise ProtocolError("MPV startup deadline expired")
        current.observed_progress |= progressed
        current.observed_surface |= surface_ready
        if current.observed_progress and current.observed_surface:
            current.state = "playing"
        return self.snapshot(session_id)

    @serialized
    def expire_startup(self, *, now: float | None = None) -> dict | None:
        tick = self._now(now)
        self._ordered_tick(tick)
        if (self.active is not None and self.active.state == "starting"
                and tick >= self.active.startup_deadline):
            return self._finish("failed", "startup_timeout")
        return None

    @serialized
    def end_file(self, session_id: str, entry_id: int, reason: str) -> dict | None:
        _uuid(session_id, "Session")
        if type(reason) is not str or reason not in {"eof", "error", "stop", "quit", "redirect"}:
            raise ProtocolError("Invalid MPV end-file reason")
        current = self._session(session_id)
        if type(entry_id) is not int or entry_id != current.entry_id:
            raise ProtocolError("Late or wrong MPV end-file event")
        if reason == "eof" and current.loop:
            return None  # Chromium's duration timer controls looping items.
        if reason == "eof" and current.state == "playing":
            return self._finish("completed", "eof")
        if reason in {"stop", "quit"}:
            return self._finish("interrupted", reason)
        return self._finish("failed", "unverified_eof" if reason == "eof" else "mpv_error")

    @serialized
    def stop(self, request: StopRequest) -> dict:
        if not isinstance(request, StopRequest):
            raise ProtocolError("Invalid stop command")
        _uuid(request.request_id, "Request")
        _uuid(request.session_id, "Session")
        _revision(request.playlist_revision)
        _generation(request.generation)
        current = self._session(request.session_id)
        if (request.generation != current.request.generation
                or request.playlist_revision != current.request.playlist_revision):
            raise ProtocolError("Stop belongs to another playlist generation")
        return self._finish("interrupted", "requested_stop")

    def _finish(self, state: str, reason: str) -> dict:
        current = self.active
        if current is None:
            raise ProtocolError("No active session to finish")
        result = {"session_id": current.session_id, "item_id": current.request.item_id,
                  "playlist_revision": current.request.playlist_revision,
                  "generation": current.request.generation,
                  "state": state, "reason": reason,
                  "eof": state == "completed"}
        self.active = None
        self.last_terminal = result
        return dict(result)

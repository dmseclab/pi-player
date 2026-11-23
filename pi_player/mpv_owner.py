"""Offline Phase 2B-1 owner-epoch and renderer-slot policy (NOT deployed).

This is NOT a peer authenticator, process monitor, media broker, or a service.
Its methods must be driven exclusively by a future trusted, serialized kiosk
supervisor. In particular, reconcile_empty and confirm_exit are assertions
from a trusted local process/cgroup inspector, not browser commands.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import uuid
from dataclasses import dataclass
from typing import Literal


class OwnerError(ValueError):
    """Invalid lease, stale owner, or unsafe renderer transition."""


def _canonical_uuid(value: object, label: str) -> str:
    if type(value) is not str:
        raise OwnerError(f"Invalid {label}")
    try:
        if str(uuid.UUID(value)) != value:
            raise OwnerError(f"Invalid {label}")
    except ValueError as exc:
        raise OwnerError(f"Invalid {label}") from exc
    return value


@dataclass(frozen=True)
class OwnerLease:
    owner_id: str
    epoch: str = __import__('dataclasses').field(repr=False)


@dataclass(frozen=True)
class RendererSlot:
    slot_id: str
    state: Literal["reserved", "running", "quarantined"]
    child_id: str | None = None


class OfflineOwner:
    """A locked policy model; an actual supervisor must own all side effects.

    Starts unreconciled: no new renderer is permitted until a trusted startup
    inspection confirms the previous cgroup/process inventory is empty.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._reconciled = False
        self._lease: OwnerLease | None = None
        self._slot: RendererSlot | None = None

    def _require(self, lease: OwnerLease) -> None:
        if not isinstance(lease, OwnerLease):
            raise OwnerError("Invalid owner lease")
        _canonical_uuid(lease.owner_id, "owner ID")
        if (type(lease.epoch) is not str or len(lease.epoch) != 64
                or any(ch not in "0123456789abcdef" for ch in lease.epoch)):
            raise OwnerError("Invalid owner epoch")
        current = self._lease
        if (current is None or lease.owner_id != current.owner_id
                or not hmac.compare_digest(lease.epoch, current.epoch)):
            raise OwnerError("Stale or replaced owner lease")

    def snapshot(self) -> dict:
        with self._lock:
            return {"reconciled": self._reconciled,
                    "owner_active": self._lease is not None,
                    "slot_state": "empty" if self._slot is None else self._slot.state,
                    "slot_id": None if self._slot is None else self._slot.slot_id}
        # Never expose lease secrets or trusted child handles in snapshots.

    def reconcile_empty(self) -> None:
        """TRUSTED inspector only; allowed only when no slot is retained."""
        with self._lock:
            if self._slot is not None:
                raise OwnerError("Renderer still owned; cannot reconcile empty")
            self._reconciled = True

    def replace_owner(self, owner_id: str) -> OwnerLease:
        """Mint a fresh epoch; fence the prior owner even if its ID is reused."""
        with self._lock:
            _canonical_uuid(owner_id, "owner ID")
            self._lease = OwnerLease(owner_id, secrets.token_hex(32))
            if self._slot is not None:
                self._slot = RendererSlot(
                    self._slot.slot_id, "quarantined", self._slot.child_id)
            return self._lease

    def revoke_owner(self, lease: OwnerLease) -> None:
        with self._lock:
            self._require(lease)
            self._lease = None
            if self._slot is not None:
                self._slot = RendererSlot(
                    self._slot.slot_id, "quarantined", self._slot.child_id)

    def reserve(self, lease: OwnerLease) -> str:
        """Do not reserve during unknown startup state or prior child cleanup."""
        with self._lock:
            self._require(lease)
            if not self._reconciled or self._slot is not None:
                raise OwnerError("Renderer unavailable or unreconciled")
            slot_id = str(uuid.uuid4())
            self._slot = RendererSlot(slot_id, "reserved")
            return slot_id

    def mark_spawned(self, lease: OwnerLease, slot_id: str,
                     child_id: str) -> None:
        """TRUSTED launcher only: bind process identity before playback."""
        with self._lock:
            self._require(lease)
            _canonical_uuid(slot_id, "slot ID")
            _canonical_uuid(child_id, "child ID")
            if (self._slot is None or self._slot.slot_id != slot_id
                    or self._slot.state != "reserved"):
                raise OwnerError("Cannot bind child to renderer slot")
            self._slot = RendererSlot(slot_id, "running", child_id)

    def acknowledge_late_spawn(self, slot_id: str, child_id: str) -> None:
        """TRUSTED launcher only: account for a child after quarantine/takeover.

        This is not an old-owner command. The kiosk's serialized launch
        coordinator must bind the original slot to the original spawn attempt
        and verify child identity. Never grant playback authority here.
        """
        with self._lock:
            _canonical_uuid(slot_id, "slot ID")
            _canonical_uuid(child_id, "child ID")
            if (self._slot is None or self._slot.slot_id != slot_id
                    or self._slot.state != "quarantined"
                    or self._slot.child_id is not None):
                raise OwnerError("Late child acknowledgement denied")
            self._slot = RendererSlot(slot_id, "quarantined", child_id)

    def quarantine(self, slot_id: str) -> None:
        """TRUSTED supervisor: timeout, IPC loss, stop or unknown child state."""
        with self._lock:
            _canonical_uuid(slot_id, "slot ID")
            if self._slot is None or self._slot.slot_id != slot_id:
                raise OwnerError("Unknown renderer slot")
            self._slot = RendererSlot(slot_id, "quarantined", self._slot.child_id)

    def cancel_unspawned(self, slot_id: str, *, launch_ruled_out: bool) -> None:
        """TRUSTED launcher: release only once a spawn race is ruled out."""
        with self._lock:
            _canonical_uuid(slot_id, "slot ID")
            if type(launch_ruled_out) is not bool or not launch_ruled_out:
                raise OwnerError("Launch not proved absent")
            if (self._slot is None or self._slot.slot_id != slot_id
                    or self._slot.child_id is not None
                    or self._slot.state not in ("reserved", "quarantined")):
                raise OwnerError("Unspawned renderer release denied")
            self._slot = None

    def confirm_exit(self, slot_id: str, child_id: str, *,
                     group_empty: bool) -> None:
        """TRUSTED reaper: child exit AND verified empty cgroup required."""
        with self._lock:
            _canonical_uuid(slot_id, "slot ID")
            _canonical_uuid(child_id, "child ID")
            if type(group_empty) is not bool or not group_empty:
                raise OwnerError("Process group still occupied or unverified")
            if (self._slot is None or self._slot.slot_id != slot_id
                    or self._slot.child_id != child_id
                    or self._slot.state not in ("running", "quarantined")):
                raise OwnerError("Exit identity does not match renderer")
            self._slot = None

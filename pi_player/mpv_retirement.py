"""Feature-disabled MPV process retirement coordinator.

The trusted launcher exclusively owns child identities; these methods are
unavailable through the browser/API. Never treat PID disappearance or return
code zero as natural EOF, and never release a renderer with a populated or
unverifiable cgroup.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from .mpv_owner import OfflineOwner, OwnerLease, OwnerError
from .mpv_process_evidence import GroupEvidence, EvidenceError


class RetirementError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChildRecord:
    slot_id: str
    child_id: str
    pid: int
    started: bool = True


class OfflineProcessRetirement:
    """Serializes tracked child exit, cgroup inspection and owner release.

    The inspector must be supplied by a trusted launcher that owns a dedicated
    immutable cgroup path. No process is started/killed by this module.
    """

    def __init__(self, owner: OfflineOwner,
                 evidence: Callable[[], GroupEvidence]):
        if not isinstance(owner, OfflineOwner) or not callable(evidence):
            raise TypeError("Trusted owner and evidence inspector required")
        self.owner = owner
        self.evidence = evidence
        self._lock = threading.RLock()
        self._child: ChildRecord | None = None
        self._exit_witnessed = False
        self._launcher_quiescent = False

    def bind_child(self, lease: OwnerLease, slot_id: str,
                   child_id: str, pid: int) -> None:
        with self._lock:
            if type(pid) is not int or pid < 1 or self._child is not None:
                raise RetirementError("Invalid or overlapping process registration")
            self.owner.mark_spawned(lease, slot_id, child_id)
            self._child = ChildRecord(slot_id, child_id, pid)
            self._exit_witnessed = False
            self._launcher_quiescent = False

    def launcher_quiescent(self, child_id: str) -> None:
        """Trusted launcher has ruled out late, overlapping child creation."""
        with self._lock:
            if self._child is None or self._child.child_id != child_id:
                raise RetirementError("Unknown launcher identity")
            self._launcher_quiescent = True

    def witnessed_exit(self, child_id: str, pid: int) -> None:
        """Trusted waitpid/pidfd observer witnessed this exact child exit."""
        with self._lock:
            if (self._child is None or self._child.child_id != child_id
                    or self._child.pid != pid):
                raise RetirementError("Unrecognized child exit")
            self._exit_witnessed = True

    def retire(self, child_id: str) -> None:
        with self._lock:
            child = self._child
            if (child is None or child.child_id != child_id
                    or not self._exit_witnessed or not self._launcher_quiescent):
                raise RetirementError("Child exit and launch closure unverified")
            try:
                evidence = self.evidence()
            except (OSError, EvidenceError) as exc:
                raise RetirementError("Cgroup inventory unavailable") from exc
            if not isinstance(evidence, GroupEvidence) or not evidence.empty:
                raise RetirementError("Cgroup not proven empty")
            self.owner.confirm_exit(child.slot_id, child.child_id,
                                    group_empty=True)
            self._child = None
            self._exit_witnessed = False
            self._launcher_quiescent = False

    def snapshot(self) -> dict:
        with self._lock:
            return {"tracked": self._child is not None,
                    "exit_witnessed": self._exit_witnessed,
                    "launch_closed": self._launcher_quiescent}

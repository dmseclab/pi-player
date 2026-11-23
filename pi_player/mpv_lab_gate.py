"""Read-only Phase 2B laboratory gate. It never enables hybrid playback.

A capability report is NOT permission to start MPV. Operator acceptance of
visual output, watchdog recovery and physical power-loss tests is separate.
"""
from __future__ import annotations

import os
import pwd
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    detail: str


def evaluate(facts: dict) -> tuple[Gate, ...]:
    """Pure, deterministic checklist: missing evidence always fails closed."""
    required = ("api_uid", "kiosk_uid", "broker_uid", "service_api_uid",
                "service_kiosk_uid", "cgroup_v2", "wayland",
                "mpv_binary", "kernel_healthy", "production_freeze",
                "verified_restore_plan", "feature_enabled")
    if not isinstance(facts, dict) or any(k not in facts for k in required):
        raise ValueError("Missing required lab facts")
    uid_keys = ("api_uid", "kiosk_uid", "broker_uid",
                "service_api_uid", "service_kiosk_uid")
    valid_uids = all(type(facts[k]) is int and facts[k] >= 0 for k in uid_keys)
    separate = (valid_uids
                and len({facts["api_uid"], facts["kiosk_uid"],
                         facts["broker_uid"]}) == 3
                and facts["api_uid"] == facts["service_api_uid"]
                and facts["kiosk_uid"] == facts["service_kiosk_uid"])
    result = (
        Gate("separate_accounts", separate, "API, kiosk and broker must have distinct verified UIDs"),
        Gate("kernel_cgroup_v2", facts["cgroup_v2"] is True,
             "cgroup v2 inventory is required for child cleanup"),
        Gate("wayland_compositor", facts["wayland"] is True,
             "trusted compositor-side readiness still requires a separate probe"),
        Gate("mpv_available", facts["mpv_binary"] is True,
             "mpv binary must be present before any opt-in video test"),
        Gate("kernel_health", facts["kernel_healthy"] is True,
             "no relevant blocked-task/kernel faults in observed baseline"),
        Gate("construction_frozen", facts["production_freeze"] is True,
             "no changes to Construction or main"),
        Gate("rollback_ready", facts["verified_restore_plan"] is True,
             "operator-verified lab backup and Chromium fallback"),
        Gate("hybrid_disabled", facts["feature_enabled"] is False,
             "hybrid feature remains off until an explicit lab approval"),
    )
    return result


def readiness(facts: dict) -> bool:
    """All checkboxes must pass; this only permits *planning* the lab trial."""
    return all(g.passed for g in evaluate(facts))


def parse_service_uid(text: str) -> str | None:
    """Parse a systemd unit's User= without starting/changing services."""
    if type(text) is not str:
        return None
    users = [line.partition("=")[2].strip() for line in text.splitlines()
             if line.strip().startswith("User=")]
    return users[-1] if users else None


def inspect_source_units(api_text: str, kiosk_text: str) -> tuple[Gate, ...]:
    """Offline source-level check, independent of installed systemd state."""
    api = parse_service_uid(api_text)
    kiosk = parse_service_uid(kiosk_text)
    return (
        Gate("api_identity_declared", bool(api), "API service declares User="),
        Gate("kiosk_identity_declared", bool(kiosk), "Kiosk service declares User="),
        Gate("source_account_separation",
             bool(api and kiosk and api != kiosk),
             "API and kiosk source units must not share a Unix identity"),
    )

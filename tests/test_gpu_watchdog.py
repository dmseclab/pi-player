"""Regression tests for conservative GPU watchdog recovery policy."""
import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "deploy" / "pi-player-gpu-watchdog.py"
spec = importlib.util.spec_from_file_location("gpu_watchdog", MODULE)
watchdog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watchdog)

HIGH = [{"pid": 123, "fds": 1300, "chromium_shm": 1250}]
LOW = [{"pid": 123, "fds": 70, "chromium_shm": 25}]


def test_only_sustained_high_samples_trigger_recovery():
    state = {}
    for n in range(1, 4):
        state, action = watchdog.next_state(state, HIGH, [], 10000 + n * 60, "boot1")
        assert action is (n == 3)
    assert state["high_samples"] == 0


def test_low_sample_resets_counter():
    state, _ = watchdog.next_state({}, HIGH, [], 10000, "boot1")
    state, action = watchdog.next_state(state, LOW, [], 10060, "boot1")
    assert not action
    assert state["high_samples"] == 0


def test_blocked_tasks_prevent_restart():
    state = {}
    for n in range(4):
        state, action = watchdog.next_state(state, HIGH, [88], 10000 + n * 60, "boot1")
        assert not action


def test_cooldown_and_daily_limit():
    state = {}
    first = 100000
    for n in range(3):
        state, action = watchdog.next_state(state, HIGH, [], first + n * 60, "boot1")
    assert action
    for n in range(3):
        state, action = watchdog.next_state(state, HIGH, [], first + 600 + n * 60, "boot1")
        assert not action
    second = first + 6 * 3600 + 300
    state, action = watchdog.next_state(state, HIGH, [], second, "boot1")
    assert action
    state, action = watchdog.next_state(state, HIGH, [], second + 6 * 3600 + 300, "boot1")
    assert not action


def test_boot_change_resets_sample_count():
    state, _ = watchdog.next_state({}, HIGH, [], 10000, "boot1")
    state, action = watchdog.next_state(state, HIGH, [], 10060, "boot2")
    assert not action
    assert state["high_samples"] == 1

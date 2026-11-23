"""Offline MPV supervisor protocol: no network, API, MPV or kiosk effects."""
import json
import unittest
import uuid

from pi_player.mpv_supervisor import (
    MAX_MESSAGE_BYTES, AuthorizedVideo, OfflineSupervisor, ProtocolError,
    StartRequest, StopRequest, StatusRequest, parse_request,
)


def ident():
    return str(uuid.uuid4())


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.start = dict(version=1, action="start", request_id=ident(),
                          item_id=ident(), playlist_revision="r.1", generation=7)

    def test_start_stop_status_decoding(self):
        start = parse_request(json.dumps(self.start).encode())
        self.assertIsInstance(start, StartRequest)
        stop = dict(version=1, action="stop", request_id=ident(),
                    session_id=ident(), playlist_revision="r.1", generation=7)
        status = dict(version=1, action="status", request_id=ident(), session_id=ident())
        self.assertIsInstance(parse_request(json.dumps(stop).encode()), StopRequest)
        self.assertIsInstance(parse_request(json.dumps(status).encode()), StatusRequest)

    def test_reject_unknown_fields_paths_and_unsupported_actions(self):
        for field in ("path", "url", "mpv_args", "command"):
            with self.subTest(field=field):
                self.assert_invalid({**self.start, field: "/etc/passwd"})
        self.assert_invalid({**self.start, "action": "reboot"})
        self.assert_invalid({**self.start, "version": True})
        self.assert_invalid({**self.start, "generation": True})

    def test_invalid_ids_and_revisions(self):
        for key, value in (
            ("request_id", "not-uuid"), ("item_id", "bad-id"),
            ("playlist_revision", "../foo"), ("playlist_revision", ""),
            ("generation", -1), ("generation", 2**53),
        ):
            with self.subTest(key=key, value=value):
                self.assert_invalid({**self.start, key: value})

    def test_duplicate_nonobject_and_oversize(self):
        for payload in (b'{"version":1,"version":1}', b"[]", b"null",
                        b"{not-json", b"", b" " * (MAX_MESSAGE_BYTES + 1)):
            with self.subTest(payload=payload[:30]):
                with self.assertRaises(ProtocolError):
                    parse_request(payload)

    def assert_invalid(self, data):
        with self.assertRaises(ProtocolError):
            parse_request(json.dumps(data).encode())


class StateTests(unittest.TestCase):
    def setUp(self):
        self.item = ident()
        self.start = StartRequest(ident(), self.item, "revision_1", 42)
        self.grant = AuthorizedVideo(self.item, "revision_1", valid_until=100)
        self.engine = OfflineSupervisor()

    def begin(self, loop=False):
        result = self.engine.begin(self.start, self.grant, loop=loop, now=1)
        return result["session_id"]

    def test_invalid_startup_duration_always_raises_value_error(self):
        # Oversized integers must be rejected before math.isfinite converts to float.
        for value in (10**1000, -(10**1000), True, False, 0,
                      -1, 60.001, float("inf"), -float("inf"),
                      float("nan"), "30", None):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                OfflineSupervisor(startup_seconds=value)
        self.assertEqual(OfflineSupervisor(startup_seconds=30).startup_seconds, 30.0)

    def test_denied_or_expired_grants_never_create_session(self):
        for grant in (
            AuthorizedVideo(ident(), "revision_1", 100),
            AuthorizedVideo(self.item, "wrong", 100),
            AuthorizedVideo(self.item, "revision_1", 100, video=False),
            AuthorizedVideo(self.item, "revision_1", 100, enabled=False),
            AuthorizedVideo(self.item, "revision_1", 1),
        ):
            with self.subTest(grant=grant):
                with self.assertRaises(ProtocolError):
                    self.engine.begin(self.start, grant, now=1)
                self.assertIsNone(self.engine.active)

    def test_malformed_direct_grants_and_requests_rejected(self):
        invalid_grants = [
            AuthorizedVideo(self.item, "revision_1", valid_until="tomorrow"),
            AuthorizedVideo(self.item, "revision_1", valid_until=float("nan")),
            AuthorizedVideo(self.item, "revision_1", valid_until=100, video=1),
            AuthorizedVideo(self.item, "revision_1", valid_until=100, enabled=1),
        ]
        for grant in invalid_grants:
            with self.subTest(grant=grant), self.assertRaises(ProtocolError):
                self.engine.begin(self.start, grant, now=1)
        invalid = StartRequest("not-a-uuid", self.item, "revision_1", 42)
        with self.assertRaises(ProtocolError):
            self.engine.begin(invalid, self.grant, now=1)
        self.assertIsNone(self.engine.active)

    def test_readiness_requires_file_progress_and_surface(self):
        session = self.begin()
        self.assertFalse(self.engine.snapshot(session)["ready"])
        with self.assertRaises(ProtocolError):
            self.engine.observe_readiness(session, entry_id=5, progressed=True, now=2)
        self.engine.observe_file(session, 5)
        self.assertFalse(self.engine.observe_readiness(session, entry_id=5, progressed=True, now=2)["ready"])
        self.assertTrue(self.engine.observe_readiness(session, entry_id=5, surface_ready=True, now=2)["ready"])

    def test_natural_eof_only_for_ready_entry_once(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        with self.assertRaises(ProtocolError):
            self.engine.end_file(session, 6, "eof")
        self.engine.observe_readiness(session, entry_id=5, progressed=True, surface_ready=True, now=2)
        completed = self.engine.end_file(session, 5, "eof")
        self.assertTrue(completed["eof"])
        self.assertEqual(completed["state"], "completed")
        with self.assertRaises(ProtocolError):
            self.engine.end_file(session, 5, "eof")

    def test_unready_eof_not_completion(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        result = self.engine.end_file(session, 5, "eof")
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["eof"])

    def test_loop_ignores_eof_until_owner_timing_stop(self):
        session = self.begin(loop=True)
        self.engine.observe_file(session, 5)
        self.engine.observe_readiness(session, entry_id=5, progressed=True, surface_ready=True, now=2)
        self.assertIsNone(self.engine.end_file(session, 5, "eof"))
        self.assertTrue(self.engine.snapshot(session)["ready"])
        stopped = self.engine.stop(StopRequest(ident(), session, "revision_1", 42))
        self.assertEqual(stopped["state"], "interrupted")
        self.assertFalse(stopped["eof"])

    def test_error_not_eof(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        self.engine.observe_readiness(session, entry_id=5, progressed=True, surface_ready=True, now=2)
        result = self.engine.end_file(session, 5, "error")
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["eof"])

    def test_start_deadline_and_replay_rejection(self):
        session = self.begin()
        self.assertEqual(self.engine.begin(self.start, self.grant, now=2)["session_id"], session)
        self.assertIsNone(self.engine.expire_startup(now=30))
        timed_out = self.engine.expire_startup(now=31)
        self.assertEqual(timed_out["reason"], "startup_timeout")
        with self.assertRaises(ProtocolError):
            self.engine.begin(self.start, self.grant, now=32)

    def test_stale_stop_generation_and_session_denied(self):
        session = self.begin()
        for request in (
            StopRequest(ident(), session, "revision_1", 43),
            StopRequest(ident(), session, "other", 42),
            StopRequest(ident(), ident(), "revision_1", 42),
        ):
            with self.assertRaises(ProtocolError):
                self.engine.stop(request)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")
        self.engine.stop(StopRequest(ident(), session, "revision_1", 42))
        with self.assertRaises(ProtocolError):
            self.engine.stop(StopRequest(ident(), session, "revision_1", 42))

    def test_busy_different_request_cannot_replace_session(self):
        session = self.begin()
        other = StartRequest(ident(), self.item, "revision_1", 43)
        with self.assertRaises(ProtocolError):
            self.engine.begin(other, self.grant, now=2)
        self.assertEqual(self.engine.snapshot(session)["generation"], 42)

    def test_readiness_at_deadline_rejected_even_before_timer(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        with self.assertRaisesRegex(ProtocolError, "deadline"):
            self.engine.observe_readiness(session, entry_id=5, progressed=True,
                                          surface_ready=True, now=31)
        self.assertIsNone(self.engine.active)
        self.assertEqual(self.engine.last_terminal["reason"], "startup_timeout")

    def test_readiness_wrong_entry_does_not_latch_evidence(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        with self.assertRaises(ProtocolError):
            self.engine.observe_readiness(session, entry_id=6, progressed=True, now=2)
        self.assertFalse(self.engine.observe_readiness(
            session, entry_id=5, surface_ready=True, now=2)["ready"])
        self.assertTrue(self.engine.observe_readiness(
            session, entry_id=5, progressed=True, now=2)["ready"])

    def test_stale_generation_rejected_even_after_cache_eviction(self):
        self.begin()
        self.engine.stop(StopRequest(ident(), self.engine.active.session_id,
                                     "revision_1", 42))
        for generation in range(43, 110):
            request = StartRequest(ident(), self.item, "revision_1", generation)
            session = self.engine.begin(request, self.grant, now=2)["session_id"]
            self.engine.stop(StopRequest(ident(), session, "revision_1", generation))
        with self.assertRaises(ProtocolError):
            self.engine.begin(self.start, self.grant, now=3)
        lower = StartRequest(ident(), self.item, "revision_1", 42)
        with self.assertRaises(ProtocolError):
            self.engine.begin(lower, self.grant, now=3)

    def test_duplicate_requires_fresh_grant_and_same_options(self):
        session = self.begin()
        with self.assertRaises(ProtocolError):
            self.engine.begin(self.start, self.grant, loop=True, now=2)
        with self.assertRaises(ProtocolError):
            self.engine.begin(self.start, AuthorizedVideo(
                self.item, "revision_1", valid_until=2), now=2)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")

    def test_direct_stop_rejects_boolean_generation_and_bad_id(self):
        session = self.begin()
        for request in (
            StopRequest(ident(), session, "revision_1", True),
            StopRequest("not-uuid", session, "revision_1", 42),
        ):
            with self.assertRaises(ProtocolError):
                self.engine.stop(request)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")

    def test_end_file_rejects_bad_reason_without_terminal_transition(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        for reason in (True, 0, None, "bad"):
            with self.assertRaises(ProtocolError):
                self.engine.end_file(session, 5, reason)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")

    def test_two_simultaneous_starts_one_winner(self):
        import threading
        barrier = threading.Barrier(3)
        results = []
        results_lock = threading.Lock()
        def attempt(generation):
            request = StartRequest(ident(), self.item, "revision_1", generation)
            barrier.wait()
            try:
                value = self.engine.begin(request, self.grant, now=2)
                outcome = ("ok", value["session_id"])
            except ProtocolError:
                outcome = ("rejected", None)
            with results_lock:
                results.append(outcome)
        threads = [threading.Thread(target=attempt, args=(n,)) for n in (42, 43)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(x[0] for x in results), ["ok", "rejected"])

    def test_late_events_do_not_affect_replacement(self):
        first = self.begin()
        self.engine.stop(StopRequest(ident(), first, "revision_1", 42))
        fresh = StartRequest(ident(), self.item, "revision_1", 43)
        second = self.engine.begin(fresh, self.grant, now=2)["session_id"]
        with self.assertRaises(ProtocolError):
            self.engine.observe_file(first, 5)
        with self.assertRaises(ProtocolError):
            self.engine.end_file(first, 5, "eof")
        self.assertEqual(self.engine.snapshot(second)["state"], "starting")

    def test_fractional_startup_deadline_all_transitions(self):
        for action in ("duplicate", "readiness", "expiry"):
            with self.subTest(action=action):
                engine = OfflineSupervisor()
                request = StartRequest(ident(), self.item, "revision_1", 42)
                session = engine.begin(request, self.grant, now=2.001)["session_id"]
                engine.observe_file(session, 5)
                deadline = engine.active.startup_deadline
                self.assertEqual(deadline, 32.001)
                if action == "duplicate":
                    with self.assertRaisesRegex(ProtocolError, "deadline"):
                        engine.begin(request, self.grant, now=deadline)
                elif action == "readiness":
                    with self.assertRaisesRegex(ProtocolError, "deadline"):
                        engine.observe_readiness(
                            session, entry_id=5, progressed=True,
                            surface_ready=True, now=deadline)
                else:
                    self.assertEqual(engine.expire_startup(now=deadline)["reason"],
                                     "startup_timeout")
                self.assertIsNone(engine.active)
                self.assertEqual(engine.last_terminal["reason"], "startup_timeout")

    def test_backwards_evidence_rejected_without_latching(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        self.engine.observe_readiness(session, entry_id=5, progressed=True, now=8)
        with self.assertRaisesRegex(ProtocolError, "Backward"):
            self.engine.observe_readiness(session, entry_id=5, surface_ready=True, now=7)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")
        self.assertFalse(self.engine.active.observed_surface)
        self.assertTrue(self.engine.observe_readiness(
            session, entry_id=5, surface_ready=True, now=9)["ready"])

    def test_pre_session_evidence_rejected(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        with self.assertRaisesRegex(ProtocolError, "Backward"):
            self.engine.observe_readiness(
                session, entry_id=5, progressed=True, surface_ready=True, now=0.999)
        self.assertFalse(self.engine.active.observed_progress)
        self.assertFalse(self.engine.active.observed_surface)

    def test_backward_duplicate_and_expiry_do_not_mutate(self):
        session = self.begin()
        with self.assertRaisesRegex(ProtocolError, "Backward"):
            self.engine.begin(self.start, self.grant, now=0.5)
        with self.assertRaisesRegex(ProtocolError, "Backward"):
            self.engine.expire_startup(now=0.5)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")
        self.assertIsNone(self.engine.expire_startup(now=2))

    def test_stale_readiness_after_timer_tick_rejected(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        self.assertIsNone(self.engine.expire_startup(now=5))
        with self.assertRaisesRegex(ProtocolError, "Backward"):
            self.engine.observe_readiness(session, entry_id=5, progressed=True, now=4)
        self.assertFalse(self.engine.active.observed_progress)

    def test_forced_ordered_race_rejects_older_evidence(self):
        import threading
        gate = threading.Event()
        results = []
        session = self.begin()
        self.engine.observe_file(session, 5)
        def later():
            self.engine.observe_readiness(session, entry_id=5, progressed=True, now=8)
            gate.set()
        def earlier():
            if not gate.wait(3):
                results.append("timeout")
                return
            try:
                self.engine.observe_readiness(session, entry_id=5, surface_ready=True, now=7)
                results.append("accepted")
            except ProtocolError:
                results.append("rejected")
        threads = [threading.Thread(target=later), threading.Thread(target=earlier)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["rejected"])
        self.assertFalse(self.engine.active.observed_surface)
        self.assertEqual(self.engine.snapshot(session)["state"], "starting")


if __name__ == "__main__":
    unittest.main()

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

    def test_readiness_requires_file_progress_and_surface(self):
        session = self.begin()
        self.assertFalse(self.engine.snapshot(session)["ready"])
        with self.assertRaises(ProtocolError):
            self.engine.observe_readiness(session, progressed=True)
        self.engine.observe_file(session, 5)
        self.assertFalse(self.engine.observe_readiness(session, progressed=True)["ready"])
        self.assertTrue(self.engine.observe_readiness(session, surface_ready=True)["ready"])

    def test_natural_eof_only_for_ready_entry_once(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        with self.assertRaises(ProtocolError):
            self.engine.end_file(session, 6, "eof")
        self.engine.observe_readiness(session, progressed=True, surface_ready=True)
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
        self.engine.observe_readiness(session, progressed=True, surface_ready=True)
        self.assertIsNone(self.engine.end_file(session, 5, "eof"))
        self.assertTrue(self.engine.snapshot(session)["ready"])
        stopped = self.engine.stop(StopRequest(ident(), session, "revision_1", 42))
        self.assertEqual(stopped["state"], "interrupted")
        self.assertFalse(stopped["eof"])

    def test_error_not_eof(self):
        session = self.begin()
        self.engine.observe_file(session, 5)
        self.engine.observe_readiness(session, progressed=True, surface_ready=True)
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


if __name__ == "__main__":
    unittest.main()

import unittest
from pi_player.mpv_playback_bridge import PlaybackBridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.clean = True
        self.grant = object()
        self.evidence = {}
        self.started = []
        self.retired = []
        self.bridge = PlaybackBridge(self.start, lambda h: self.evidence,
                                     self.retire, lambda i: self.grant,
                                     clock=lambda: self.now)
        self.owner = self.bridge.bind()

    def start(self, grant):
        self.started.append(grant)
        return object()

    def retire(self, handle):
        self.retired.append(handle)
        return self.clean

    def begin(self, generation=1):
        return self.bridge.begin(self.owner, generation, "item")

    def test_progress_alone_does_not_prove_surface(self):
        ticket = self.begin()["ticket"]
        self.evidence = {"progress": True}
        self.assertEqual(self.bridge.poll(self.owner, ticket)["state"], "starting")
        self.evidence["surface"] = True
        self.assertEqual(self.bridge.poll(self.owner, ticket)["state"], "playing")
        self.evidence = {"eof": True}
        self.assertEqual(self.bridge.poll(self.owner, ticket),
                         {"state": "completed", "clean": True})

    def test_expired_lease_retires_without_browser(self):
        self.begin()
        self.now = 15
        self.assertEqual(self.bridge.tick(), {"state": "fallback", "clean": True})

    def test_unverified_cleanup_blocks_next_start(self):
        ticket = self.begin()["ticket"]
        self.clean = False
        self.assertEqual(self.bridge.cancel(self.owner, ticket)["state"], "quarantined")
        with self.assertRaises(RuntimeError):
            self.begin(2)
        self.assertEqual(len(self.started), 1)
        self.clean = True
        self.bridge.tick()
        self.assertEqual(self.begin(2)["state"], "starting")

    def test_old_owner_and_generation_rejected(self):
        self.begin()
        with self.assertRaises(ValueError):
            self.begin()
        old = self.owner
        self.owner = self.bridge.bind()
        with self.assertRaises(PermissionError):
            self.bridge.begin(old, 2, "item")
        self.assertEqual(self.begin()["state"], "starting")

    def test_catalog_revocation(self):
        ticket = self.begin()["ticket"]
        self.grant = None
        self.assertEqual(self.bridge.poll(self.owner, ticket)["state"], "cancelled")

    def test_startup_timeout_even_with_browser_polling(self):
        ticket = self.begin()["ticket"]
        for t in (10, 20, 30):
            self.now = t
            result = self.bridge.poll(self.owner, ticket)
        self.assertEqual(result["state"], "fallback")

    def test_disconnect_retires_and_revokes_owner(self):
        self.begin()
        self.assertTrue(self.bridge.disconnect(self.owner)["clean"])
        with self.assertRaises(PermissionError):
            self.begin(2)

    def test_unknown_spawn_outcome_quarantines(self):
        def fail(grant):
            raise OSError("unknown launch outcome")
        self.bridge.start_renderer = fail
        self.clean = False
        self.assertEqual(self.begin()["state"], "quarantined")
        self.assertEqual(self.retired, [None])

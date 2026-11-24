"""Opt-in bridge contract tests, no real renderer or display operations."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pi_player import mpv_lab_integration as lab

TOKEN = "a" * 64
ITEM = "12345678-1234-1234-1234-123456789012"
HEADERS = {"origin": lab.ORIGIN, "host": "127.0.0.1:8000"}
PATH = "/api/player/mpv-lab"


class LabIntegrationTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_api_websocket_route(PATH, lab.mpv_lab)
        self.client = TestClient(app, client=("127.0.0.1", 12345))
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(lab, "_lock", asyncio.Lock()))
        self.stack.enter_context(patch.object(lab, "_renderer", None))
        self.stack.enter_context(patch.object(lab, "any_mpv", return_value=False))
        self.token = self.stack.enter_context(patch.object(lab, "lab_token", return_value=TOKEN))
        self.renderer = MagicMock()
        self.renderer.inspect.return_value = "playing"
        self.renderer.retire.return_value = True
        self.factory = self.stack.enter_context(
            patch.object(lab, "LabRenderer", return_value=self.renderer))

    def connect(self):
        return self.client.websocket_connect(PATH, headers=HEADERS)

    def start(self, ws):
        ws.send_json({"action": "start", "token": TOKEN, "item_id": ITEM})
        self.assertEqual(ws.receive_json(), {"state": "starting"})

    def test_disabled_by_default(self):
        self.token.return_value = None
        with self.assertRaises(WebSocketDisconnect):
            with self.connect():
                pass
        self.factory.assert_not_called()

    def test_wrong_token_cannot_spawn(self):
        with self.connect() as ws:
            ws.send_json({"action": "start", "token": "b"*64, "item_id": ITEM})
            with self.assertRaises(WebSocketDisconnect):
                ws.receive_json()
        self.factory.assert_not_called()

    def test_remote_origin_rejected(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(PATH, headers={**HEADERS, "origin":"http://example.com"}):
                pass
        self.factory.assert_not_called()

    def test_check_does_not_spawn(self):
        with self.connect() as ws:
            ws.send_json({"action":"check","token":TOKEN})
            self.assertEqual(ws.receive_json(), {"state":"clean","clean":True})
        self.factory.assert_not_called()

    def test_terminal_acknowledgements_release_lock_before_send(self):
        # A browser may open its next WebSocket as soon as it receives clean.
        # Assert at the actual send boundary, rather than relying on timing.
        from starlette.websockets import WebSocket
        original = WebSocket.send_json
        terminal_states = []

        async def checked_send(ws, data, *args, **kwargs):
            if "clean" in data and data.get("clean") is True:
                self.assertFalse(lab._lock.locked())
                terminal_states.append(data["state"])
            return await original(ws, data, *args, **kwargs)

        with patch.object(WebSocket, "send_json", checked_send):
            with self.connect() as ws:
                ws.send_json({"action":"check","token":TOKEN})
                self.assertEqual(ws.receive_json(), {"state":"clean","clean":True})
                with self.connect() as playback:
                    self.start(playback)
                    playback.send_json({"action":"stop"})
                    self.assertEqual(playback.receive_json(), {"state":"cancelled","clean":True})
        self.assertEqual(terminal_states, ["clean", "cancelled"])
        self.factory.assert_called_once()

    def test_normal_playback_and_verified_completion(self):
        self.renderer.inspect.side_effect = ["playing", "completed"]
        with self.connect() as ws:
            self.start(ws)
            ws.send_json({"action":"ping"})
            self.assertEqual(ws.receive_json(), {"state":"playing"})
            ws.send_json({"action":"ping"})
            self.assertEqual(ws.receive_json(), {"state":"completed","clean":True})
        self.renderer.retire.assert_called()

    def test_explicit_stop(self):
        with self.connect() as ws:
            self.start(ws)
            ws.send_json({"action":"stop"})
            self.assertEqual(ws.receive_json(), {"state":"cancelled","clean":True})
        self.renderer.retire.assert_called()

    def test_failed_cleanup_quarantines(self):
        self.renderer.retire.return_value = False
        with self.connect() as ws:
            self.start(ws)
            ws.send_json({"action":"stop"})
            self.assertEqual(ws.receive_json(), {"state":"quarantined","clean":False})
        with self.connect() as ws:
            ws.send_json({"action":"check","token":TOKEN})
            self.assertEqual(ws.receive_json(), {"state":"quarantined","clean":False})
        self.factory.assert_called_once()

    def test_launch_failure_falls_back_only_after_cleanup(self):
        self.renderer.stage = "spawn"
        self.renderer.launch.side_effect = OSError(13, "fixture secret must not be returned")
        with self.connect() as ws:
            ws.send_json({"action":"start","token":TOKEN,"item_id":ITEM})
            self.assertEqual(ws.receive_json(), {"state":"fallback","clean":True,
                                                  "reason":"spawn:PermissionError:errno=13"})
        self.renderer.retire.assert_called()


class RendererTests(unittest.TestCase):
    def test_revoked_catalog_cancels(self):
        renderer = lab.LabRenderer(ITEM)
        renderer.proc = MagicMock()
        renderer.proc.poll.return_value = None
        with patch.object(lab, "eligible", side_effect=ValueError("revoked")):
            self.assertEqual(renderer.inspect(), "cancelled")

    def test_authorization_checks_origin_and_peer(self):
        ws = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers=HEADERS)
        with patch.object(lab, "lab_token", return_value=TOKEN):
            self.assertTrue(lab.authorized(ws, TOKEN))
            ws.client.host = "192.0.2.1"
            self.assertFalse(lab.authorized(ws, TOKEN))

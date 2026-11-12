import configparser
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pi_player.network_credentials import (
    CredentialStore, Credentials, WirelessCredentials, STORE_FILE,
    encode_credentials, decode_credentials, render_profile,
)
from pi_player.network_policy import HOTSPOT_SSID
from pi_player.network_wireless import CLIENT_UUID, HOTSPOT_UUID


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = CredentialStore(self.directory, owner_uid=os.getuid())
        self.path = self.directory / STORE_FILE

    def test_first_provision_and_persistence(self):
        first = self.store.provision()
        self.assertEqual(first.hotspot.ssid, HOTSPOT_SSID)
        self.assertRegex(first.hotspot.password, r"^[A-Za-z0-9]{8}$")
        self.assertEqual(first, self.store.provision())
        self.assertEqual(first, self.store.load())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(first.client)

    def test_explicit_change_and_regeneration(self):
        first = self.store.provision()
        client = Credentials("Test client", "password")
        self.store.save(WirelessCredentials(first.hotspot, client))
        with patch("pi_player.network_credentials.generate_hotspot_password", return_value="Abc12345"):
            updated = self.store.regenerate_hotspot()
        self.assertEqual(updated.hotspot.password, "Abc12345")
        self.assertEqual(updated.hotspot.ssid, first.hotspot.ssid)
        self.assertEqual(updated.client, client)
        self.assertEqual(self.store.load(), updated)
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_public_status_and_repr_redact_password(self):
        value = WirelessCredentials(Credentials("test", "password"), Credentials("client", "password"))
        self.assertNotIn("password", repr(value))
        self.assertEqual(value.public_status(), {
            "hotspot_ssid": "test", "client_configured": True, "client_ssid": "client"})

    def test_unsafe_directory_refused(self):
        self.directory.chmod(0o755)
        with self.assertRaises(PermissionError):
            self.store.provision()
        self.assertFalse(self.path.exists())

    def test_unsafe_file_refused_not_reset(self):
        self.store.provision()
        self.path.chmod(0o644)
        previous = self.path.read_bytes()
        with self.assertRaises(PermissionError):
            self.store.provision()
        self.assertEqual(self.path.read_bytes(), previous)

    def test_wrong_owner_refused(self):
        store = CredentialStore(self.directory, owner_uid=os.getuid() + 1)
        with self.assertRaises(PermissionError):
            store.provision()

    def test_symlink_file_refused(self):
        target = self.directory / "other"
        target.write_text("untouched")
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            self.store.provision()
        self.assertEqual(target.read_text(), "untouched")

    def test_symlink_directory_refused(self):
        with tempfile.TemporaryDirectory() as other:
            link = Path(other) / "link"
            link.symlink_to(self.directory, target_is_directory=True)
            with self.assertRaises(OSError):
                CredentialStore(link, owner_uid=os.getuid()).provision()

    def test_hardlinked_file_refused(self):
        self.store.provision()
        os.link(self.path, self.directory / "other")
        with self.assertRaises(PermissionError):
            self.store.load()

    def test_corrupt_record_not_overwritten(self):
        self.path.write_text("invalid")
        self.path.chmod(0o600)
        with self.assertRaises(ValueError):
            self.store.provision()
        self.assertEqual(self.path.read_text(), "invalid")

    def test_explicit_save_requires_existing_store(self):
        value = WirelessCredentials(Credentials("test", "password"))
        with self.assertRaises(FileNotFoundError):
            self.store.save(value)
        self.assertFalse(self.path.exists())

    def test_invalid_credentials_and_schema(self):
        for ssid, password in (("", "password"), ("bad\nssid", "password"),
                               ("a"*33, "password"), ("test", "short"), ("test", None)):
            with self.assertRaises(ValueError):
                Credentials(ssid, password)
        for data in (b"[]", b"{}", b'{"version":true,"hotspot":{},"client":null}', b"\xff"):
            with self.assertRaises(ValueError):
                decode_credentials(data)
        value = WirelessCredentials(Credentials("test", "password"))
        self.assertEqual(decode_credentials(encode_credentials(value)), value)

    def test_atomic_replace_failure_preserves_existing_record(self):
        first = self.store.provision()
        with patch("pi_player.network_credentials.os.replace", side_effect=OSError("simulated")):
            with self.assertRaises(OSError):
                self.store.save(WirelessCredentials(Credentials("changed", "password")))
        self.assertEqual(self.store.load(), first)
        self.assertEqual(list(self.directory.iterdir()), [self.path])


class WirelessProfileTests(unittest.TestCase):
    def parse(self, credentials, hotspot):
        result = configparser.ConfigParser(interpolation=None)
        result.read_string(render_profile(credentials, hotspot=hotspot))
        return result

    def test_standard_wpa_psk_vector(self):
        p = self.parse(Credentials("IEEE", "password"), False)
        # Public IEEE WPA test vector; not a real appliance credential.
        self.assertEqual(p["wifi-security"]["psk"],
                         "f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e")

    def test_ssid_encoded_as_bytes_and_no_raw_password(self):
        credentials = Credentials(" test;=é\\ ", "password")
        raw = render_profile(credentials, hotspot=True)
        p = self.parse(credentials, True)
        encoded = bytes(int(n) for n in p["wifi"]["ssid"].split(";") if n)
        self.assertEqual(encoded.decode("utf-8"), credentials.ssid)
        self.assertNotIn(credentials.password, raw)

    def test_hotspot_isolation_settings(self):
        p = self.parse(Credentials("test", "password"), True)
        self.assertEqual(p["connection"]["uuid"], HOTSPOT_UUID)
        self.assertEqual(p["connection"]["autoconnect"], "false")
        self.assertEqual(p["wifi"]["mode"], "ap")
        self.assertEqual(p["wifi"]["ap-isolation"], "1")
        self.assertEqual(p["wifi-security"]["wps-method"], "1")
        self.assertEqual(p["wifi-security"]["pairwise"], "ccmp;")
        self.assertEqual(p["ipv4"]["address1"], "10.42.0.1/24")
        self.assertEqual(p["ipv4"]["never-default"], "true")
        self.assertEqual(p["ipv6"]["method"], "disabled")

    def test_client_profile_is_dhcp_only_and_not_shared(self):
        p = self.parse(Credentials("test", "password"), False)
        self.assertEqual(p["connection"]["uuid"], CLIENT_UUID)
        self.assertEqual(p["connection"]["autoconnect"], "false")
        self.assertEqual(p["wifi"]["mode"], "infrastructure")
        self.assertEqual(p["ipv4"]["method"], "auto")
        self.assertEqual(p["ipv6"]["method"], "disabled")
        self.assertNotIn("address1", p["ipv4"])


if __name__ == "__main__":
    unittest.main()

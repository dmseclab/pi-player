import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Isolated runtime, never a player's production database.
_runtime = tempfile.TemporaryDirectory()
os.environ['PI_PLAYER_DATA_DIR'] = _runtime.name
from fastapi.testclient import TestClient
from pi_player.application import app
from pi_player.db import connect, init_db, db, set_setting


class PdfTests(unittest.TestCase):
    def setUp(self):
        with db() as conn:
            set_setting(conn,"setup_required","0")
        self.client = TestClient(app)
        self.client.post('/api/login', json={'username': 'pi', 'password': 'pi'}).raise_for_status()

    def test_upload_playback_settings_and_package_roundtrip(self):
        content = b'%PDF-1.7\nPDF fixture for transport tests\n%%EOF'
        response = self.client.post('/api/assets/upload', files={'file': ('notice.pdf', content, 'application/pdf')}, data={'pdf_page_seconds': '7'})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()
        self.assertEqual(asset['type'], 'pdf')
        self.assertEqual(asset['pdf_page_seconds'], 7)
        self.assertEqual(self.client.get(asset['media_url']).content, content)
        response = self.client.put('/api/assets/'+asset['id'], json={'name': 'Notice', 'pdf_page_seconds': 3})
        self.assertEqual(response.status_code, 200, response.text)
        playlist = self.client.post('/api/playlists', json={'name': 'PDF test'}).json()
        pid = playlist['id']
        self.client.post(f'/api/playlists/{pid}/items', json={'asset_id': asset['id'], 'duration_seconds': 30}).raise_for_status()
        self.client.post(f'/api/playlists/{pid}/activate').raise_for_status()
        self.client.post('/api/playback/start').raise_for_status()
        item = self.client.get('/api/player/playlist').json()['items'][0]
        self.assertEqual(item['asset_pdf_page_seconds'], 3)
        self.assertTrue(item['asset_file_present'])
        package = self.client.get(f'/api/playlists/{pid}/export')
        package.raise_for_status()
        imported = self.client.post('/api/playlists/import', files={'file': ('test.zip', package.content, 'application/zip')})
        self.assertEqual(imported.status_code, 200, imported.text)
        new_assets = self.client.get('/api/assets').json()
        copies = [a for a in new_assets if a['type'] == 'pdf' and a['id'] != asset['id']]
        self.assertEqual(copies[-1]['pdf_page_seconds'], 3)
        self.assertEqual(self.client.get(copies[-1]['media_url']).content, content)

    def test_video_support_survives_consolidation(self):
        response = self.client.post('/api/assets/upload', files={'file': ('clip.mp4', b'video transport fixture', 'video/mp4')}, data={'video_muted':'false','video_loop':'true'})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()
        self.assertEqual(asset['type'], 'video')
        self.assertFalse(asset['video_muted'])
        self.assertTrue(asset['video_loop'])
        listed = next(a for a in self.client.get('/api/assets').json() if a['id']==asset['id'])
        self.assertIsNotNone(listed['media_url'])
        self.assertIn('inline', self.client.get(listed['media_url']).headers['content-disposition'])
        pid = self.client.post('/api/playlists', json={'name':'Video roundtrip'}).json()['id']
        self.client.post(f'/api/playlists/{pid}/items',json={'asset_id':asset['id'],'duration_seconds':15}).raise_for_status()
        package = self.client.get(f'/api/playlists/{pid}/export')
        package.raise_for_status()
        response = self.client.post('/api/playlists/import',files={'file':('video.zip',package.content,'application/zip')})
        self.assertEqual(response.status_code,200,response.text)
        copied = [a for a in self.client.get('/api/assets').json() if a['type']=='video' and a['id']!=asset['id'] and a['original_filename']=='clip.mp4'][-1]
        self.assertFalse(bool(copied['video_muted']))
        self.assertTrue(bool(copied['video_loop']))

    def test_appliance_migration_preserves_video_and_setup(self):
        import pi_player.db as module
        original=module.DB_PATH
        module.DB_PATH=Path(_runtime.name)/'appliance.sqlite'
        try:
            conn=connect()
            conn.executescript("""
            CREATE TABLE "assets" (id TEXT PRIMARY KEY, type TEXT NOT NULL CHECK (type IN ('image','website','video')), name TEXT, display_mode TEXT, created_at TEXT, updated_at TEXT, video_muted INTEGER, video_loop INTEGER);
            CREATE TABLE links (asset_id TEXT REFERENCES assets(id));
            INSERT INTO assets VALUES ('oldvideo','video','Clip','fit','','',0,1);
            INSERT INTO links VALUES ('oldvideo');
            """)
            conn.close()
            init_db()
            with db() as conn:
                set_setting(conn,'setup_required','0')
            init_db()
            with db() as conn:
                row=conn.execute('SELECT * FROM assets').fetchone()
                self.assertEqual((row['video_muted'],row['video_loop']),(0,1))
                self.assertEqual(row['pdf_page_seconds'],10)
                self.assertEqual(conn.execute('SELECT asset_id FROM links').fetchone()[0],'oldvideo')
                self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
                conn.execute("INSERT INTO assets (id,type,name) VALUES ('newpdf','pdf','New')")
                self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='setup_required'").fetchone()[0],'0')
        finally:
            module.DB_PATH=original

    def test_new_assets_append_disabled_to_active_playlist(self):
        pid=self.client.post('/api/playlists',json={'name':'Automatic additions'}).json()['id']
        self.client.post(f'/api/playlists/{pid}/activate').raise_for_status()
        for name,mime,body in [('image.png','image/png',b'image'),('video.mp4','video/mp4',b'video'),('pdf.pdf','application/pdf',b'%PDF-1.7')]:
            self.client.post('/api/assets/upload',files={'file':(name,body,mime)}).raise_for_status()
        self.client.post('/api/assets/link',json={'name':'Website','url':'https://example.com'}).raise_for_status()
        playlist=next(p for p in self.client.get('/api/playlists').json() if p['id']==pid)
        self.assertEqual(len(playlist['items']),4)
        self.assertEqual([i['position'] for i in playlist['items']],[0,1,2,3])
        self.assertTrue(all(not i['enabled'] for i in playlist['items']))
        self.assertTrue(all(i['duration_seconds']==15 for i in playlist['items']))
        with db() as conn:
            conn.execute('UPDATE playlists SET is_active=0')
        self.client.post('/api/assets/link',json={'name':'Unassigned','url':'https://example.com'}).raise_for_status()
        playlist=next(p for p in self.client.get('/api/playlists').json() if p['id']==pid)
        self.assertEqual(len(playlist['items']),4)

    def test_validation(self):
        response = self.client.post('/api/assets/upload', files={'file': ('bad.pdf', b'not PDF', 'application/pdf')})
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/assets/upload', files={'file': ('bad.pdf', b'%PDF-', 'image/png')})
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/assets/upload', files={'file': ('test.pdf', b'%PDF-', 'application/pdf')}, data={'pdf_page_seconds': '0'})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(list((Path(_runtime.name)/'tmp').glob('*.upload')))

    def test_legacy_migration_preserves_references_and_columns(self):
        # Build legacy constraint on an isolated database, preserving extra columns.
        import pi_player.db as module
        original = module.DB_PATH
        module.DB_PATH = Path(_runtime.name)/'legacy.sqlite'
        try:
            conn = connect()
            conn.executescript("""
            CREATE TABLE assets (id TEXT PRIMARY KEY, type TEXT CHECK(type IN ('image', 'website')), name TEXT, display_mode TEXT, created_at TEXT, updated_at TEXT, zoom_percent INTEGER);
            CREATE TABLE links (asset_id TEXT REFERENCES assets(id));
            INSERT INTO assets VALUES ('legacy', 'image', 'Old', 'fit', '', '', 125);
            INSERT INTO links VALUES ('legacy');
            """)
            conn.close()
            init_db()
            init_db()
            conn = connect()
            self.assertEqual(conn.execute('SELECT zoom_percent FROM assets').fetchone()[0], 125)
            self.assertEqual(conn.execute('SELECT asset_id FROM links').fetchone()[0], 'legacy')
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
            conn.execute("INSERT INTO assets (id,type,name) VALUES ('pdf','pdf','New')")
            conn.close()
        finally:
            module.DB_PATH = original

if __name__ == '__main__':
    unittest.main()

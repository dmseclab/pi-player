import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.geteuid()==0 and shutil.which('rsync'),'Updater harness requires root and rsync')
class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source';self.app=self.root/'runtime';self.data=self.root/'data';self.bin=self.root/'bin'
        for base in [self.source,self.app]:
            for folder in ['pi_player','static','deploy']:(base/folder).mkdir(parents=True)
            (base/'requirements.txt').write_text('fixture==1\n')
        (self.source/'pi_player/__init__.py').write_text('__version__="new"\n')
        (self.app/'pi_player/__init__.py').write_text('__version__="old"\n')
        (self.app/'static/old.js').write_text('old')
        (self.source/'static/new.js').write_text('new')
        (self.source/'deploy/update.sh').write_bytes((ROOT/'deploy/update.sh').read_bytes())
        (self.app/'.venv/bin').mkdir(parents=True)
        self.data.mkdir();(self.data/'database').write_text('original data')
        self.bin.mkdir()
        self.env={**os.environ,'PATH':str(self.bin)+os.pathsep+os.environ['PATH'],
                  'PI_PLAYER_APP_DIR':str(self.app),'PI_PLAYER_DATA_DIR':str(self.data),
                  'PI_PLAYER_BACKUP_ROOT':str(self.root/'backups'),'TEST_LOG':str(self.root/'calls')}
        def executable(path,code):path.write_text(code);path.chmod(0o755)
        executable(self.app/'.venv/bin/python',f'''#!{sys.executable}
import os,sys
if sys.argv[1:3]==['-m','pip']:
    with open(os.environ['TEST_LOG'],'a') as f:f.write(sys.argv[3]+'\\n')
    if sys.argv[3]=='install' and os.environ.get('FAIL_INSTALL'):sys.exit(1)
    sys.exit(0)
os.execv({sys.executable!r},[{sys.executable!r}]+sys.argv[1:])
''')
        executable(self.bin/'systemctl',f'''#!{sys.executable}
import os,sys
with open(os.environ['TEST_LOG'],'a') as f:f.write('systemctl '+' '.join(sys.argv[1:])+'\\n')
sys.exit(0)
''')
        executable(self.bin/'curl',f'''#!{sys.executable}
import json,os,re
from pathlib import Path
version=re.search(r'__version__\\s*=\\s*["\\\']([^"\\\']+)',(Path(os.environ['PI_PLAYER_APP_DIR'])/'pi_player/__init__.py').read_text()).group(1)
print(json.dumps({{'ok':True,'version':version}}))
''')
    def run_update(self,*args,fail=False):
        env={**self.env}
        if fail:env['FAIL_INSTALL']='1'
        return subprocess.run(['bash',str(self.source/'deploy/update.sh'),*args],env=env,text=True,capture_output=True)
    def test_success_and_manual_rollback(self):
        result=self.run_update();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Update complete: new',result.stdout)
        self.assertTrue((self.app/'static/new.js').exists())
        self.assertFalse((self.app/'static/old.js').exists())
        calls=(self.root/'calls').read_text();self.assertLess(calls.index('download'),calls.index('systemctl stop'))
        snapshot=next(p for p in (self.root/'backups').iterdir() if (p/'complete').exists())
        (self.data/'database').write_text('post-update change')
        result=self.run_update('--rollback',str(snapshot));self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('"old"',(self.app/'pi_player/__init__.py').read_text())
        self.assertEqual((self.data/'database').read_text(),'original data')
        self.assertTrue((self.app/'static/old.js').exists())
    def test_dependency_failure_restores_snapshot(self):
        result=self.run_update(fail=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('restoring application and data snapshot',result.stderr)
        self.assertIn('"old"',(self.app/'pi_player/__init__.py').read_text())
        self.assertTrue((self.app/'static/old.js').exists())
        self.assertFalse((self.app/'static/new.js').exists())
        self.assertEqual((self.data/'database').read_text(),'original data')
        self.assertIn('systemctl start pi-player-api.service',(self.root/'calls').read_text())

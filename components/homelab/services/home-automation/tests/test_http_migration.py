"""Exercise restored HTTP storage through the real bootstrap in isolated paths."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[5]
SOURCE=ROOT/'deployments/homelab/cluster/apps/home-automation/bootstrap.py'

class HttpMigrationTests(unittest.TestCase):
    def fixture(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        for folder in ['state','bootstrap','credentials','runtime']:(root/folder).mkdir()
        for name in ['configuration.yaml','zigbee-configuration.yaml','mosquitto.acl','mosquitto-nuki.acl']:
            (root/'bootstrap'/name).write_text('{}\n')
        for name in ['homeassistant','zigbee2mqtt','monitoring','nuki']:
            (root/'credentials'/f'{name}-password').write_text('synthetic-local-mqtt-fixture')
        source=SOURCE.read_text()
        for folder in ['state','bootstrap','credentials','runtime']:
            source=source.replace(f"Path('/{folder}')",'Path('+repr(str(root/folder))+')')
        script=root/'bootstrap-test.py';script.write_text(source)
        return root,script

    def execute(self,script):
        result=subprocess.run([sys.executable,str(script)],capture_output=True)
        self.assertEqual(0,result.returncode,result.stderr.decode())

    def test_fresh_http_storage_trusts_target_pod_range(self):
        root,script=self.fixture();self.execute(script)
        stored=json.loads((root/'state/home-assistant/.storage/http').read_text())
        self.assertEqual(['10.100.0.0/16'],stored['data']['stable']['trusted_proxies'])

    def test_restored_storage_preserves_custom_settings_and_is_idempotent(self):
        root,script=self.fixture()
        directory=root/'state/home-assistant/.storage';directory.mkdir(parents=True)
        stable={'trusted_proxies':['172.16.0.0/13','192.0.2.14/32'],
                'server_port':8123,'cors_allowed_origins':['https://home.fahrican.com'],
                'created_at':'existing-state-marker','login_attempts_threshold':7}
        document={'version':2,'minor_version':2,'key':'http',
                  'data':{'stable':stable,'pending':{'trusted_proxies':['172.16.0.0/13'],'server_port':8124},'yaml_migration_done':True}}
        path=directory/'http';path.write_text(json.dumps(document))
        matter=root/'state/matter';matter.mkdir();(matter/'paired-device-state').write_bytes(b'preserve-pairing-identities')
        self.execute(script)
        result=json.loads(path.read_text())
        self.assertEqual(['10.100.0.0/16','192.0.2.14/32'],result['data']['stable']['trusted_proxies'])
        self.assertEqual(['10.100.0.0/16'],result['data']['pending']['trusted_proxies'])
        self.assertEqual({k:v for k,v in stable.items() if k!='trusted_proxies'},
                         {k:v for k,v in result['data']['stable'].items() if k!='trusted_proxies'})
        self.assertEqual(8124,result['data']['pending']['server_port'])
        self.assertEqual(b'preserve-pairing-identities',(matter/'paired-device-state').read_bytes())
        before=path.read_bytes();self.execute(script);self.assertEqual(before,path.read_bytes())

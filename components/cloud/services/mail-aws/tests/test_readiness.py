import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "tofu/wait-ready.sh"


class ReplacementReadinessTest(unittest.TestCase):
    def run_probe(self, admin_status="404", jmap_url="https://mail.fahrican.com/jmap/"):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory, "wget")
            binary.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[-1].endswith('/admin/'):
    print('  HTTP/1.1 ' + os.environ['ADMIN_STATUS'] + ' Status', file=sys.stderr)
    raise SystemExit(8 if os.environ['ADMIN_STATUS'] == '404' else 0)
payload = ('version: STSv1\\nmx: mail.fahrican.com\\n'
           if args[-1].endswith('/mta-sts.txt')
           else json.dumps({'apiUrl': os.environ['JMAP_URL']}))
Path(args[args.index('-O') + 1]).write_text(payload)
''')
            binary.chmod(0o700)
            sleep = Path(directory, "sleep")
            sleep.write_text("#!/bin/sh\nexit 0\n")
            sleep.chmod(0o700)
            env = dict(os.environ, PATH=directory + ":" + os.environ["PATH"],
                       MAIL_READY_IP="192.0.2.1", ADMIN_STATUS=admin_status, JMAP_URL=jmap_url)
            return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, timeout=30)

    def test_public_jmap_and_closed_admin_allow_promotion(self):
        self.assertEqual(self.run_probe().returncode, 0)

    def test_healthy_mail_with_exposed_admin_never_promotes(self):
        self.assertNotEqual(self.run_probe(admin_status="200").returncode, 0)

    def test_private_jmap_discovery_never_promotes(self):
        self.assertNotEqual(self.run_probe(jmap_url="https://mail-admin.fahrican.com/jmap/").returncode, 0)


if __name__ == "__main__":
    unittest.main()

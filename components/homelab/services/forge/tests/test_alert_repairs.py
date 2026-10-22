"""Regression coverage for the October metrics and alert failures."""
import importlib.util
import io
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[5]
SERVICES = ROOT / 'deployments/homelab/cluster'


class MetricsTests(unittest.TestCase):
    def test_every_scrape_closes_sqlite_even_on_query_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            env = {'FORGEJO_DATABASE': str(path / 'db.sqlite')}
            with sqlite3.connect(path / 'db.sqlite') as db:
                db.executescript('CREATE TABLE action_run_job(status, updated, name, stopped, repo_id);'
                                 'CREATE TABLE repository(id, owner_name, name);')
            db.close()
            spec = importlib.util.spec_from_file_location('actions_metrics_test', SERVICES / 'apps/forge/actions-metrics.py')
            module = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, env):
                spec.loader.exec_module(module)
            connect = sqlite3.connect
            connections = []

            def track(*args, **kwargs):
                connection = connect(*args, **kwargs)
                connections.append(connection)
                return connection

            for broken in (False, True):
                if broken:
                    with connect(path / 'db.sqlite') as db:
                        db.execute('DROP TABLE action_run_job')
                    db.close()
                with patch.object(module.sqlite3, 'connect', side_effect=track):
                    for _ in range(20):
                        handler = object.__new__(module.Metrics)
                        handler.path, handler.wfile = '/metrics', io.BytesIO()
                        handler.send_response = lambda *_: None
                        handler.send_header = lambda *_: None
                        handler.end_headers = lambda: None
                        handler.do_GET()
                        self.assertIn(b'forge_actions_metrics_up', handler.wfile.getvalue())
                        with self.assertRaises(sqlite3.ProgrammingError):
                            connections[-1].execute('SELECT 1')


class AlertTests(unittest.TestCase):
    def test_recovered_history_and_terminal_failures(self):
        document = yaml.safe_load((ROOT / 'deployments/homelab/cluster/infrastructure/observability/job-health.yaml').read_text())
        groups = document['spec']['groups']
        scheduled = next(r for g in groups for r in g['rules']
                         if r.get('alert') == 'KubeJobFailed' and 'unrecovered_failure' in r['expr'])
        standalone = next(r for g in groups for r in g['rules']
                          if r.get('alert') == 'KubeJobFailed' and 'job_name' in r['expr'])
        tests = []
        for success, suspended, terminal, owned in ((200, False, True, True),
                (50, False, True, True), (None, False, True, True),
                (None, True, True, True), (None, False, False, True),
                (None, False, True, False)):
            labels = 'namespace="media",job_name="reconcile-old"'
            cj = 'namespace="media",cronjob="reconcile"'
            series = [
                {'series': f'kube_job_status_start_time{{{labels}}}', 'values': '100+0x20'},
                {'series': f'kube_job_status_failed{{{labels}}}', 'values': '1+0x20'},
                {'series': f'kube_job_failed{{{labels},condition="true"}}', 'values': f'{int(terminal)}+0x20'},
                {'series': f'kube_cronjob_spec_suspend{{{cj}}}', 'values': f'{int(suspended)}+0x20'},
            ]
            if owned:
                series.append({'series': f'kube_job_owner{{{labels},owner_kind="CronJob",owner_name="reconcile"}}', 'values': '1+0x20'})
            if success is not None:
                series.append({'series': f'kube_cronjob_status_last_successful_time{{{cj}}}', 'values': f'{success}+0x20'})
            expected = []
            if terminal and (not owned or (not suspended and (success is None or success < 100))):
                rule = scheduled if owned else standalone
                expected = [{'exp_labels': {'namespace': 'media',
                    ('cronjob' if owned else 'job_name'): ('reconcile' if owned else 'reconcile-old'),
                    'severity': 'warning'}, 'exp_annotations': {
                        **rule['annotations'], 'description': (
                            'CronJob media/reconcile has no successful completion since its latest failed run.'
                            if owned else 'Job media/reconcile-old failed to complete. Inspect its logs before removing it.')}}]
            tests.append({'interval': '1m', 'input_series': series,
                'alert_rule_test': [{'eval_time': '16m', 'alertname': 'KubeJobFailed', 'exp_alerts': expected}]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'rules.yml').write_text(yaml.safe_dump({'groups': groups}))
            (path / 'tests.yml').write_text(yaml.safe_dump({'rule_files': ['rules.yml'], 'evaluation_interval': '1m', 'tests': tests}))
            result = subprocess.run([shutil.which('promtool') or 'promtool', 'test', 'rules', 'tests.yml'],
                cwd=path, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_recovered_jobs_and_duplicate_notifications(self):
        groups = []
        for filename in ('infrastructure/observability/persistent-targets.yaml',
                         'infrastructure/observability/job-health.yaml', 'apps/unifi/monitoring.yaml',
                         'apps/forge/monitoring.yaml', 'infrastructure/backups/drill.yaml'):
            for document in yaml.safe_load_all((SERVICES / filename).read_text()):
                if document['kind'] == 'PrometheusRule':
                    groups.extend(document['spec']['groups'])
        by_name = {r['alert']: r for g in groups for r in g['rules'] if 'alert' in r}
        tests = []
        for recovered, suspended, terminal in ((True, False, True), (False, False, True),
                                               (False, True, True), (False, False, False)):
            labels = 'namespace="media",job_name="audiomuse-reconcile-old"'
            cj = 'namespace="media",cronjob="audiomuse-reconcile"'
            series = [
                {'series': f'kube_job_status_start_time{{{labels}}}', 'values': '100+0x20'},
                {'series': f'kube_job_status_failed{{{labels}}}', 'values': '1+0x20'},
                {'series': f'kube_job_failed{{{labels},condition="true"}}', 'values': f'{int(terminal)}+0x20'},
                {'series': f'kube_job_owner{{{labels},owner_kind="CronJob",owner_name="audiomuse-reconcile"}}', 'values': '1+0x20'},
                {'series': f'kube_cronjob_spec_suspend{{{cj}}}', 'values': f'{int(suspended)}+0x20'},
            ]
            if recovered:
                series.append({'series': f'kube_cronjob_status_last_successful_time{{{cj}}}', 'values': '200+0x20'})
            expected = [] if recovered or suspended or not terminal else [{
                'exp_labels': {'namespace': 'media', 'cronjob': 'audiomuse-reconcile', 'severity': 'warning'},
                'exp_annotations': {'summary': 'Scheduled job has not recovered.',
                                    'description': 'CronJob media/audiomuse-reconcile has no successful completion since its latest failed run.',
                                    'runbook_url': 'https://runbooks.prometheus-operator.dev/runbooks/kubernetes/kubejobfailed'}}]
            tests.append({'interval': '1m', 'input_series': series, 'alert_rule_test': [
                {'eval_time': '16m', 'alertname': 'KubeJobFailed', 'exp_alerts': expected}]})
        for scrape_up, telemetry in ((False, False), (True, False), (True, True)):
            series = [{'series': 'up{namespace="unifi",job="unifi",endpoint="ap-metrics",instance="unifi:9130"}',
                       'values': f'{int(scrape_up)}+0x20'}]
            if telemetry:
                series.append({'series': 'unifi_device_uptime_seconds{namespace="unifi",type="uap"}', 'values': '100+60x20'})
            tests.append({'interval': '1m', 'input_series': series, 'alert_rule_test': [
                {'eval_time': '16m', 'alertname': 'UniFiAPMetricsMissing', 'exp_alerts': [] if telemetry else [{
                    'exp_labels': {'namespace': 'unifi', 'severity': 'warning'},
                    'exp_annotations': by_name['UniFiAPMetricsMissing']['annotations']}]},
                {'eval_time': '16m', 'alertname': 'TargetDown', 'exp_alerts': []}]})
        for namespace in ('forge',):
            labels = f'namespace="{namespace}",pod="forgejo-0",job="kube-state-metrics"'
            tests.append({'interval': '1m', 'input_series': [
                {'series': f'kube_pod_status_phase{{{labels},phase="Pending"}}', 'values': '1+0x20'},
                {'series': f'kube_pod_owner{{{labels},owner_kind="StatefulSet"}}', 'values': '1+0x20'},
                {'series': f'kube_pod_info{{{labels}}}', 'values': '1+0x20'},
            ], 'alert_rule_test': [{'eval_time': '16m', 'alertname': 'KubePodNotReady',
                'exp_alerts': [{
                    'exp_labels': {'namespace': 'forge', 'pod': 'forgejo-0', 'job': 'kube-state-metrics', 'severity': 'warning'},
                    'exp_annotations': {'summary': by_name['KubePodNotReady']['annotations']['summary'],
                        'description': 'Pod forge/forgejo-0 has been in a non-ready state for longer than 15 minutes.',
                        'runbook_url': by_name['KubePodNotReady']['annotations']['runbook_url']}}]}]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'rules.yml').write_text(yaml.safe_dump({'groups': groups}))
            (path / 'tests.yml').write_text(yaml.safe_dump({'rule_files': ['rules.yml'], 'evaluation_interval': '1m', 'tests': tests}))
            result = subprocess.run([shutil.which('promtool') or 'promtool', 'test', 'rules', 'tests.yml'],
                                    cwd=path, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

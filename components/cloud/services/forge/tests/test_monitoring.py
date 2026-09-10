"""Evaluate deployed PromQL across retry, recovery and suspension histories."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / 'deployments/homelab/cloud/services/46-forge'


class MonitoringTests(unittest.TestCase):
    def test_controller_failures_are_stable_and_recover(self):
        promtool = shutil.which('promtool')
        if not promtool:
            self.fail('promtool is required; run the repository cloud-python Nix check')
        selected = {'ForgejoActionsLauncherFailing', 'ForgejoLinuxControllerFailed',
                    'ForgejoNativeControllerFailed', 'ForgejoLinuxRunnerFailed', 'ForgejoSnapshotBackupFailed'}
        rules = []
        for name in ['monitoring.yaml', 'native-monitoring.yaml']:
            for document in yaml.safe_load_all((SCRIPTS / name).read_text()):
                if document['kind'] == 'PrometheusRule':
                    rules += [r for group in document['spec']['groups'] for r in group['rules']
                              if 'record' in r or r.get('alert') in selected]
        by_name = {r['alert']: r for r in rules if 'alert' in r}
        tests = []
        for namespace, cronjob, alert in [
            ('forge', 'forge-snapshot-backup', 'ForgejoSnapshotBackupFailed'),
            ('forge-ci', 'forge-linux-qualification', 'ForgejoActionsLauncherFailing'),
            ('forge-control', 'forge-linux-atollion-launcher', 'ForgejoLinuxControllerFailed'),
            ('forge-control', 'forge-windows-qualification', 'ForgejoNativeControllerFailed'),
            ('forge-control', 'forge-macos-qualification', 'ForgejoNativeControllerFailed'),
        ]:
            for scenario in ['retries', 'recovered', 'never-succeeded', 'suspended']:
                series = []
                # Each retry has a different Job AND scrape target. History expires
                # while another failure persists: the alert must not restart its timer.
                for index, values in enumerate(['100+0x3 stale _ _ _ _', '_ _ 220+0x6']):
                    labels = f'namespace="{namespace}",job_name="{cronjob}-{index}",instance="ksm-{index}"'
                    series += [
                        {'series': f'kube_job_status_start_time{{{labels}}}', 'values': values},
                        {'series': f'kube_job_status_failed{{{labels}}}', 'values': values.replace('100', '1').replace('220', '1')},
                        {'series': f'kube_job_owner{{{labels},owner_kind="CronJob",owner_name="{cronjob}"}}',
                         'values': values.replace('100', '1').replace('220', '1')},
                    ]
                labels = f'namespace="{namespace}",cronjob="{cronjob}",instance="ksm"'
                series.append({'series': f'kube_cronjob_spec_suspend{{{labels}}}',
                               'values': ('1' if scenario == 'suspended' else '0') + '+0x8'})
                if scenario != 'never-succeeded':
                    series.append({'series': f'kube_cronjob_status_last_successful_time{{{labels}}}',
                                   'values': '50+0x5 500+0x2' if scenario == 'recovered' else '50+0x8'})
                expected = {'exp_labels': {'namespace': namespace, 'cronjob': cronjob, 'severity': 'warning'},
                            'exp_annotations': by_name[alert]['annotations']}
                tests.append({'name': cronjob + '-' + scenario, 'interval': '1m', 'input_series': series,
                              'alert_rule_test': [
                                  {'eval_time': '4m', 'alertname': alert, 'exp_alerts': []},
                                  {'eval_time': '5m', 'alertname': alert,
                                   'exp_alerts': [] if scenario == 'suspended' else [expected]},
                                  {'eval_time': '8m', 'alertname': alert,
                                   'exp_alerts': [expected] if scenario in ['retries', 'never-succeeded'] else []},
                              ]})
        # Application runner failures retain visibility, but do not alert per Job.
        alert = 'ForgejoLinuxRunnerFailed'
        tests.append({'name': 'multiple-application-runner-failures', 'interval': '1m',
                      'input_series': [
                          {'series': f'kube_job_status_failed{{namespace="forge-ci",job_name="forge-linux-atollion-{i}"}}',
                           'values': '1+0x8'} for i in range(2)],
                      'alert_rule_test': [{'eval_time': '6m', 'alertname': alert, 'exp_alerts': [
                          {'exp_labels': {'namespace': 'forge-ci', 'repository': 'atollion', 'severity': 'warning'},
                           'exp_annotations': by_name[alert]['annotations']}]}]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'rules.yml').write_text(yaml.safe_dump({'groups': [{'name': 'forge-test', 'rules': rules}]}))
            (path / 'tests.yml').write_text(yaml.safe_dump({'rule_files': ['rules.yml'],
                                                          'evaluation_interval': '1m', 'tests': tests}))
            result = subprocess.run([promtool, 'test', 'rules', 'tests.yml'], cwd=path,
                                    text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

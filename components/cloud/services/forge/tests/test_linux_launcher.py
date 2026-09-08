"""Bound queue concurrency and prevent duplicate or wrong-platform job launch."""
import importlib.util
from decimal import Decimal
from pathlib import Path
import unittest

import yaml

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).resolve().parents[1] / 'linux-launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class NamespaceBudget(unittest.TestCase):
    def test_quota_admits_all_launcher_slots_and_qualification(self):
        manifests = Path(__file__).resolve().parents[5] / 'deployments/homelab/cloud/services/46-forge'
        with (manifests / 'runners.yaml').open() as source:
            runners = list(yaml.safe_load_all(source))
        with (manifests / 'atollion-runners.yaml').open() as source:
            atollion = list(yaml.safe_load_all(source))
        quota = next(item['spec']['hard'] for item in runners if item['kind'] == 'ResourceQuota')

        def pod(documents, name):
            job = next(item for item in documents if item['metadata']['name'] == name)
            return job['spec']['jobTemplate']['spec']['template']['spec']

        def quantity(value):
            value = str(value)
            for suffix, factor in [('Gi', 1024**3), ('Mi', 1024**2), ('Ki', 1024), ('m', Decimal('0.001'))]:
                if value.endswith(suffix):
                    return Decimal(value[:-len(suffix)]) * factor
            return Decimal(value)

        def budget(spec, kind, resource):
            def value(container):
                return quantity(container.get('resources', {}).get(kind, {}).get(resource, '0'))
            return max(sum(value(container) for container in spec['containers']),
                       max((value(container) for container in spec.get('initContainers', [])), default=0))

        application = pod(atollion, 'forge-linux-atollion-template')
        qualification = pod(runners, 'forge-linux-qualification')
        for key in ['requests.cpu', 'limits.cpu', 'requests.memory', 'limits.memory', 'limits.ephemeral-storage']:
            with self.subTest(quota=key):
                kind, resource = key.split('.')
                required = launcher.CAPACITY * budget(application, kind, resource) + budget(qualification, kind, resource)
                self.assertGreaterEqual(quantity(quota[key]), required,
                                        f'{key} must admit every Atollion slot plus qualification')
        self.assertGreaterEqual(int(quota['pods']), launcher.CAPACITY + 1)


class QueueBounds(unittest.TestCase):
    def job(self, number, labels=None, attempt=1):
        return {'id': number, 'attempt': attempt, 'status': 'waiting',
                'runs_on': ['linux-x86_64'] if labels is None else labels}

    def existing(self, number, conditions=None, attempt=None):
        annotations = {launcher.JOB_ID_ANNOTATION: str(number)}
        if attempt is not None:
            annotations[launcher.ATTEMPT_ANNOTATION] = str(attempt)
        return {'metadata': {'annotations': annotations},
                'status': {'conditions': conditions or []}}

    def test_pending_jobs_consume_capacity_before_pods_exist(self):
        self.assertEqual(launcher.select_jobs([self.existing(1), self.existing(2)], [self.job(3)]), [])

    def test_terminal_jobs_cannot_be_launched_twice(self):
        completed = self.existing(1, [{'type': 'Complete', 'status': 'True'}])
        self.assertEqual(launcher.select_jobs([completed], [self.job(1), self.job(2)]), [self.job(2)])

    def test_only_two_oldest_eligible_linux_jobs_launch(self):
        waiting = [self.job(8), self.job(2), self.job(3), self.job(1, []),
                   self.job(4, ['windows-x86_64']), self.job(5, ['linux-x86_64', 'privileged'])]
        self.assertEqual(launcher.select_jobs([], waiting), [self.job(2), self.job(3)])

    def test_false_terminal_condition_keeps_slot_occupied(self):
        existing = [self.existing(1, [{'type': 'Failed', 'status': 'False'}])]
        self.assertEqual(launcher.select_jobs(existing, [self.job(2), self.job(3)]), [self.job(2)])

    def test_completed_attempt_does_not_delay_warm_retry(self):
        completed = self.existing(1, [{'type': 'Complete', 'status': 'True'}], attempt=1)
        self.assertEqual(launcher.select_jobs([completed], [self.job(1, attempt=2)]),
                         [self.job(1, attempt=2)])
        self.assertEqual(launcher.select_jobs([completed], [self.job(1, attempt=1)]), [])

    def test_attempt_tracking_preserves_active_capacity_and_legacy_claims(self):
        active = [self.existing(1, attempt=1), self.existing(2, attempt=1)]
        self.assertEqual(launcher.select_jobs(active, [self.job(1, attempt=2)]), [])
        self.assertEqual(launcher.select_jobs([self.existing(1)], [self.job(1, attempt=2)]), [])

    def test_invalid_queue_attempt_never_launches(self):
        for attempt in (None, 0, True, '2'):
            self.assertEqual(launcher.select_jobs([], [self.job(1, attempt=attempt)]), [])


if __name__ == '__main__':
    unittest.main()

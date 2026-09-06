"""Bound queue concurrency and prevent duplicate or wrong-platform job launch."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).resolve().parents[1] / 'linux-launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class QueueBounds(unittest.TestCase):
    def job(self, number, labels=None):
        return {'id': number, 'status': 'waiting', 'runs_on': ['linux-x86_64'] if labels is None else labels}

    def existing(self, number, conditions=None):
        return {'metadata': {'annotations': {'forge.fahrican.com/job-id': str(number)}},
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


if __name__ == '__main__':
    unittest.main()

from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import source_capture


class Session:
    def __init__(self, pages): self.pages, self.calls = pages, []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = unittest.mock.Mock(status_code=200)
        response.json.return_value = self.pages[url]
        return response


class SourceCapture(unittest.TestCase):
    def test_all_pages_are_read_and_initial_scope_is_not_lost(self):
        url = "https://cloud.example/v3/project/volumes/detail"
        session = Session({url: {"volumes": [{"id": "first"}], "volumes_links": [{"rel": "next", "href": url + "?marker=first&all_tenants=1"}]},
                           url + "?marker=first&all_tenants=1": {"volumes": [{"id": "second"}]}})
        objects = source_capture.paginated(session, "https://cloud.example/v3/project", "/volumes/detail", "volumes", {"all_tenants": 1})
        self.assertEqual([obj["id"] for obj in objects], ["first", "second"])
        self.assertEqual(session.calls[0][1]["params"], {"all_tenants": 1})
        self.assertIsNone(session.calls[1][1]["params"])

    def test_glance_relative_next_and_versioned_endpoints(self):
        url = "https://cloud.example/v2/images"
        session = Session({url: {"images": [{"id": "a"}], "next": "/v2/images?marker=a"},
                           url + "?marker=a": {"images": [{"id": "b"}]}})
        self.assertEqual(len(source_capture.paginated(session, "https://cloud.example/v2", "/v2/images", "images")), 2)
        self.assertEqual(source_capture.endpoint_path("https://cloud.example/v2.0", "/v2.0/floatingips"), "https://cloud.example/v2.0/floatingips")

    def test_foreign_origin_loop_and_duplicate_ids_are_rejected(self):
        url = "https://cloud.example/v2/images"
        for link in ("https://foreign.example/v2/images", "http://cloud.example/v2/images", "/outside/images", url):
            session = Session({url: {"images": [{"id": "a"}], "next": link}})
            with self.assertRaises(ValueError): source_capture.paginated(session, "https://cloud.example/v2", "/images", "images")
            self.assertEqual(len(session.calls), 1)
        session = Session({url: {"images": [{"id": "a"}, {"id": "a"}]}})
        with self.assertRaises(ValueError): source_capture.paginated(session, "https://cloud.example/v2", "/images", "images")

    def test_failed_api_response_never_becomes_an_empty_inventory(self):
        session = unittest.mock.Mock()
        session.get.return_value.status_code = 403
        with self.assertRaises(ValueError): source_capture.paginated(session, "https://cloud.example/v2", "/images", "images")

    def test_manila_microversion_is_retained_on_every_page(self):
        url = "https://cloud.example/v2/project/shares/detail"
        session = Session({url: {"shares": [{"id": "a"}], "shares_links": [{"rel": "next", "href": url + "?marker=a"}]},
                           url + "?marker=a": {"shares": [{"id": "b"}]}})
        headers = {"X-OpenStack-Manila-API-Version": "2.9"}
        source_capture.paginated(session, "https://cloud.example/v2/project", "/shares/detail", "shares", headers=headers)
        self.assertTrue(all(call[1]["headers"] == headers for call in session.calls))

    def test_public_summaries_do_not_copy_arbitrary_private_fields(self):
        obj = {"apiVersion": "v1", "kind": "PersistentVolume", "metadata": {"name": "disk", "annotations": {"password": "PRIVATE"}, "labels": {"password": "PRIVATE"}},
               "spec": {"csi": {"driver": "cinder.csi.openstack.org", "volumeHandle": "volume-id", "volumeAttributes": {"password": "PRIVATE", "pool": "rbd"}, "nodePublishSecretRef": {"name": "PRIVATE"}}},
               "status": {"phase": "Bound", "message": "PRIVATE"}}
        public = source_capture.public_volume(obj)
        self.assertNotIn("PRIVATE", json.dumps(public))
        self.assertEqual(public["spec"]["csi"]["volumeHandle"], "volume-id")
        obj.update(kind="Deployment", spec={"replicas": 2, "template": {"spec": {"containers": [{"env": [{"value": "PRIVATE"}]}]}}})
        self.assertNotIn("PRIVATE", json.dumps(source_capture.public_controller(obj)))
        self.assertIn("PRIVATE", json.dumps(source_capture.clean_object(obj)))  # Full source only in ciphertext.

    def test_new_private_directory_modes_overwrite_and_repository_refusal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            root.mkdir()
            with self.assertRaises(ValueError): source_capture.private_directory(root / "export", (root,))
            output = source_capture.private_directory(Path(temporary) / "export", (root,))
            source_capture.write_file(output, "state.sops.yaml", b"encrypted")
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertEqual((output / "state.sops.yaml").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError): source_capture.private_directory(output, (root,))
            with self.assertRaises(FileExistsError): source_capture.write_file(output, "state.sops.yaml", b"replacement")

    def test_missing_runtime_state_fails_before_provider_export(self):
        objects = [{"kind": "ConfigMap" if name == "services-backup-destination" else "Secret", "metadata": {"namespace": ns, "name": name}, "data": {}}
                   for ns, names in source_capture.STATE_INPUTS.items() for name in names]
        self.assertEqual(len(source_capture.state_inputs(objects)), 18)
        with self.assertRaises(KeyError): source_capture.state_inputs(objects[:-1])

    def test_complete_marker_is_absent_on_capture_failure_and_source_commands_are_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, source, output = [Path(temporary) / name for name in ("target", "source", "capture")]
            (root / "docs/migration").mkdir(parents=True)
            (root / "docs/migration/source-inventory.json").write_text(json.dumps({"commit": "frozen"}))
            source.mkdir()
            commands = []
            def command(args, **kwargs):
                commands.append(args)
                if args[-2:] == ["rev-parse", "HEAD"]: return b"frozen\n"
                if "diff" in args: return b""
                raise RuntimeError("PRIVATE")
            with patch.object(source_capture, "run", side_effect=command):
                with self.assertRaises(RuntimeError): source_capture.capture(root, source, output)
            self.assertFalse((output / "capture-manifest.json").exists())
            self.assertIn("get", commands[-1])
            self.assertIn("--no-write-lock-file", commands[-1])
            self.assertFalse(any(word in commands[-1] for word in ("apply", "patch", "delete", "create")))


if __name__ == "__main__": unittest.main()

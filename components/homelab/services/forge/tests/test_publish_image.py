"""The publisher pushes only to the single forge-runner tag baked into the archive."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "operations"))
spec = importlib.util.spec_from_file_location("publish_image", Path(__file__).parents[1] / "publish-image.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


def archive(directory, tags, mode="w:gz"):
    path = Path(directory) / "image.tar.gz"
    manifest = json.dumps([{"Config": "config.json", "RepoTags": tags, "Layers": []}]).encode()
    with tarfile.open(path, mode) as tar:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    return path


class DestinationTests(unittest.TestCase):
    def test_uses_the_archive_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("w", "w:gz"):
                path = archive(directory, ["git.fahrican.com/forge-runner/matrix-runtime:1.0.0"], mode)
                self.assertEqual(publish.destination(path), "git.fahrican.com/forge-runner/matrix-runtime:1.0.0")

    def test_rejects_foreign_or_ambiguous_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            for tags in ([], ["docker.io/library/alpine:3"],
                         ["git.fahrican.com/forge-runner/a:1", "git.fahrican.com/forge-runner/b:1"]):
                with self.subTest(tags=tags), self.assertRaises(SystemExit):
                    publish.destination(archive(directory, tags))


if __name__ == "__main__":
    unittest.main()

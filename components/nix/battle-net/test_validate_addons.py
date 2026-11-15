from pathlib import Path
import tempfile
import unittest

from validate_addons import validate


class AddonValidationTests(unittest.TestCase):
    def validate_tocs(self, tocs):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            addons = {}
            for folder, metadata in tocs.items():
                directory = bundle / folder
                directory.mkdir()
                (directory / f"{folder}.toc").write_text("## Interface: 16001\n" + metadata)
                addons[folder] = {
                    "version": "1",
                    "url": "https://example.com/addon.zip",
                    "hash": "sha256-" + "A" * 43 + "=",
                    "folders": [folder],
                }
            validate({"schemaVersion": 1, "flavour": "forever_classic", "addons": addons}, bundle)

    def test_empty_required_dependencies_do_not_consume_next_metadata_line(self):
        for header in ("Dependencies", "RequiredDeps"):
            for ending in ("\n", "\r\n"):
                with self.subTest(header=header, ending=ending):
                    self.validate_tocs({
                        "Main": f"## {header}: \t{ending}## OptionalDeps: NotInstalled{ending}",
                    })

    def test_missing_required_addon_is_rejected(self):
        for header in ("Dependencies", "RequiredDeps"):
            with self.subTest(header=header):
                with self.assertRaisesRegex(AssertionError, "Main requires missing addon Missing"):
                    self.validate_tocs({"Main": f"## {header}: \tMissing\n"})

    def test_bundled_and_blizzard_dependencies_are_accepted(self):
        self.validate_tocs({
            "Main": "## RequiredDeps: Companion, Blizzard_UIParent\n",
            "Companion": "",
        })


if __name__ == "__main__":
    unittest.main()

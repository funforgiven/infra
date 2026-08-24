import unittest

from albumclean_core import is_non_title_qualifier, normalize_album_title


class AlbumCleanCoreTest(unittest.TestCase):
    def test_strips_audio_quality_suffixes(self):
        cases = {
            "狂言 (48kHz/24bit)": "狂言",
            "Album [24-bit / 96 kHz FLAC]": "Album",
            "Album（Hi-Res Audio）": "Album",
            "Album (DSD256)": "Album",
            "Album (24/192)": "Album",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_album_title(source), expected)

    def test_strips_retail_suffixes(self):
        cases = {
            "残夢 (通常盤・初回プレス)": "残夢",
            "Album (Deluxe Edition)": "Album",
            "Album [Digital Media]": "Album",
            "Album (Limited Edition) (24-bit)": "Album",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_album_title(source), expected)

    def test_preserves_artistic_or_mastering_qualifiers(self):
        values = (
            "(What's the Story) Morning Glory?",
            "Album (Live at Wembley 1974)",
            "Album (Acoustic Version)",
            "Album (2011 Remaster)",
            "Album (Original Soundtrack)",
        )
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(normalize_album_title(value), value)

    def test_identifies_version_fields_without_parentheses(self):
        self.assertTrue(is_non_title_qualifier("48kHz/24bit"))
        self.assertTrue(is_non_title_qualifier("通常盤・初回プレス"))
        self.assertTrue(is_non_title_qualifier("96 kHz, 24-bit, FLAC"))
        self.assertFalse(is_non_title_qualifier("Live at Wembley 1974"))
        self.assertFalse(is_non_title_qualifier("2011 Remaster"))


if __name__ == "__main__":
    unittest.main()

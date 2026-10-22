#!/lsiopy/bin/python3
"""Prove the deployed LastGenre cleanup path cannot query Last.fm.

import.sh runs this before its daily genre cleanup and skips the cleanup when
it fails, so private-API drift after a Beets upgrade never blocks imports.
"""

from beets import config, library

# Use the deployed lastgenre settings from $BEETSDIR/config.yaml.
config.read()

from beetsplug.lastgenre import LastGenrePlugin  # noqa: E402


plugin = LastGenrePlugin()


def reject_network(*_args, **_kwargs):
    raise AssertionError("LastGenre attempted a Last.fm request")


plugin.client.fetch = reject_network
item = library.Item(
    title="Offline contract",
    artist="Contract Artist",
    album="Contract Album",
    albumartist="Contract Artist",
    genres=["hip-hop", "vocaloid"],
)
genres, label = plugin._get_genre(item)
assert genres == ["Hip Hop", "Vocaloid"], (
    f"offline alias or niche-genre cleanup drifted: {genres!r}"
)
assert "cleanup" in label, f"unexpected LastGenre path: {label}"
assert plugin.import_stages == [], "LastGenre auto-import hook is enabled"
print("LastGenre offline cleanup contract passed with zero Last.fm requests")

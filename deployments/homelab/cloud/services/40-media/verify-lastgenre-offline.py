#!/lsiopy/bin/python3
"""Prove the deployed LastGenre cleanup path cannot query Last.fm."""

from beets import config, library


config["lastgenre"].set(
    {
        "auto": False,
        "force": False,
        "cleanup_existing": True,
        "aliases": True,
        "canonical": False,
        "whitelist": False,
        "keep_existing": False,
        "count": 3,
        "fallback": None,
        "min_weight": 10,
        "prefer_specific": False,
        "source": "album",
        "title_case": True,
        "ignorelist": False,
    }
)

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

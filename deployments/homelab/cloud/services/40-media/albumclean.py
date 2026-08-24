"""Normalize non-artistic album format and retail qualifiers in Beets."""

from __future__ import annotations

from albumclean_core import is_non_title_qualifier, normalize_album_title
from beets import ui
from beets.plugins import BeetsPlugin


class AlbumCleanPlugin(BeetsPlugin):
    """Keep technical storefront metadata out of album presentation fields."""

    def __init__(self) -> None:
        super().__init__()
        self.register_listener("import_task_choice", self.import_task_choice)
        self.register_listener("import_task_apply", self.import_task_apply)

    @staticmethod
    def _normalize_info(info) -> None:
        if "album" in info:
            info.album = normalize_album_title(info.album)
        if "albumdisambig" in info and is_non_title_qualifier(
            info.albumdisambig
        ):
            info.albumdisambig = None

    def import_task_choice(self, session, task) -> None:
        """Normalize the selected candidate before duplicate detection."""

        del session
        if task.match is not None:
            self._normalize_info(task.match.info)

    def import_task_apply(self, session, task) -> None:
        """Normalize item fields before Beets writes or moves imported files."""

        del session
        for item in task.imported_items():
            item.album = normalize_album_title(item.album)
            if is_non_title_qualifier(item.albumdisambig):
                item.albumdisambig = ""
            if is_non_title_qualifier(item.disctitle):
                item.disctitle = ""

    @staticmethod
    def _normalize_library(lib, opts, args) -> None:
        """Migrate every matching album already managed by Beets."""

        del opts
        changed = 0
        for album in lib.albums(args):
            normalized_title = normalize_album_title(album.album)
            clear_disambiguation = is_non_title_qualifier(
                album.albumdisambig
            )
            items = list(album.items())
            clear_disc_titles = any(
                is_non_title_qualifier(item.disctitle) for item in items
            )

            if (
                normalized_title == album.album
                and not clear_disambiguation
                and not clear_disc_titles
            ):
                continue

            old_title = album.album
            album.album = normalized_title
            if clear_disambiguation:
                album.albumdisambig = ""
            album.store(inherit=True)

            # Reload the items after album.store propagated inherited fields.
            for item in album.items():
                if is_non_title_qualifier(item.disctitle):
                    item.disctitle = ""
                item.try_sync(write=True, move=True)

            changed += 1
            ui.print_(f"Normalized album metadata: {old_title} -> {normalized_title}")

        ui.print_(f"Normalized {changed} album(s)")

    def commands(self):
        command = ui.Subcommand(
            "albumclean",
            help="remove technical and retail qualifiers from album metadata",
        )
        command.func = self._normalize_library
        return [command]

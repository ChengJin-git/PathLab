"""Small object-size helpers. Global statistics live in the indexed inventory."""

import os
from pathlib import Path


class StorageStatsMixin:
    def _get_dir_size(self, directory: Path) -> int:
        return self._get_directory_stats(directory)["size"]

    def _get_file_info(self, path: Path):
        try:
            info = path.lstat()
            return {"path": str(path), "size": info.st_size, "exists": True}
        except FileNotFoundError:
            return {"path": str(path), "size": 0, "exists": False}

    def _get_directory_stats(self, directory: Path):
        size = count = 0
        pending = [str(directory)]
        while pending:
            try:
                with os.scandir(pending.pop()) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        else:
                            try:
                                size += entry.stat(follow_symlinks=False).st_size
                                count += 1
                            except FileNotFoundError:
                                continue
            except FileNotFoundError:
                continue
        return {"size": size, "file_count": count}

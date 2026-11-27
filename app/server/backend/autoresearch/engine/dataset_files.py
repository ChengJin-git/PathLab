"""Request-local directory inventories for research input preparation.

Do not glob a shared image/feature directory once per slide. Each directory is
enumerated once per preparation; new preparations see new or removed files.
"""

import errno
import os
from collections.abc import Callable
from pathlib import Path


class DatasetPreparationTimeout(TimeoutError):
    def __init__(self, name, stage, completed, total):
        self.dataset_name = name
        self.stage = stage
        self.completed = completed
        self.total = total
        super().__init__(f'Dataset preparation timed out while checking input files: {name}; '
                         f'stage={stage}, progress={completed}/{total}. Previous prepared inputs are preserved.')


class DatasetFiles:
    def __init__(self, check: Callable[[], None]):
        self.check = check
        self._features: dict[Path, tuple[dict[str, Path], list[Path]]] = {}
        self._labels: dict[Path, list[Path]] = {}
        self._parents: dict[Path, Path] = {}

    def resolve_source(self, source: Path) -> Path:
        """Resolve shared parent chains once, retaining per-file symlink semantics."""
        visited = set()
        while True:
            self.check()
            parent = source.parent
            if parent not in self._parents:
                self._parents[parent] = parent.resolve()
            source = self._parents[parent] / source.name
            if source in visited or len(visited) >= 40:
                raise RuntimeError(f'Symlink loop in research input: {source}')
            visited.add(source)
            try:
                target = source.readlink()
            except OSError as error:
                if error.errno not in {errno.EINVAL, errno.ENOENT, errno.ENOTDIR}:
                    raise
                return source
            source = target if target.is_absolute() else source.parent / target

    def label_tables(self, directory: Path) -> list[Path]:
        if directory not in self._labels:
            found = []
            try:
                with os.scandir(directory) as entries:
                    for index, entry in enumerate(entries):
                        if index % 256 == 0:
                            self.check()
                        name = entry.name
                        if (name == 'train.csv' or ('label' in name and name.endswith(('.csv', '.tsv')))) and entry.is_file():
                            found.append(Path(entry.path))
            except (FileNotFoundError, NotADirectoryError):
                pass
            self._labels[directory] = found
        return self._labels[directory]

    def feature_directory(self, directory: Path) -> tuple[dict[str, Path], list[Path]]:
        if directory not in self._features:
            files, children = {}, []
            try:
                with os.scandir(directory) as entries:
                    for index, entry in enumerate(entries):
                        if index % 256 == 0:
                            self.check()
                        if entry.name.startswith('.'):
                            continue
                        if entry.is_dir():
                            children.append(Path(entry.path))
                        elif entry.name.endswith(('.pt', '.pth')) and entry.is_file():
                            files[entry.name] = Path(entry.path)
            except (FileNotFoundError, NotADirectoryError):
                pass
            self._features[directory] = files, sorted(children)
        return self._features[directory]

    def features(self, slide, source: Path, roots: list[Path]) -> dict[str, str]:
        result = {}
        for item in (slide.associated_files or {}).get('autoresearch_features', {}).values():
            path = Path(item.get('feature_path', ''))
            if path.is_file():
                result[item.get('extractor_name') or path.parent.name] = str(path)
        original = Path(slide.original_filename or source.name).stem
        stems = list(dict.fromkeys([slide.wsi_id, Path(slide.wsi_path).stem, original, source.stem]))
        if '__' in original:
            stems.append(original.split('__', 1)[1])
        candidates = list(roots)
        lowered = [part.lower() for part in source.parts]
        if 'original_data' in lowered:
            index = lowered.index('original_data')
            if len(source.parts) > index + 2 and lowered[index + 1] == 'tcga':
                cohort = source.parts[index + 2]
                for name in dict.fromkeys([cohort, cohort.upper(), cohort.lower()]):
                    candidates.append(Path(*source.parts[:index]) / 'Patches' / 'TCGA' / f'TCGA-{name}' / 'pt_files')
        for root in dict.fromkeys(candidates):
            _, extractors = self.feature_directory(root)
            for extractor in extractors:
                if extractor.name in result:
                    continue
                files, parameter_dirs = self.feature_directory(extractor)
                for stem in stems:
                    match = files.get(f'{stem}.pt') or files.get(f'{stem}.pth')
                    if match is None:
                        for directory in parameter_dirs:
                            nested, _ = self.feature_directory(directory)
                            match = nested.get(f'{stem}.pt')
                            if match is not None:
                                break
                    if match is not None:
                        result[extractor.name] = str(match)
                        break
        return result

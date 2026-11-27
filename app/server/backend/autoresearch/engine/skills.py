"""Complete, bounded skill packages with session-owned resource snapshots."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.common.config import Config

MAX_SKILL_CHARS = 128000
MAX_SKILLS = 32
MAX_IMPORT_BYTES = 64 * 1024 * 1024
MAX_PACKAGE_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_FILES = 4096
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "__MACOSX"}


class SkillImportError(ValueError):
    """Stable codes translated by the client, never raw network/decoder errors."""


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 512
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise SkillImportError("skillUnsafePath")
    return str(path)


def parse_markdown(content: str) -> tuple[dict, str]:
    text = content.lstrip("\ufeff").strip()
    if len(text) > MAX_SKILL_CHARS:
        raise SkillImportError("skillTooLarge")
    if (
        not text
        or "\x00" in text
        or re.match(r"(?is)^\s*(<!doctype\s+html|<html\b)", text)
    ):
        raise SkillImportError("skillNotMarkdown")
    metadata = {}
    if text.startswith(("---\n", "---\r\n")):
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)\Z", text, re.DOTALL)
        if not match:
            raise SkillImportError("skillInvalidMetadata")
        try:
            metadata = yaml.safe_load(match[1]) or {}
        except yaml.YAMLError as exc:
            raise SkillImportError("skillInvalidMetadata") from exc
        if not isinstance(metadata, dict):
            raise SkillImportError("skillInvalidMetadata")
        text = match[2].strip()
    if not text:
        raise SkillImportError("skillNotMarkdown")
    return metadata, text


def decode_markdown(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillImportError("skillEncoding") from exc
    parse_markdown(text)
    return text


class ResearchSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=MAX_SKILL_CHARS)
    source_url: str | None = Field(None, max_length=2048)
    package_id: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    entrypoint: str = "SKILL.md"

    @field_validator("entrypoint")
    @classmethod
    def valid_path(cls, value):
        if not value.lower().endswith(('.md', '.markdown')):
            raise SkillImportError('skillMissingEntry')
        return safe_path(value)

    @field_validator("content")
    @classmethod
    def valid_markdown(cls, value):
        parse_markdown(value)
        return value


def package_directory(user_id: str) -> Path:
    owner = hashlib.sha256(user_id.encode()).hexdigest()
    return Config.get_autoresearch_dir() / "skill-imports" / owner


def unpack_zip(
    data: bytes, *, strip_root: bool = True
) -> dict[str, tuple[bytes, bool]]:
    if len(data) > MAX_PACKAGE_BYTES:
        raise SkillImportError("skillTooLarge")
    files = {}
    total = 0
    folded = set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > MAX_FILES * 2:
                raise SkillImportError("skillTooLarge")
            for item in archive.infolist():
                name = safe_path(item.filename.rstrip("/"))
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode) or (
                    stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))
                ):
                    raise SkillImportError("skillUnsafePath")
                if item.is_dir() or set(PurePosixPath(name).parts) & SKIP_DIRS:
                    continue
                total += item.file_size
                if (
                    item.file_size > MAX_FILE_BYTES
                    or total > MAX_PACKAGE_BYTES
                    or len(files) >= MAX_FILES
                ):
                    raise SkillImportError("skillTooLarge")
                if name.casefold() in folded:
                    raise SkillImportError("skillDuplicatePath")
                folded.add(name.casefold())
                files[name] = (archive.read(item), bool(mode & 0o111))
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise SkillImportError("skillInvalidArchive") from exc
    # Remove only the enclosing archive directory, preserving sibling skill paths.
    if (
        strip_root
        and files
        and all("/" in name for name in files)
        and len({name.split("/")[0] for name in files}) == 1
    ):
        files = {name.split("/", 1)[1]: value for name, value in files.items()}
    return files


def inspect_files(
    files: dict[str, tuple[bytes, bool]],
    user_id: str,
    source_url: str | None = None,
    selected: str | None = None,
) -> tuple[dict, dict[str, tuple[bytes, bool]]]:
    """Validate the full file tree and return metadata plus normalized bytes, without caching."""
    clean = {}
    total = 0
    folded = set()
    for name, (data, executable) in files.items():
        name = safe_path(name)
        if set(PurePosixPath(name).parts) & SKIP_DIRS:
            continue
        if name.casefold() in folded:
            raise SkillImportError("skillDuplicatePath")
        folded.add(name.casefold())
        total += len(data)
        if (
            len(data) > MAX_FILE_BYTES
            or total > MAX_PACKAGE_BYTES
            or len(clean) >= MAX_FILES
        ):
            raise SkillImportError("skillTooLarge")
        clean[name] = (data, executable)
    entries = sorted(
        name for name in clean if PurePosixPath(name).name.lower() == "skill.md"
    )
    if any(
        str(parent).casefold() in folded
        for name in clean
        for parent in PurePosixPath(name).parents
        if str(parent) != "."
    ):
        raise SkillImportError("skillDuplicatePath")
    if selected:
        selected = safe_path(selected)
        if selected in clean and selected.lower().endswith(".md"):
            entries = [selected]
        else:
            entries = [
                name for name in entries if name.startswith(selected.rstrip("/") + "/")
            ]
    if not entries and len(clean) == 1 and next(iter(clean)).lower().endswith(".md"):
        entries = list(clean)
    if not entries:
        raise SkillImportError("skillMissingEntry")
    if len(entries) > 128:
        raise SkillImportError("skillTooManyEntries")
    result, warnings = [], set()
    for name in entries:
        content = decode_markdown(clean[name][0])
        metadata, body = parse_markdown(content)
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = metadata.get("name") or (
            heading[1] if heading else PurePosixPath(name).parent.name or "Skill"
        )
        result.append(
            {
                "name": str(title)[:80],
                "content": content,
                "entrypoint": name,
                "source_url": source_url,
            }
        )
        if (
            "allowed-tools" in metadata
            or "compatibility" in metadata
            or re.search(r"\b(?:mcp__|AskUserQuestion|TodoWrite|image_gen\.)", body)
        ):
            warnings.add("skillRuntimeRequirements")
        # Relative Markdown links are checkable without guessing shell snippets.
        for target in re.findall(r"\]\(([^\s)#]+)(?:#[^)]*)?\)", body):
            if "://" in target or target.startswith(("#", "mailto:", "/")):
                continue
            parts = list(PurePosixPath(name).parent.parts)
            for part in PurePosixPath(target).parts:
                if part == "..":
                    if parts:
                        parts.pop()
                elif part != ".":
                    parts.append(part)
            if "/".join(parts) not in clean:
                warnings.add("skillMissingResources")
    manifest = {
        name: {"sha256": hashlib.sha256(data).hexdigest(), "executable": executable}
        for name, (data, executable) in sorted(clean.items())
    }
    package_id = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    return {
        "skills": [dict(item, package_id=package_id) for item in result],
        "files": [{"path": name, "size": len(value[0])} for name, value in sorted(clean.items())],
        "total_bytes": total,
        "warnings": sorted(warnings),
    }, clean


def import_files(files, user_id, source_url=None, selected=None):
    preview, clean = inspect_files(files, user_id, source_url, selected)
    package_id = preview['skills'][0]['package_id']
    directory = package_directory(user_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Imports are previews. Session creation copies them durably into its own workspace.
    for old in directory.glob("*.zip"):
        if old.stat().st_mtime < time.time() - 86400:
            old.unlink()
    target = directory / f"{package_id}.zip"
    if not target.exists():
        if len(list(directory.glob("*.zip"))) >= 20:
            raise SkillImportError("skillImportQuota")
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
            temp = Path(temporary.name)
        try:
            with zipfile.ZipFile(
                temp, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for name, (data, executable) in clean.items():
                    info = zipfile.ZipInfo(name)
                    info.external_attr = (
                        stat.S_IFREG | (0o755 if executable else 0o644)
                    ) << 16
                    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    target.touch()
    return preview


def snapshot_skills(
    skills: list[ResearchSkill], root: Path | None = None, user_id: str = ""
) -> list[dict]:
    if len(skills) > MAX_SKILLS:
        raise SkillImportError("skillTooManySelected")
    snapshots, packages = [], {}
    seen = set()
    total = 0
    for index, skill in enumerate(skills, 1):
        metadata, body = parse_markdown(skill.content)
        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip():
            description = body[:1024].replace("\n", " ")
        header = {"name": skill.name, "description": description[:1024]}
        for field in ["license", "compatibility"]:
            if isinstance(metadata.get(field), str):
                header[field] = metadata[field]
        document = (
            "---\n"
            + yaml.safe_dump(header, allow_unicode=True, sort_keys=False)
            + "---\n\n"
            + body
            + "\n"
        )
        if skill.package_id:
            key = (skill.package_id, skill.entrypoint)
            if key in seen:
                raise SkillImportError("skillDuplicatePath")
            seen.add(key)
            path = package_directory(user_id) / f"{skill.package_id}.zip"
            if not root or not path.is_file() or path.stat().st_mtime < time.time() - 86400:
                raise SkillImportError("skillImportExpired")
            if skill.package_id not in packages:
                # The normalized cache is trusted only after archive validation again.
                packages[skill.package_id] = unpack_zip(
                    path.read_bytes(), strip_root=False
                )
                total += sum(
                    len(data) for data, _ in packages[skill.package_id].values()
                )
                if total > 2 * MAX_PACKAGE_BYTES:
                    raise SkillImportError("skillTooLarge")
            if skill.entrypoint not in packages[skill.package_id]:
                raise SkillImportError("skillMissingEntry")
        snapshots.append(
            {
                "id": f"user-skill-{index}",
                "name": skill.name,
                "content": document,
                "source_url": skill.source_url,
                "package_id": skill.package_id,
                "entrypoint": skill.entrypoint,
                "sha256": hashlib.sha256(document.encode()).hexdigest(),
            }
        )
    if root:
        for package_id, files in packages.items():
            directory = root / ".opencode/packages" / package_id
            directory.mkdir(parents=True, exist_ok=True)
            for name, (data, executable) in files.items():
                target = directory / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o755 if executable else 0o644)
    return snapshots


def install_skills(root: Path, skills: list[dict]) -> None:
    for skill in skills:
        if not re.fullmatch(r"user-skill-(?:[1-9]|[12][0-9]|3[0-2])", skill["id"]):
            raise SkillImportError("skillUnsafePath")
        directory = root / ".opencode/skills" / skill["id"]
        if not directory.resolve().is_relative_to(root.resolve()):
            raise SkillImportError("skillUnsafePath")
        directory.mkdir(parents=True, exist_ok=True)
        document = skill["content"]
        if skill.get("package_id"):
            package_id = skill["package_id"]
            if not re.fullmatch(r"[a-f0-9]{64}", package_id):
                raise SkillImportError("skillUnsafePath")
            source = (
                root
                / ".opencode/packages"
                / package_id
                / safe_path(skill["entrypoint"])
            )
            if not source.resolve().is_relative_to(
                (root / ".opencode/packages" / package_id).absolute()
            ):
                raise SkillImportError("skillUnsafePath")
            if not source.is_file():
                raise SkillImportError("skillMissingResources")
            source.write_text(document, encoding="utf-8")
            header, _ = parse_markdown(document)
            from ..runtime.container_backend import backend, container_path
            source_text = container_path(str(source)) if backend() == 'docker' else str(source)
            parent_text = container_path(str(source.parent)) if backend() == 'docker' else str(source.parent)
            document = (
                "---\n"
                + yaml.safe_dump(header, allow_unicode=True, sort_keys=False)
                + "---\n\nRead the complete skill at `"
                + source_text
                + "`. "
                + "Its resource base directory is `"
                + parent_text
                + "`. "
                + "Resolve all relative scripts, references and sibling resources from that directory, not this wrapper. "
                + "Run code only through the PathLab execution workflow when applicable. "
                + "Use the session output language for user-facing prose; preserve code and source quotations.\n"
            )
        entry = directory / "SKILL.md"
        if entry.is_symlink():
            raise SkillImportError("skillUnsafePath")
        entry.write_text(document, encoding="utf-8")

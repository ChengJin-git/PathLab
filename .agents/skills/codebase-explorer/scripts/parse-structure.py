#!/usr/bin/env python3
"""
parse-structure.py
Recursively walks a directory tree and outputs a JSON file-tree,
grouped by directory, excluding noise folders.
Used by the codebase-explorer Codex skill.
"""

import os
import json
import argparse
from pathlib import Path

EXCLUDE_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build",
    ".venv", "venv", ".next", ".nuxt", "coverage", ".pytest_cache",
    ".mypy_cache", "target", "out", ".idea", ".vscode", "eggs",
    ".eggs", "htmlcov", "site-packages",
}

SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
    ".kt", ".swift", ".c", ".cpp", ".h", ".hpp", ".cs", ".rb",
    ".php", ".vue", ".svelte", ".sh", ".yaml", ".yml", ".toml",
    ".json", ".md",
}

def build_tree(root: Path, max_depth: int = 10) -> dict:
    tree = {}
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded dirs in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS and not d.startswith(".")]

        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)
        if depth > max_depth:
            continue

        relevant_files = [
            f for f in filenames
            if Path(f).suffix in SOURCE_EXTENSIONS
        ]

        if relevant_files or str(rel_dir) == ".":
            key = str(rel_dir) if str(rel_dir) != "." else "(root)"
            tree[key] = {
                "files": sorted(relevant_files),
                "has_readme": "README.md" in filenames or "readme.md" in filenames,
            }

    return tree

def main():
    parser = argparse.ArgumentParser(description="Parse repo structure for codebase-explorer skill")
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument("--output", default="/tmp/tree.json", help="Output JSON path")
    parser.add_argument("--max-depth", type=int, default=10)
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"Error: {root} does not exist")
        return 1

    tree = build_tree(root, args.max_depth)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)

    # Print a human-readable summary
    total_dirs = len(tree)
    total_files = sum(len(v["files"]) for v in tree.values())
    readme_dirs = [k for k, v in tree.items() if v["has_readme"]]

    print(f"✓ Scanned {total_dirs} directories, {total_files} source files")
    print(f"✓ READMEs found in: {readme_dirs if readme_dirs else ['(root only)']}")
    print(f"✓ Tree written to: {args.output}")

    # Print top-level structure
    print("\nDirectory overview:")
    for dir_key, info in sorted(tree.items()):
        indent = "  " * (dir_key.count("/") if dir_key != "(root)" else 0)
        readme_flag = " 📖" if info["has_readme"] else ""
        print(f"{indent}{dir_key}/ ({len(info['files'])} files){readme_flag}")

if __name__ == "__main__":
    main()

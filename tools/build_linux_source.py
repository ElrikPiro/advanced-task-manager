#!/usr/bin/env python3
"""Build repeatable Linux source and test source archives from an allowlist."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable


SOURCE_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_ROOT = "advanced-task-manager"
RUNTIME_FILES = (
    "ARCHITECTURE.md",
    "Dockerfile",
    "Makefile",
    "README.md",
    "compose.yaml",
    "requirements-test.lock",
    "requirements.lock",
    "requirements.txt",
    "backend/app.sh",
    "backend/backend.py",
    "tools/bash/local-quality-checks.sh",
    "tools/build_linux_source.py",
)
TEST_FILES = (
    "requirements-test.lock",
    "tools/bash/local-quality-checks.sh",
)


def collect_file_list(paths: Iterable[str], trees: tuple[str, ...]) -> list[Path]:
    files: set[Path] = set()
    for relative_path in paths:
        path = SOURCE_ROOT / relative_path
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Required source file is missing or unsafe: {relative_path}")
        files.add(path)

    for relative_tree in trees:
        tree = SOURCE_ROOT / relative_tree
        if not tree.is_dir() or tree.is_symlink():
            raise FileNotFoundError(f"Required source directory is missing or unsafe: {relative_tree}")
        extension = ".py" if relative_tree == "backend/src" or relative_tree == "backend/tests" else ".md"
        for path in tree.rglob(f"*{extension}"):
            relative_path = path.relative_to(SOURCE_ROOT)
            if path.is_symlink() or any(part.startswith(".") or part == "__pycache__" for part in relative_path.parts):
                continue
            if path.is_file():
                files.add(path)

    return sorted(files, key=lambda path: path.relative_to(SOURCE_ROOT).as_posix())


def tar_info(name: str, is_directory: bool, executable: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = 0o755 if is_directory or executable else 0o644
    if is_directory:
        info.type = tarfile.DIRTYPE
    return info


def write_archive(files: list[Path], output_path: Path) -> None:
    archive_files = {
        f"{ARCHIVE_ROOT}/{path.relative_to(SOURCE_ROOT).as_posix()}": path
        for path in files
    }
    directories = {ARCHIVE_ROOT}
    for name in archive_files:
        parent = Path(name).parent
        while parent.as_posix() != ".":
            directories.add(parent.as_posix())
            parent = parent.parent

    with output_path.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", filename="", compresslevel=9, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for directory in sorted(directories):
                    archive.addfile(tar_info(f"{directory}/", is_directory=True))
                for name in sorted(archive_files):
                    source = archive_files[name]
                    executable = bool(source.stat().st_mode & 0o111)
                    info = tar_info(name, is_directory=False, executable=executable)
                    data = source.read_bytes()
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))


def build_deterministic_pair(files: list[Path], output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="linux-source-check-", dir=output_path.parent) as temp_dir:
        first = Path(temp_dir) / "first.tar.gz"
        second = Path(temp_dir) / "second.tar.gz"
        write_archive(files, first)
        write_archive(files, second)
        first_digest = hashlib.sha256(first.read_bytes()).hexdigest()
        second_digest = hashlib.sha256(second.read_bytes()).hexdigest()
        if first_digest != second_digest:
            raise RuntimeError(f"Archive output was not reproducible: {output_path.name}")
        os.replace(first, output_path)
    return first_digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SOURCE_ROOT / "dist/linux-source",
        help="Directory for the runtime and separate test source archives.",
    )
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else SOURCE_ROOT / args.output_dir

    runtime_files = collect_file_list(RUNTIME_FILES, ("backend/src", "docs"))
    test_files = collect_file_list(TEST_FILES, ("backend/tests",))
    artifacts = (
        (runtime_files, output_dir / "advanced-task-manager-linux-source.tar.gz"),
        (test_files, output_dir / "advanced-task-manager-linux-tests.tar.gz"),
    )
    for files, output_path in artifacts:
        digest = build_deterministic_pair(files, output_path)
        print(f"{output_path}: SHA-256 {digest}; files={len(files)}; repeat=identical")


if __name__ == "__main__":
    main()

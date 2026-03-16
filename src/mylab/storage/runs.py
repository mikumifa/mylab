from __future__ import annotations

from pathlib import Path

from mylab.config import RUN_SUBDIRS
from mylab.domain import RunManifest, RunPaths
from mylab.storage.io import ensure_dir, read_json, write_json


def init_run_dirs(run_root: Path) -> RunPaths:
    ensure_dir(run_root)
    paths = {name: ensure_dir(run_root / name) for name in RUN_SUBDIRS}
    return RunPaths(root=run_root, **paths)


def load_manifest(run_dir: Path) -> RunManifest:
    payload = read_json(run_dir / "manifests" / "run.json")
    return RunManifest.from_dict(payload)


def save_manifest(paths: RunPaths, manifest: RunManifest) -> None:
    write_json(paths.manifests / "run.json", manifest.to_dict())

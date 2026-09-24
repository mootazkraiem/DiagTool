"""
model_promotion.py
──────────────────
staging → validate → promote.

A staged version (``assets/models_staging/<version>/``) reaches production
(``assets/models/``) only through ``promote``:

1. every family in the staged version is validated (Step 9 schema-2 checks:
   hashes, feature pipeline version, feature schema, scaler, threshold,
   train/holdout disjointness). One failure stops everything; production is
   not touched;
2. the families to promote are copied next to production and validated again
   there, so what is swapped in is exactly what was checked;
3. each existing production family is moved to
   ``assets/models_archive/<stamp>/<family>`` and the validated copy renamed
   into place - a rename, so a reader sees the old family or the new one,
   never a mixture;
4. every promoted family is loaded from production once more. Any failure in
   3 or 4 restores the archived families.

Nothing else in production is modified. The legacy shared state-classifier
files are not read or written.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
from pathlib import Path

from backend.ml.runtime.model_manifest import MANIFEST_NAME, FamilyModel, ManifestError, load_family_model


class PromotionError(RuntimeError):
    pass


def staged_families(version_dir: Path) -> list[str]:
    return sorted(p.name for p in Path(version_dir).iterdir() if (p / MANIFEST_NAME).is_file())


def validate_staging(version_dir: Path) -> dict[str, FamilyModel]:
    """Every staged family, loaded and validated; raises PromotionError listing all failures."""
    version_dir = Path(version_dir)
    if not version_dir.is_dir():
        raise PromotionError(f"no staged version at {version_dir}")
    families = staged_families(version_dir)
    if not families:
        raise PromotionError(f"{version_dir} contains no families")
    loaded: dict[str, FamilyModel] = {}
    failures: list[str] = []
    for f in families:
        try:
            loaded[f] = load_family_model(version_dir, f)
        except ManifestError as exc:
            failures.append(str(exc))
    if failures:
        raise PromotionError("staged version failed validation:\n" + "\n".join(failures))
    return loaded


def promote(version_dir: Path, production_root: Path, archive_root: Path,
            families: list[str] | None = None) -> dict:
    version_dir = Path(version_dir)
    production_root = Path(production_root)
    archive_root = Path(archive_root)
    if production_root.resolve() in (version_dir.resolve(), *version_dir.resolve().parents):
        raise PromotionError("the staged version lies inside the production root")

    staged = validate_staging(version_dir)
    selected = sorted(families) if families else sorted(staged)
    unknown = [f for f in selected if f not in staged]
    if unknown:
        raise PromotionError(f"families not in the staged version: {unknown}")

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    incoming = production_root / f".incoming-{stamp}"
    archive = archive_root / stamp
    incoming.mkdir(parents=True)
    try:
        for f in selected:
            shutil.copytree(version_dir / f, incoming / f)
            load_family_model(incoming, f)                   # validate the exact bytes to be swapped in
    except Exception:
        shutil.rmtree(incoming, ignore_errors=True)
        raise

    swapped: list[tuple[str, bool]] = []                     # (family, had a previous version)
    try:
        for f in selected:
            current = production_root / f
            had = current.exists()
            if had:
                archive.mkdir(parents=True, exist_ok=True)
                current.rename(archive / f)
            (incoming / f).rename(current)
            swapped.append((f, had))
        for f in selected:
            load_family_model(production_root, f)
    except Exception as exc:
        _roll_back(swapped, production_root, archive)
        shutil.rmtree(incoming, ignore_errors=True)
        raise PromotionError(f"promotion rolled back: {exc}") from exc

    shutil.rmtree(incoming, ignore_errors=True)
    record = {"version": version_dir.name, "promoted_at": stamp, "families": selected,
              "archived": [f for f, had in swapped if had], "archive_dir": str(archive)}
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "promotion.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def _roll_back(swapped: list[tuple[str, bool]], production_root: Path, archive: Path) -> None:
    for f, had in reversed(swapped):
        current = production_root / f
        if current.exists():
            shutil.rmtree(current)
        if had and (archive / f).exists():
            (archive / f).rename(current)

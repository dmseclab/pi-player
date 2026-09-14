from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .config import ASSET_DIR, DB_PATH, DATA_DIR, TMP_DIR
from .db import db, now_iso


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity_report(*, verify_checksums: bool = False) -> dict[str, Any]:
    """Compare asset metadata with persistent storage without deleting anything."""
    missing: list[dict[str, Any]] = []
    size_mismatch: list[dict[str, Any]] = []
    checksum_mismatch: list[dict[str, Any]] = []
    referenced_paths: set[Path] = set()

    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, storage_path, size_bytes, checksum_sha256
            FROM assets
            WHERE deleted_at IS NULL AND type = 'image'
            ORDER BY created_at
            """
        ).fetchall()

        for row in rows:
            path_text = row["storage_path"]
            if not path_text:
                missing.append({"id": row["id"], "name": row["name"], "reason": "no storage path"})
                continue

            path = Path(path_text).resolve()
            referenced_paths.add(path)
            if ASSET_DIR.resolve() not in path.parents or not path.is_file():
                missing.append({"id": row["id"], "name": row["name"], "path": str(path)})
                continue

            actual_size = path.stat().st_size
            expected_size = row["size_bytes"]
            if expected_size is not None and actual_size != expected_size:
                size_mismatch.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "expected": expected_size,
                        "actual": actual_size,
                    }
                )

            if verify_checksums and row["checksum_sha256"]:
                actual_hash = _sha256(path)
                if actual_hash != row["checksum_sha256"]:
                    checksum_mismatch.append(
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "expected": row["checksum_sha256"],
                            "actual": actual_hash,
                        }
                    )

    orphan_files = [
        str(path)
        for path in sorted(ASSET_DIR.glob("*"))
        if path.is_file() and path.resolve() not in referenced_paths
    ]
    temp_files = [str(path) for path in sorted(TMP_DIR.glob("*")) if path.is_file()]
    usage = shutil.disk_usage(DATA_DIR)
    issues = len(missing) + len(size_mismatch) + len(checksum_mismatch)

    return {
        "ok": issues == 0,
        "checked_at": now_iso(),
        "database": str(DB_PATH),
        "asset_dir": str(ASSET_DIR),
        "image_assets_checked": len(referenced_paths) + len([x for x in missing if x.get("reason") == "no storage path"]),
        "missing_assets": missing,
        "size_mismatch": size_mismatch,
        "checksum_mismatch": checksum_mismatch,
        "orphan_files": orphan_files,
        "temp_files": temp_files,
        "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
    }

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

_SAFE_EXT = re.compile(r"^[a-z0-9]{1,8}$")


@dataclass(frozen=True)
class StoredFile:

    storage_path: str
    checksum: str
    byte_size: int
    deduplicated: bool


def upload_root() -> Path:
    root = Path(settings.UPLOAD_ROOT)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root


def _extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    return ext if _SAFE_EXT.match(ext) else "bin"


def save_bytes(content: bytes, *, filename: str, subdir: str) -> StoredFile:
    checksum = hashlib.sha256(content).hexdigest()
    ext = _extension(filename)
    rel = f"{subdir}/{checksum[:2]}/{checksum}.{ext}"
    target = upload_root() / rel

    if target.exists() and target.stat().st_size == len(content):
        return StoredFile(rel, checksum, len(content), deduplicated=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(content)
    tmp.replace(target)
    return StoredFile(rel, checksum, len(content), deduplicated=False)


def resolve(storage_path: str) -> Path:
    root = upload_root().resolve()
    candidate = (root / storage_path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"storage path escapes the upload root: {storage_path!r}")
    return candidate


def read_bytes(storage_path: str) -> bytes:
    return resolve(storage_path).read_bytes()

"""Object storage abstraction.

StorageBackend protocol + two implementations:
- LocalDiskBackend: dev/test only
- S3Backend: any S3-compatible endpoint (AWS S3, MinIO); Azure Blob slots in
  as a third backend without touching callers.

Every key is manager-scoped by construction:
    {manager_id}/employee-repo/{batch_id}/{uuid}-{safe_filename}
    {manager_id}/gets/{batch_id}/{uuid}-{safe_filename}
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.config import settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    checksum_sha256: str


class StorageError(Exception):
    pass


def _sanitize_filename(name: str) -> str:
    name = Path(name).name  # strip any path components
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "file"


def build_key(*, manager_id: str, kind: str, batch_id: str, filename: str) -> str:
    safe = _sanitize_filename(filename)
    prefix = "employee-repo" if kind == BatchKindValue.EMPLOYEE_REPO else "gets"
    return f"{manager_id}/{prefix}/{batch_id}/{uuid.uuid4().hex[:8]}-{safe}"


class BatchKindValue:
    EMPLOYEE_REPO = "EMPLOYEE_REPO"
    GETS = "GETS"


class StorageBackend(Protocol):
    def put(self, key: str, stream: BinaryIO, length: int) -> StoredObject: ...
    def get_bytes(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalDiskBackend:
    """Dev/test backend. Never selected in production config."""

    def __init__(self, root: str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        # Defense in depth: refuse traversal even though keys are generated.
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise StorageError("invalid storage key")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def put(self, key: str, stream: BinaryIO, length: int) -> StoredObject:
        import hashlib

        data = stream.read()
        digest = hashlib.sha256(data).hexdigest()
        self._path(key).write_bytes(data)
        return StoredObject(key=key, size=len(data), checksum_sha256=digest)

    def get_bytes(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"object not found: {key}") from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class S3Backend:
    """boto3 is imported lazily so dev machines without it keep working."""

    def __init__(self) -> None:
        import boto3  # noqa: PLC0415 — lazy import

        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET is required for the s3 storage backend")
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    def put(self, key: str, stream: BinaryIO, length: int) -> StoredObject:
        import hashlib

        data = stream.read()
        digest = hashlib.sha256(data).hexdigest()
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentLength=length)
        return StoredObject(key=key, size=length, checksum_sha256=digest)

    def get_bytes(self, key: str) -> bytes:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except ClientError as exc:
            raise StorageError(f"s3 get failed for {key}") from exc

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is None:
        if settings.storage_backend == "s3":
            _backend = S3Backend()
        else:
            if settings.is_production:
                raise StorageError(
                    "local disk storage must not be used in production; set STORAGE_BACKEND=s3"
                )
            _backend = LocalDiskBackend(settings.local_storage_root)
    return _backend


def reset_storage_for_tests() -> None:
    global _backend
    _backend = None

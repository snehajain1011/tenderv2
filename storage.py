from __future__ import annotations

import os
from pathlib import Path


class StorageBackend:
    def put_bytes(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("LOCAL_STORAGE_ROOT", "workspaces"))

    def put_bytes(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def get_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class MinioStorage(StorageBackend):
    def __init__(self) -> None:
        raise NotImplementedError("MinIO/S3 production adapter is configured in docker-compose but not used by local demo mode yet.")


def storage_from_env() -> StorageBackend:
    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend == "local":
        return LocalStorage()
    if backend in {"s3", "minio"}:
        return MinioStorage()
    raise ValueError(f"Unsupported storage backend: {backend}")

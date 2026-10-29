"""Statement file storage: local disk for development, private S3-compatible
object storage for ephemeral hosting. No public URLs or browser credentials.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .config import UPLOAD_DIR


def cloud_enabled() -> bool:
    return bool(os.getenv("SPENDFLOW_S3_BUCKET"))


def _client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=os.getenv("SPENDFLOW_S3_ENDPOINT") or None,
        aws_access_key_id=os.environ["SPENDFLOW_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["SPENDFLOW_S3_SECRET_KEY"],
        region_name=os.getenv("SPENDFLOW_S3_REGION", "auto"),
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def persist(path: Path, user_id: int) -> str:
    """Store a parsed file permanently; return an opaque private storage URI."""
    if not cloud_enabled():
        return str(path)
    bucket = os.environ["SPENDFLOW_S3_BUCKET"]
    key = f"statements/{user_id}/{path.name}"
    _client().upload_file(str(path), bucket, key)
    return f"s3://{bucket}/{key}"


def _parse_uri(stored_path: str):
    u = urlparse(stored_path)
    if u.scheme != "s3":
        return None
    bucket = os.environ.get("SPENDFLOW_S3_BUCKET")
    if not bucket or u.netloc != bucket or not u.path.startswith("/statements/"):
        raise ValueError("Stored statement location is not authorized")
    return bucket, u.path[1:]


def get_file(stored_path: str, user_id: int) -> tuple[str, object]:
    """Return type and a file-like S3 response, or a validated local file."""
    parsed = _parse_uri(stored_path)
    if parsed:
        bucket, key = parsed
        if not key.startswith(f"statements/{user_id}/"):
            raise ValueError("Statement owner mismatch")
        return "cloud", _client().get_object(Bucket=bucket, Key=key)["Body"]
    path = Path(stored_path).resolve()
    if UPLOAD_DIR.resolve() not in path.parents or not path.exists():
        raise FileNotFoundError("The original statement is no longer stored")
    return "local", path


def delete_file(stored_path: str, user_id: int) -> None:
    parsed = _parse_uri(stored_path)
    if parsed:
        bucket, key = parsed
        if not key.startswith(f"statements/{user_id}/"):
            raise ValueError("Statement owner mismatch")
        _client().delete_object(Bucket=bucket, Key=key)
    else:
        path = Path(stored_path).resolve()
        if UPLOAD_DIR.resolve() in path.parents:
            path.unlink(missing_ok=True)


def delete_user_files(user_id: int) -> None:
    if cloud_enabled():
        bucket = os.environ["SPENDFLOW_S3_BUCKET"]
        prefix = f"statements/{user_id}/"
        client = _client()
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys = [{"Key": x["Key"]} for x in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
    else:
        import shutil
        shutil.rmtree(UPLOAD_DIR / str(user_id), ignore_errors=True)


def iter_body(body, chunk_size: int = 65536):
    try:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        body.close()

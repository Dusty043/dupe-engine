from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _s3_bucket() -> str:
    return os.environ.get("DUPE_S3_BUCKET", "")


def _aws_region() -> str:
    return os.environ.get("DUPE_AWS_REGION", "us-east-1")


def _aws_mode() -> bool:
    return bool(_s3_bucket())


# ---------------------------------------------------------------------------
# S3 URI helpers
# ---------------------------------------------------------------------------

def make_input_prefix(job_id: str) -> str:
    bucket = _s3_bucket()
    if not bucket:
        return ""
    return f"s3://{bucket}/input/{job_id}/"


def make_output_prefix(job_id: str) -> str:
    bucket = _s3_bucket()
    if not bucket:
        return ""
    return f"s3://{bucket}/runs/{job_id}/"


def make_review_prefix(job_id: str) -> str:
    bucket = _s3_bucket()
    if not bucket:
        return ""
    return f"s3://{bucket}/review-decisions/{job_id}/"


def make_export_prefix(job_id: str) -> str:
    bucket = _s3_bucket()
    if not bucket:
        return ""
    return f"s3://{bucket}/exports/{job_id}/"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Return (bucket, key) from an s3://bucket/key URI."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {uri}")
    without_scheme = uri[5:]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


# ---------------------------------------------------------------------------
# Upload helpers
# ---------------------------------------------------------------------------

def upload_file(local_path: str | Path, s3_uri: str) -> None:
    """Upload a single file to an S3 URI."""
    local_path = Path(local_path)
    if not _aws_mode():
        _local_copy_file(local_path, s3_uri)
        return

    bucket, key = parse_s3_uri(s3_uri)
    import boto3
    s3 = boto3.client("s3", region_name=_aws_region())
    s3.upload_file(str(local_path), bucket, key)


def upload_dir(local_dir: str | Path, s3_prefix: str) -> list[str]:
    """Upload all files under local_dir to s3_prefix. Returns list of uploaded S3 URIs."""
    local_dir = Path(local_dir)
    if not s3_prefix.endswith("/"):
        s3_prefix += "/"
    uploaded: list[str] = []
    for file_path in sorted(local_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(local_dir)
        dest_uri = s3_prefix + rel.as_posix()
        upload_file(file_path, dest_uri)
        uploaded.append(dest_uri)
    return uploaded


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_file(s3_uri: str, local_path: str | Path) -> None:
    """Download a single S3 object to local_path."""
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if not _aws_mode():
        _local_copy_file_from(s3_uri, local_path)
        return

    bucket, key = parse_s3_uri(s3_uri)
    import boto3
    s3 = boto3.client("s3", region_name=_aws_region())
    s3.download_file(bucket, key, str(local_path))


def download_prefix(s3_prefix: str, local_dir: str | Path) -> list[Path]:
    """Download all objects under s3_prefix into local_dir. Returns list of local paths."""
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    if not s3_prefix.endswith("/"):
        s3_prefix += "/"

    if not _aws_mode():
        return _local_copy_prefix(s3_prefix, local_dir)

    bucket, prefix_key = parse_s3_uri(s3_prefix)
    import boto3
    s3 = boto3.client("s3", region_name=_aws_region())
    paginator = s3.get_paginator("list_objects_v2")
    downloaded: list[Path] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix_key):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            rel = key[len(prefix_key):]
            if not rel:
                continue
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(dest))
            downloaded.append(dest)
    return downloaded


def list_prefix(s3_prefix: str) -> list[str]:
    """List all S3 URIs under a prefix."""
    if not s3_prefix.endswith("/"):
        s3_prefix += "/"
    if not _aws_mode():
        return []

    bucket, prefix_key = parse_s3_uri(s3_prefix)
    import boto3
    s3 = boto3.client("s3", region_name=_aws_region())
    paginator = s3.get_paginator("list_objects_v2")
    uris: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix_key):
        for obj in page.get("Contents") or []:
            uris.append(f"s3://{bucket}/{obj['Key']}")
    return uris


# ---------------------------------------------------------------------------
# Local fallback (plain file copy when S3 is not configured)
# ---------------------------------------------------------------------------

def _local_copy_file(src: Path, dest_uri: str) -> None:
    dest_path = _local_path_for(dest_uri)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dest_path))


def _local_copy_file_from(src_uri: str, dest: Path) -> None:
    src_path = _local_path_for(src_uri)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src_path), str(dest))


def _local_copy_prefix(s3_prefix: str, local_dir: Path) -> list[Path]:
    src_dir = _local_path_for(s3_prefix)
    if not src_dir.exists():
        return []
    copied: list[Path] = []
    for src_file in sorted(src_dir.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(src_dir)
        dest = local_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_file), str(dest))
        copied.append(dest)
    return copied


def _local_path_for(uri: str) -> Path:
    """Map a pseudo s3:// URI to a local path under /tmp/dupe-local-store/."""
    if uri.startswith("s3://"):
        uri = uri[5:]
    return Path("/tmp/dupe-local-store") / uri.lstrip("/")

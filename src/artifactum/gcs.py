from __future__ import annotations

from pathlib import Path

from google.cloud import storage

_CHUNK = 8 * 1024 * 1024  # 8 MB resumable upload threshold


def _parse_gcs_url(gcs_url: str) -> tuple[str, str]:
    """Parse 'gs://bucket/path' into (bucket, blob_path)."""
    if not gcs_url.startswith("gs://"):
        raise ValueError(f"Invalid GCS URL: {gcs_url}")
    rest = gcs_url[5:]
    bucket, _, blob_path = rest.partition("/")
    return bucket, blob_path


def upload(local_path: Path, gcs_url: str) -> None:
    """Upload a local file to GCS using Application Default Credentials."""
    bucket_name, blob_path = _parse_gcs_url(gcs_url)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(str(local_path))


def download(gcs_url: str, local_path: Path) -> None:
    """Download a GCS object to a local path using Application Default Credentials."""
    bucket_name, blob_path = _parse_gcs_url(gcs_url)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(str(local_path))

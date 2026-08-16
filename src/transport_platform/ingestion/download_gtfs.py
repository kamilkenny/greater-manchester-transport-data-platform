from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from zipfile import is_zipfile

import httpx

from transport_platform.settings import get_settings

CHUNK_SIZE_BYTES = 1024 * 1024


def download_gtfs_snapshot() -> Path:
    """Download and preserve one timestamped TfGM GTFS snapshot."""

    settings = get_settings()
    downloaded_at = datetime.now(UTC)
    timestamp = downloaded_at.strftime("%Y%m%dT%H%M%SZ")

    snapshot_directory = (
        settings.raw_data_dir
        / "gtfs"
        / downloaded_at.strftime("%Y")
        / downloaded_at.strftime("%m")
        / downloaded_at.strftime("%d")
    )
    snapshot_directory.mkdir(parents=True, exist_ok=True)

    partial_path = snapshot_directory / f".tfgm_gtfs_{timestamp}.part"
    checksum = hashlib.sha256()
    response_headers: dict[str, str] = {}

    try:
        with httpx.stream(
            "GET",
            settings.tfgm_gtfs_url,
            follow_redirects=True,
            timeout=httpx.Timeout(180.0, connect=30.0),
        ) as response:
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "zip" not in content_type.lower():
                received_type = content_type or "unknown"
                raise ValueError(
                    f"Expected ZIP content, received {received_type}"
                )

            response_headers = {
                "content_type": content_type,
                "content_length": response.headers.get("content-length", ""),
                "etag": response.headers.get("etag", ""),
                "last_modified": response.headers.get("last-modified", ""),
            }

            with partial_path.open("wb") as file_handle:
                for chunk in response.iter_bytes(CHUNK_SIZE_BYTES):
                    file_handle.write(chunk)
                    checksum.update(chunk)

        if not is_zipfile(partial_path):
            raise ValueError("Downloaded file is not a valid ZIP archive")

        sha256 = checksum.hexdigest()
        snapshot_path = snapshot_directory / (
            f"tfgm_gtfs_{timestamp}_{sha256[:12]}.zip"
        )
        partial_path.replace(snapshot_path)

        metadata = {
            "source_url": settings.tfgm_gtfs_url,
            "downloaded_at_utc": downloaded_at.isoformat(),
            "file_name": snapshot_path.name,
            "file_size_bytes": snapshot_path.stat().st_size,
            "sha256": sha256,
            **response_headers,
        }

        metadata_path = snapshot_path.with_suffix(".json")
        metadata_path.write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )

    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    print(f"Snapshot saved: {snapshot_path}")
    print(f"Metadata saved: {metadata_path}")
    print(f"SHA256: {sha256}")

    return snapshot_path


if __name__ == "__main__":
    download_gtfs_snapshot()


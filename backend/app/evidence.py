"""Private storage for optional report photos.

S3Evidence: a private bucket (Block Public Access). Browsers upload with a
short-lived presigned POST whose policy fixes the key, the Content-Type and a
byte-size range. After upload the API checks the object's size and its first
bytes (JPEG/PNG/WebP signatures) and deletes anything that does not match.
Viewing uses a 2-minute presigned GET issued only to authorised users.

LocalEvidence: local mode only. Same validation, files in backend/.data/evidence,
and HMAC-signed short-lived URLs.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_BYTES = 5 * 1024 * 1024


class EvidenceError(ValueError):
    pass


def sniff(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def check_declared(content_type: str, size: int) -> None:
    if content_type not in ALLOWED_TYPES:
        raise EvidenceError("Only JPEG, PNG or WebP photos are accepted.")
    if not 0 < size <= MAX_BYTES:
        raise EvidenceError("Photos must be between 1 byte and 5 MB.")


class S3Evidence:
    kind = "s3-private"

    def __init__(self, bucket: str, client: Any | None = None):
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client("s3", config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}))
        self.client = client
        self.bucket = bucket

    def upload_target(self, key: str, content_type: str, size: int) -> dict:
        check_declared(content_type, size)
        post = self.client.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, MAX_BYTES]],
            ExpiresIn=300,
        )
        return {"method": "POST", "url": post["url"], "fields": post["fields"]}

    def verify(self, key: str, content_type: str) -> int:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise EvidenceError("Upload not found.") from exc
        size = int(head.get("ContentLength", 0))
        first = self.client.get_object(Bucket=self.bucket, Key=key, Range="bytes=0-15")["Body"].read()
        if size > MAX_BYTES or sniff(first) != content_type:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            raise EvidenceError("The uploaded file is not a valid JPEG/PNG/WebP image under 5 MB; it was deleted.")
        return size

    def view_url(self, key: str) -> str:
        return self.client.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=120)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


class LocalEvidence:
    kind = "local-files"

    def __init__(self, root: Path, signer):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.signer = signer  # callable(str) -> hex signature

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise EvidenceError("invalid key")
        return p

    def _signed(self, op: str, key: str, ttl: int) -> str:
        exp = int(time.time()) + ttl
        sig = self.signer(f"{op}|{key}|{exp}")
        return f"/api/local-evidence/{op}?key={key}&exp={exp}&sig={sig}"

    def check_sig(self, op: str, key: str, exp: int, sig: str) -> bool:
        import hmac

        return exp >= time.time() and hmac.compare_digest(sig, self.signer(f"{op}|{key}|{exp}"))

    def upload_target(self, key: str, content_type: str, size: int) -> dict:
        check_declared(content_type, size)
        return {"method": "PUT", "url": self._signed("put", key, 300), "headers": {"Content-Type": content_type}}

    def store(self, key: str, content_type: str, body: bytes) -> None:
        check_declared(content_type, len(body))
        if sniff(body[:16]) != content_type:
            raise EvidenceError("File content does not match a JPEG/PNG/WebP image.")
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)

    def verify(self, key: str, content_type: str) -> int:
        p = self._path(key)
        if not p.exists():
            raise EvidenceError("Upload not found.")
        body = p.read_bytes()
        if len(body) > MAX_BYTES or sniff(body[:16]) != content_type:
            p.unlink(missing_ok=True)
            raise EvidenceError("The uploaded file is not a valid image under 5 MB; it was deleted.")
        return len(body)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def view_url(self, key: str) -> str:
        return self._signed("get", key, 120)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

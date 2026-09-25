"""
storage.py — Cloudflare R2 (S3-compatible) storage for Kijiji Tanzania.

Environment (Render > Environment):
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET_NAME
    R2_ENDPOINT_URL      e.g. https://<accountid>.r2.cloudflarestorage.com
    R2_PUBLIC_URL        e.g. https://pub-xxxx.r2.dev  (no trailing slash)
"""
from __future__ import annotations

import os
import uuid
import mimetypes
from io import BytesIO
from typing import Optional, BinaryIO

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    Config = None
    ClientError = Exception


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


R2_ACCESS_KEY_ID = _env("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = _env("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = _env("R2_BUCKET_NAME")
R2_ENDPOINT_URL = _env("R2_ENDPOINT_URL")
R2_PUBLIC_URL = _env("R2_PUBLIC_URL").rstrip("/")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
LOCAL_UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(LOCAL_UPLOAD_FOLDER, exist_ok=True)

_client = None


def r2_configured() -> bool:
    return bool(
        boto3
        and R2_ACCESS_KEY_ID
        and R2_SECRET_ACCESS_KEY
        and R2_BUCKET_NAME
        and R2_ENDPOINT_URL
        and R2_PUBLIC_URL
    )


def get_r2_client():
    global _client
    if _client is not None:
        return _client
    if not r2_configured():
        return None
    _client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return _client


def make_unique_key(original_filename: str, prefix: str = "uploads") -> str:
    ext = ""
    if original_filename and "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()
        ext = "".join(c for c in ext if c.isalnum() or c == ".")
        if len(ext) > 12:
            ext = ext[:12]
    return f"{prefix.strip('/')}/{uuid.uuid4().hex}{ext}"


def _guess_content_type(filename: str) -> str:
    ct, _ = mimetypes.guess_type(filename or "")
    return ct or "application/octet-stream"


def upload_fileobj(fileobj: BinaryIO, key: str, content_type: Optional[str] = None) -> str:
    if content_type is None:
        content_type = _guess_content_type(key)
    client = get_r2_client()
    if client:
        fileobj.seek(0)
        client.upload_fileobj(
            fileobj,
            R2_BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        # Store KEY in DB (not full URL) so templates /static/uploads/KEY still
        # can be rewritten via media_url / serve route.
        return key
    local_name = key.replace("/", "_")
    local_path = os.path.join(LOCAL_UPLOAD_FOLDER, local_name)
    fileobj.seek(0)
    with open(local_path, "wb") as f:
        f.write(fileobj.read())
    return f"/static/uploads/{local_name}"


def upload_bytes(data: bytes, key: str, content_type: Optional[str] = None) -> str:
    return upload_fileobj(BytesIO(data), key, content_type=content_type)


def upload_werkzeug_file(file_storage, prefix: str = "uploads") -> str:
    original = getattr(file_storage, "filename", None) or "file"
    key = make_unique_key(original, prefix=prefix)
    content_type = getattr(file_storage, "content_type", None) or _guess_content_type(original)
    stream = getattr(file_storage, "stream", None) or file_storage
    return upload_fileobj(stream, key, content_type=content_type)


def upload_local_path(local_path: str, prefix: str = "uploads") -> str:
    key = make_unique_key(os.path.basename(local_path), prefix=prefix)
    content_type = _guess_content_type(local_path)
    with open(local_path, "rb") as f:
        return upload_fileobj(f, key, content_type=content_type)


def media_url(path_or_url: Optional[str]) -> str:
    if not path_or_url:
        return ""
    s = str(path_or_url).strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("/static/"):
        return s
    if r2_configured():
        return f"{R2_PUBLIC_URL}/{s.lstrip('/')}"
    name = s.replace("/", "_")
    return f"/static/uploads/{name}"


def delete_object(path_or_url: Optional[str]) -> bool:
    if not path_or_url:
        return False
    s = str(path_or_url).strip()
    if not s:
        return False
    key = s
    if R2_PUBLIC_URL and s.startswith(R2_PUBLIC_URL):
        key = s[len(R2_PUBLIC_URL):].lstrip("/")
    elif s.startswith("http://") or s.startswith("https://"):
        return False
    client = get_r2_client()
    if not client:
        local = os.path.join(LOCAL_UPLOAD_FOLDER, key.replace("/", "_"))
        try:
            if os.path.isfile(local):
                os.remove(local)
                return True
        except OSError:
            pass
        return False
    try:
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=key)
        return True
    except ClientError as e:
        print("[R2] delete error:", e)
        return False


def download_to_bytes(path_or_url: Optional[str]) -> Optional[bytes]:
    if not path_or_url:
        return None
    s = str(path_or_url).strip()
    if s.startswith("http://") or s.startswith("https://"):
        try:
            import requests
            r = requests.get(s, timeout=15)
            if r.status_code == 200:
                return r.content
        except Exception as e:
            print("[R2] download http error:", e)
        return None
    client = get_r2_client()
    if client:
        key = s.lstrip("/")
        try:
            buf = BytesIO()
            client.download_fileobj(R2_BUCKET_NAME, key, buf)
            return buf.getvalue()
        except ClientError as e:
            print("[R2] download error:", e)
            return None
    local = os.path.join(LOCAL_UPLOAD_FOLDER, s.replace("/", "_"))
    if os.path.isfile(local):
        with open(local, "rb") as f:
            return f.read()
    return None

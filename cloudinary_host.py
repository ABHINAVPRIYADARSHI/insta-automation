"""
cloudinary_host.py
==================
Uploads local rendered slides to Cloudinary and returns secure public URLs.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from config import (
    CLOUDINARY_API_KEY,
    CLOUDINARY_API_SECRET,
    CLOUDINARY_CLOUD_NAME,
    CLOUDINARY_FOLDER,
)

UPLOAD_DELAY = 0.4  # seconds between uploads


def _require_cloudinary_config() -> None:
    missing = []
    if not CLOUDINARY_CLOUD_NAME:
        missing.append("CLOUDINARY_CLOUD_NAME")
    if not CLOUDINARY_API_KEY:
        missing.append("CLOUDINARY_API_KEY")
    if not CLOUDINARY_API_SECRET:
        missing.append("CLOUDINARY_API_SECRET")
    if missing:
        raise RuntimeError(
            "Missing Cloudinary config: "
            + ", ".join(missing)
            + ". Set these in .env."
        )


def _signature(params: dict, api_secret: str, algo: str = "sha1") -> str:
    """
    Cloudinary signed upload signature (SHA1 of sorted k=v pairs + secret).
    """
    items = [
        f"{k}={v}"
        for k, v in sorted(params.items())
        if v is not None and v != ""
    ]
    to_sign = "&".join(items) + api_secret
    if algo == "sha256":
        return hashlib.sha256(to_sign.encode("utf-8")).hexdigest()
    return hashlib.sha1(to_sign.encode("utf-8")).hexdigest()


def _is_invalid_signature_response(resp: requests.Response) -> bool:
    if resp.status_code != 401:
        return False
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return "Invalid Signature" in resp.text
    msg = str(data.get("error", {}).get("message", ""))
    return "Invalid Signature" in msg


def upload_image(image_path: Path) -> str:
    """
    Upload one local image to Cloudinary and return secure_url.
    """
    _require_cloudinary_config()
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    timestamp = int(time.time())
    public_id = image_path.stem
    endpoint = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"

    sign_params = {
        "folder": CLOUDINARY_FOLDER,
        "public_id": public_id,
        "timestamp": timestamp,
    }

    def _post_with_signature(signature: str) -> requests.Response:
        with open(image_path, "rb") as f:
            return requests.post(
                endpoint,
                data={
                    "api_key": CLOUDINARY_API_KEY,
                    "timestamp": timestamp,
                    "signature": signature,
                    "folder": CLOUDINARY_FOLDER,
                    "public_id": public_id,
                },
                files={"file": f},
                timeout=45,
            )

    # Try SHA-1 first (default), then SHA-256 fallback for hardened accounts.
    signature = _signature(sign_params, CLOUDINARY_API_SECRET, algo="sha1")
    resp = _post_with_signature(signature)
    if _is_invalid_signature_response(resp):
        signature = _signature(sign_params, CLOUDINARY_API_SECRET, algo="sha256")
        resp = _post_with_signature(signature)

    if resp.status_code != 200:
        raise RuntimeError(f"Cloudinary HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    secure_url = data.get("secure_url", "")
    if not secure_url.startswith("https://"):
        raise RuntimeError(f"Cloudinary upload failed or missing secure_url: {data}")
    return secure_url


def upload_slides(slide_paths: list[Path]) -> list[str]:
    """
    Upload all slides in order and return ordered secure URLs.
    """
    urls: list[str] = []
    for i, path in enumerate(slide_paths, 1):
        url = upload_image(path)
        print(f"Uploaded slide {i}/{len(slide_paths)}: {url}")
        urls.append(url)
        if i < len(slide_paths):
            time.sleep(UPLOAD_DELAY)
    return urls

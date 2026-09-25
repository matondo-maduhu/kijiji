"""
moderation.py — NSFW check (optional external APIs).

PRIORITY:
  1) SIGHTENGINE_API_USER + SIGHTENGINE_API_SECRET  → Sightengine
  2) OPENAI_API_KEY                                 → OpenAI omni-moderation
  3) Hakuna key                                     → APPROVE (app inaendelea)

Env ya ziada:
  MODERATION_FAIL_MODE = approved | manual_review
      (default: approved) — kinachotokea kama API haipo / imeshindwa
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

import requests

REVIEW_THRESHOLD = 0.45
REJECT_THRESHOLD = 0.75
TIMEOUT_SECONDS = 25


def _fail_mode() -> str:
    m = (os.environ.get("MODERATION_FAIL_MODE") or "approved").strip().lower()
    if m in ("approved", "manual_review", "rejected"):
        return m
    return "approved"


def _fail_result(reason: str) -> Dict[str, Any]:
    decision = _fail_mode()
    print(f"[moderation] skip/fail ({reason}) → {decision}")
    return {"decision": decision, "score": 0.0, "labels": [reason]}


def _public_url(file_path: str) -> str:
    if not file_path:
        return ""
    s = str(file_path).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    try:
        from storage import media_url
        return media_url(s) or ""
    except Exception:
        return ""


# -------------------- Sightengine --------------------

def _sightengine_enabled() -> bool:
    return bool(
        (os.environ.get("SIGHTENGINE_API_USER") or "").strip()
        and (os.environ.get("SIGHTENGINE_API_SECRET") or "").strip()
    )


def _check_sightengine(url: str) -> Dict[str, Any]:
    user = os.environ.get("SIGHTENGINE_API_USER", "").strip()
    secret = os.environ.get("SIGHTENGINE_API_SECRET", "").strip()
    try:
        r = requests.get(
            "https://api.sightengine.com/1.0/check.json",
            params={
                "url": url,
                "models": "nudity-2.0",
                "api_user": user,
                "api_secret": secret,
            },
            timeout=TIMEOUT_SECONDS,
        )
        data = r.json() if r.content else {}
    except Exception as e:
        return _fail_result(f"sightengine_error:{e}")

    if r.status_code != 200 or data.get("status") == "failure":
        return _fail_result(f"sightengine_http:{r.status_code}")

    nudity = data.get("nudity") or {}
    score = 0.0
    labels: List[str] = []
    for name in (
        "sexual_activity",
        "sexual_display",
        "erotica",
        "very_suggestive",
        "raw",
        "partial",
        "suggestive",
    ):
        val = nudity.get(name)
        if val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v >= 0.15:
            labels.append(f"{name}:{v:.2f}")
        weight = 1.0 if name in ("sexual_activity", "sexual_display", "erotica", "raw") else 0.7
        score = max(score, v * weight)

    if score >= REJECT_THRESHOLD:
        decision = "rejected"
    elif score >= REVIEW_THRESHOLD:
        decision = "manual_review"
    else:
        decision = "approved"
    return {"decision": decision, "score": round(score, 4), "labels": labels}


# -------------------- OpenAI --------------------

def _openai_enabled() -> bool:
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


def _check_openai(url: str) -> Dict[str, Any]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    try:
        r = requests.post(
            "https://api.openai.com/v1/moderations",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "omni-moderation-latest",
                "input": [
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            },
            timeout=TIMEOUT_SECONDS,
        )
        data = r.json() if r.content else {}
    except Exception as e:
        return _fail_result(f"openai_error:{e}")

    if r.status_code != 200:
        return _fail_result(f"openai_http:{r.status_code}")

    results = (data.get("results") or [{}])[0]
    categories = results.get("categories") or {}
    scores = results.get("category_scores") or {}
    flagged = bool(results.get("flagged"))

    sexual = float(scores.get("sexual") or 0)
    labels = [k for k, v in categories.items() if v]
    score = sexual
    if flagged and score < REVIEW_THRESHOLD:
        score = max(score, REVIEW_THRESHOLD)

    if score >= REJECT_THRESHOLD or (flagged and sexual >= 0.5):
        decision = "rejected"
    elif score >= REVIEW_THRESHOLD or flagged:
        decision = "manual_review"
    else:
        decision = "approved"
    return {"decision": decision, "score": round(score, 4), "labels": labels}


# -------------------- public API --------------------

def moderate_media(file_path: str, media_type: str) -> Dict[str, Any]:
    """
    Called from posts.py after upload.
    Without any API keys → approved (app keeps working).
    """
    if not file_path or media_type not in ("image", "video"):
        return {"decision": "approved", "score": 0.0, "labels": []}

    url = _public_url(file_path)
    if not url.startswith("http"):
        return _fail_result("no_public_url")

    if _sightengine_enabled():
        return _check_sightengine(url)

    if _openai_enabled():
        return _check_openai(url)

    # Hakuna API — usizime app
    return _fail_result("no_api_configured")


def analyze_image(image_path: str) -> Tuple[float, List[str]]:
    r = moderate_media(image_path, "image")
    return float(r.get("score") or 0), list(r.get("labels") or [])


def analyze_video(video_path: str, num_frames: int = 6) -> Tuple[float, List[str]]:
    r = moderate_media(video_path, "video")
    return float(r.get("score") or 0), list(r.get("labels") or [])

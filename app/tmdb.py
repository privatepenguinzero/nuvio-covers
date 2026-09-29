"""Minimal TMDB discover client with relative date tokens."""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/w342"


def resolve_dates(params: dict, today: dt.date | None = None) -> dict:
    """Replace values like "-30d", "-1y" or "today" with ISO dates."""
    today = today or dt.date.today()
    out = {}
    for key, value in params.items():
        if isinstance(value, str) and value == "today":
            value = today.isoformat()
        elif isinstance(value, str) and value.startswith("-") and value[-1] in "dy" and value[1:-1].isdigit():
            n = int(value[1:-1])
            days = n if value[-1] == "d" else n * 365
            value = (today - dt.timedelta(days=days)).isoformat()
        out[key] = value
    return out


def discover(api_key: str, media: str, params: dict, language: str = "en-US") -> list[dict]:
    query = {"api_key": api_key, "language": language, **resolve_dates(params)}
    url = f"{API}/discover/{media}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": "nuvio-covers/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("results", [])


def poster_urls(results: list[dict], limit: int) -> list[str]:
    return [IMG + r["poster_path"] for r in results if r.get("poster_path")][:limit]

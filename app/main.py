"""nuvio-covers: regenerate cover images on a weekly schedule and serve them over HTTP."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

from render import (
    fetch_posters,
    fetch_rgba,
    prepare_logo,
    render_cover,
    render_hero,
    render_text_logo,
    render_wordmark,
)
from tmdb import discover, logo_url, poster_urls

log = logging.getLogger("nuvio-covers")

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/data/covers"))
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
PORT = int(os.environ.get("PORT", "8080"))
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Rome"))
# Weekly schedule: weekday 0=Monday ... 6=Sunday, local hour.
SCHEDULE_WEEKDAY = int(os.environ.get("SCHEDULE_WEEKDAY", "0"))
SCHEDULE_HOUR = int(os.environ.get("SCHEDULE_HOUR", "5"))
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN", "")

state = {"last_run": None, "last_error": None, "covers": []}
lock = threading.Lock()


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _save(img, target: Path, **opts) -> str:
    """Write next to the target and swap, so clients never see a half-written file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.stem + ".tmp" + target.suffix)
    img.save(tmp, **opts)
    tmp.replace(target)
    return str(target.relative_to(OUTPUT_DIR))


def _jpg(img, target: Path) -> str:
    return _save(img, target, quality=88, optimize=True, progressive=True)


def _png(img, target: Path) -> str:
    return _save(img, target, optimize=True)


def _cover(cfg: dict, cover: dict, seed: int) -> list[str]:
    results = discover(TMDB_API_KEY, cover["media"], cover["params"], cfg.get("language", "en-US"))
    posters = fetch_posters(poster_urls(results, cover.get("posters", 12)))
    if len(posters) < 4:
        raise RuntimeError(f"{cover['name']}: only {len(posters)} posters, keeping the previous images")
    folder = OUTPUT_DIR / cover.get("folder", "")
    text = dict(title=cover["title"], caption=cover["caption"], pill=cover.get("pill", "NEW"), color=cover["color"])
    written = [_jpg(render_cover(posters, shuffle_seed=seed, **text), folder / f"{cover['name']}.jpg")]
    if cover.get("hero", True):
        written.append(_jpg(render_hero(posters, shuffle_seed=seed), folder / f"{cover['name']}-hero.jpg"))
        written.append(_png(render_text_logo(**text), folder / f"{cover['name']}-logo.png"))
    return written


def _provider_posters(cfg: dict, region: dict) -> list:
    """Popular recent movies and shows on one service in one region, interleaved."""
    common = {
        "watch_region": region["region"],
        "with_watch_providers": region["providers"],
        "with_watch_monetization_types": "flatrate|free|ads",
        "sort_by": "popularity.desc",
    }
    movies = discover(TMDB_API_KEY, "movie", {**common, "primary_release_date.gte": "-3y", "vote_count.gte": 20}, cfg.get("language", "en-US"))
    # no talk shows, news, reality or kids shows: they make a dull wall
    shows = discover(TMDB_API_KEY, "tv", {**common, "air_date.gte": "-180d", "vote_count.gte": 20, "without_genres": "10767|10763|10764|10762"}, cfg.get("language", "en-US"))
    urls = []
    for pair in zip(poster_urls(shows, 10), poster_urls(movies, 10)):
        urls.extend(pair)
    return fetch_posters(urls)


def _provider(cfg: dict, prov: dict, seed: int) -> list[str]:
    written = []
    logo = prov.get("logo", {})
    url = logo_url(TMDB_API_KEY, network=logo.get("network"), company=logo.get("company"))
    img = prepare_logo(fetch_rgba(url)) if url else prepare_logo(render_wordmark(logo.get("text", prov["name"]), color=logo.get("color", "#FFFFFF")))
    written.append(_png(img, OUTPUT_DIR / "brand" / f"{prov['slug']}.png"))
    for key, region in prov.get("regions", {}).items():
        posters = _provider_posters(cfg, region)
        if len(posters) < 6:
            log.warning("%s/%s: only %d posters, keeping the previous hero", key, prov["slug"], len(posters))
            continue
        written.append(_jpg(render_hero(posters, shuffle_seed=seed), OUTPUT_DIR / "piattaforme" / key / f"{prov['slug']}-hero.jpg"))
    return written


def generate_all() -> None:
    if not lock.acquire(blocking=False):
        log.info("generation already running, skipped")
        return
    try:
        cfg = load_config()
        week = dt.date.today().isocalendar()
        seed = week[0] * 100 + week[1]  # new shuffle every week, stable within it
        jobs = [(c["name"], _cover, c) for c in cfg.get("covers", [])]
        jobs += [(p["slug"], _provider, p) for p in cfg.get("providers", [])]
        written, errors = [], []
        for name, job, item in jobs:
            try:  # one failing item keeps its previous images and does not stop the others
                files = job(cfg, item, seed)
                written.extend(files)
                log.info("%s: wrote %s", name, ", ".join(files))
            except Exception as exc:
                log.exception("%s failed", name)
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
        state.update(
            last_run=dt.datetime.now(TZ).isoformat(timespec="seconds"),
            last_error="; ".join(errors) or None,
            covers=written,
        )
    finally:
        lock.release()


def next_run(now: dt.datetime) -> dt.datetime:
    days = (SCHEDULE_WEEKDAY - now.weekday()) % 7
    candidate = (now + dt.timedelta(days=days)).replace(hour=SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += dt.timedelta(days=7)
    return candidate


def scheduler() -> None:
    covers_exist = OUTPUT_DIR.exists() and any(OUTPUT_DIR.rglob("*.jpg"))
    if not covers_exist or os.environ.get("GENERATE_ON_START", "true").lower() == "true":
        generate_all()
    while True:
        when = next_run(dt.datetime.now(TZ))
        state["next_run"] = when.isoformat(timespec="seconds")
        log.info("next generation at %s", when)
        while dt.datetime.now(TZ) < when:
            time.sleep(min(300, max(1, (when - dt.datetime.now(TZ)).total_seconds())))
        generate_all()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT_DIR), **kwargs)

    def do_GET(self):
        if self.path in ("/healthz", "/status"):
            return self._json(200 if not state["last_error"] else 500, state)
        if self.path.startswith("/refresh"):
            return self._refresh()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/refresh"):
            return self._refresh()
        self.send_error(404)

    def _refresh(self):
        token = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not REFRESH_TOKEN or token != REFRESH_TOKEN:
            return self._json(401, {"error": "unauthorized"})
        threading.Thread(target=generate_all, daemon=True).start()
        return self._json(202, {"status": "started"})

    def end_headers(self):
        if self.path.endswith((".jpg", ".png")):
            self.send_header("Cache-Control", "public, max-age=21600")
        super().end_headers()

    def list_directory(self, path):  # no directory listing
        self.send_error(404)
        return None

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        log.debug("%s " + fmt, self.address_string(), *args)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    if not TMDB_API_KEY:
        raise SystemExit("TMDB_API_KEY is required")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=scheduler, daemon=True).start()
    log.info("serving %s on :%d", OUTPUT_DIR, PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

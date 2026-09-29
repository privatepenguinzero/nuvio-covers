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

from render import fetch_posters, render_cover
from tmdb import discover, poster_urls

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


def generate_all() -> None:
    if not lock.acquire(blocking=False):
        log.info("generation already running, skipped")
        return
    try:
        cfg = load_config()
        week = dt.date.today().isocalendar()
        seed = week[0] * 100 + week[1]  # new shuffle every week, stable within it
        written = []
        for cover in cfg["covers"]:
            results = discover(TMDB_API_KEY, cover["media"], cover["params"], cfg.get("language", "en-US"))
            posters = fetch_posters(poster_urls(results, cover.get("posters", 12)))
            if len(posters) < 4:
                raise RuntimeError(f"{cover['name']}: only {len(posters)} posters, keeping the previous cover")
            img = render_cover(
                posters,
                title=cover["title"],
                caption=cover["caption"],
                pill=cover.get("pill", "NEW"),
                color=cover["color"],
                shuffle_seed=seed,
            )
            target = OUTPUT_DIR / cover.get("folder", "") / f"{cover['name']}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp.jpg")
            img.save(tmp, quality=88, optimize=True, progressive=True)
            tmp.replace(target)  # atomic swap, clients never see a half-written file
            written.append(str(target.relative_to(OUTPUT_DIR)))
            log.info("wrote %s (%d posters)", target, len(posters))
        state.update(last_run=dt.datetime.now(TZ).isoformat(timespec="seconds"), last_error=None, covers=written)
    except Exception as exc:  # keep serving the old covers
        log.exception("generation failed")
        state["last_error"] = f"{type(exc).__name__}: {exc}"
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
        if self.path.endswith(".jpg"):
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

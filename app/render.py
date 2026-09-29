"""Render Netflix-style cover cards from a wall of TMDB posters."""
from __future__ import annotations

import io
import random
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

FONT_TITLE = "/app/fonts/Montserrat-Black.ttf"
FONT_PILL = "/app/fonts/Montserrat-ExtraBold.ttf"
FONT_CAPTION = "/app/fonts/Montserrat-Bold.ttf"
BG = (8, 8, 10)
USER_AGENT = "nuvio-covers/1.0"


def fetch_image(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


def fetch_posters(urls: list[str]) -> list[Image.Image]:
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(_safe_fetch, urls))
    return [img for img in results if img is not None]


def _safe_fetch(url: str) -> Image.Image | None:
    try:
        return fetch_image(url)
    except Exception:  # a single broken poster must not kill the cover
        return None


def _gradient(width: int, height: int, stops: list[tuple[float, int]], horizontal: bool = True) -> Image.Image:
    """Greyscale mask interpolated between (position 0..1, value 0..255) stops."""
    length = width if horizontal else height
    line = Image.new("L", (length, 1))
    for i in range(length):
        t = i / max(length - 1, 1)
        for (a, va), (b, vb) in zip(stops, stops[1:]):
            if a <= t <= b:
                line.putpixel((i, 0), int(va + (vb - va) * (t - a) / (b - a or 1)))
                break
    if horizontal:
        return line.resize((width, height))
    return line.rotate(90, expand=True).transpose(Image.FLIP_TOP_BOTTOM).resize((width, height))


def _poster_wall(posters: list[Image.Image], width: int, height: int, angle: float = -14) -> Image.Image:
    pw = int(190 * width / 1280)
    ph = int(pw * 1.5)
    gap = max(8, int(14 * width / 1280))
    big = Image.new("RGB", (int(width * 1.8), int(height * 1.9)), BG)
    cols = big.width // (pw + gap) + 1
    rows = big.height // (ph + gap) + 1
    tiles = [p.resize((pw, ph), Image.LANCZOS) for p in posters]
    n = len(tiles)
    for r in range(rows):
        offset = (r % 2) * (pw // 2)
        for c in range(cols):
            # stride of 5 keeps the same poster from sitting next to itself
            big.paste(tiles[(c + r * 5) % n], (c * (pw + gap) - offset, r * (ph + gap)))
    big = big.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=BG)
    x = (big.width - width) // 2
    y = (big.height - height) // 2
    return big.crop((x, y, x + width, y + height))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def render_cover(
    posters: list[Image.Image],
    *,
    title: str,
    caption: str,
    pill: str,
    color: str,
    width: int = 1280,
    height: int = 720,
    shuffle_seed: int | None = None,
) -> Image.Image:
    if not posters:
        raise ValueError("no posters to render")
    posters = list(posters)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(posters)
    accent = hex_to_rgb(color)
    s = width / 1280

    img = _poster_wall(posters, width, height)
    img = ImageEnhance.Color(img).enhance(0.85)
    dark = Image.new("RGB", (width, height), BG)
    img = Image.composite(dark, img, _gradient(width, height, [(0, 245), (0.42, 215), (0.75, 90), (1, 40)]))

    glow = Image.new("L", (width, height), 0)
    ImageDraw.Draw(glow).ellipse((-width * 0.35, height * 0.35, width * 0.55, height * 1.6), fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(width * 0.12))
    img = Image.composite(Image.new("RGB", (width, height), accent), img, glow)
    img = Image.composite(dark, img, _gradient(width, height, [(0, 0), (0.7, 0), (1, 160)], horizontal=False))

    draw = ImageDraw.Draw(img)
    x0, y0 = int(70 * s), int(200 * s)

    pill_font = ImageFont.truetype(FONT_PILL, int(34 * s))
    pill_w = draw.textlength(pill, font=pill_font)
    draw.rounded_rectangle((x0, y0, x0 + pill_w + int(44 * s), y0 + int(56 * s)), radius=int(10 * s), fill=accent)
    draw.text((x0 + int(22 * s), y0 + int(28 * s)), pill, font=pill_font, fill="white", anchor="lm")

    cap_font = ImageFont.truetype(FONT_CAPTION, int(26 * s))
    draw.text((x0 + pill_w + int(64 * s), y0 + int(28 * s)), caption, font=cap_font, fill=(230, 230, 230), anchor="lm")

    size = int(150 * s)
    title_font = ImageFont.truetype(FONT_TITLE, size)
    while draw.textlength(title, font=title_font) > width * 0.62 and size > 40:
        size -= 4
        title_font = ImageFont.truetype(FONT_TITLE, size)
    ty = y0 + int(80 * s)

    shadow = Image.new("L", (width, height), 0)
    ImageDraw.Draw(shadow).text((x0, ty), title, font=title_font, fill=200)
    shadow = shadow.filter(ImageFilter.GaussianBlur(12 * s))
    img = Image.composite(Image.new("RGB", (width, height), (0, 0, 0)), img, shadow)
    draw = ImageDraw.Draw(img)
    draw.text((x0 - int(4 * s), ty), title, font=title_font, fill="white")

    bbox = draw.textbbox((x0, ty), title, font=title_font)
    draw.rounded_rectangle((x0, bbox[3] + int(22 * s), x0 + int(120 * s), bbox[3] + int(30 * s)), radius=4, fill=accent)
    return img

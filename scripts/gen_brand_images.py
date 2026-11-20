"""Generate brand artwork with OpenAI gpt-image and compose README header + social preview (og:image).

Reads OPENAI_API_KEY from .env (never printed). Text is overlaid locally with Pillow so it is crisp
and typo-free; the model only paints the background artwork.

    python scripts/gen_brand_images.py            # generate art + compose
    python scripts/gen_brand_images.py --compose  # re-compose from cached art only
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets"
RAW = OUT / "art-wide.png"
sys.path.insert(0, str(ROOT))

PROMPT = (
    "Premium dark tech hero artwork for a network security and monitoring app. Deep navy-black background (#070B14). "
    "On the right two thirds: an elegant 3D constellation of glowing network nodes connected by thin luminous lines, "
    "a central router node emitting concentric radar arcs, soft volumetric glow, subtle grid floor with perspective, "
    "small floating glass device icons (phone, laptop, camera, TV) as abstract rounded glyphs. Color palette: indigo "
    "#6366F1, electric blue #4F8DF7 and cyan #06B6D4 with tiny accents of violet. Left third mostly empty, dark and "
    "calm for text overlay. Cinematic lighting, depth of field, ultra clean, Apple/Linear-style product marketing "
    "aesthetic, high detail, no text, no letters, no logos, no watermark."
)


def api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("OPENAI_API_KEY not found")
    return key


def generate() -> None:
    headers = {"Authorization": f"Bearer {api_key()}"}
    last_err = None
    attempts = [(m, q) for m in ("gpt-image-2", "gpt-image-1") for q in ("high", "high", "medium")]
    for model, quality in attempts:
        body = {"model": model, "prompt": PROMPT, "size": "1536x1024", "quality": quality, "n": 1}
        try:
            r = httpx.post("https://api.openai.com/v1/images/generations", json=body, headers=headers,
                           timeout=httpx.Timeout(600, connect=20))
        except httpx.HTTPError as exc:
            last_err = f"{model}/{quality}: {type(exc).__name__}"
            print(last_err, "- retrying")
            continue
        if r.status_code == 200:
            data = r.json()["data"][0]
            img = base64.b64decode(data["b64_json"]) if data.get("b64_json") else httpx.get(data["url"], timeout=60).content
            OUT.mkdir(parents=True, exist_ok=True)
            RAW.write_bytes(img)
            print(f"art generated with {model}")
            return
        last_err = f"{model}: HTTP {r.status_code} {r.text[:300]}"
        print(last_err)
    sys.exit(f"image generation failed ({last_err})")


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    cands = (["segoeuib.ttf", "seguisb.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    for name in cands:
        for base in (Path("C:/Windows/Fonts"), Path("/System/Library/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            p = base / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def cover(img: Image.Image, w: int, h: int, focus_x: float = 0.6) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    im = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    x = int((im.width - w) * focus_x)
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def compose(w: int, h: int, out: Path, title_size: int, sub_size: int, chips: bool) -> None:
    from scripts.make_icons import render as render_icon

    base = cover(Image.open(RAW).convert("RGB"), w, h).convert("RGBA")
    # left-to-right darkening for legibility
    grad = Image.new("L", (w, 1))
    for x in range(w):
        grad.putpixel((x, 0), int(235 * max(0.0, 1 - x / (w * 0.62)) ** 1.3))
    shade = Image.new("RGBA", (w, h), (7, 11, 20, 255))
    shade.putalpha(grad.resize((w, h)))
    base = Image.alpha_composite(base, shade)

    d = ImageDraw.Draw(base)
    pad = int(h * 0.13)
    icon_size = int(title_size * 1.35)
    icon = render_icon(512).resize((icon_size, icon_size), Image.LANCZOS)
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([pad - 20, pad - 20, pad + icon_size + 20, pad + icon_size + 20], fill=(79, 141, 247, 120))
    base = Image.alpha_composite(base, glow.filter(ImageFilter.GaussianBlur(28)))
    base.alpha_composite(icon, (pad, pad))
    d = ImageDraw.Draw(base)

    ty = pad + icon_size + int(title_size * 0.45)
    d.text((pad, ty), "NET Sniffer", font=font(True, title_size), fill=(240, 244, 252))
    sy = ty + int(title_size * 1.22)
    d.text((pad, sy), "See every device. Secure your network.", font=font(False, sub_size), fill=(165, 175, 197))
    if chips:
        cy = sy + int(sub_size * 2.1)
        cx = pad
        f = font(True, int(sub_size * 0.62))
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        labels = []
        for label in ("Device discovery", "Security audit", "Speed test", "Alerts", "Parental controls"):
            tw = d.textlength(label, font=f)
            box = [cx, cy, cx + tw + 28, cy + int(sub_size * 1.25)]
            if box[2] > w * 0.62:
                break
            ld.rounded_rectangle(box, radius=999, fill=(255, 255, 255, 24), outline=(255, 255, 255, 52), width=1)
            labels.append((cx + 14, cy + int(sub_size * 0.2), label))
            cx = box[2] + 10
        base = Image.alpha_composite(base, layer)
        d = ImageDraw.Draw(base)
        for x, y, label in labels:
            d.text((x, y), label, font=f, fill=(225, 231, 245))
    out.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out, optimize=True, quality=92)
    print("wrote", out.relative_to(ROOT), f"{w}x{h}")


def main() -> None:
    if "--compose" not in sys.argv or not RAW.exists():
        generate()
    compose(1280, 640, OUT / "og-image.png", 64, 28, True)          # GitHub social preview / og:image
    compose(1600, 520, OUT / "readme-header.png", 66, 28, True)     # README banner
    # copy og image into the web UI for link previews when served remotely
    Image.open(OUT / "og-image.png").save(ROOT / "netsniffer" / "web" / "og-image.png", optimize=True)


if __name__ == "__main__":
    main()

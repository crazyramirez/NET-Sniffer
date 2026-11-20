"""Render the app icon (same design as web/icon.svg) to PNG/ICO with Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parent.parent / "netsniffer" / "web"


def render(size: int = 1024) -> Image.Image:
    s = 4  # supersampling
    n = size * s
    grad = Image.new("RGBA", (n, n))
    px = grad.load()
    stops = [(0.0, (99, 102, 241)), (0.5, (79, 141, 247)), (1.0, (6, 182, 212))]
    for y in range(0, n, s):
        for x in range(0, n, s):
            t = (x + y) / (2 * n)
            for (a, ca), (b, cb) in zip(stops, stops[1:]):
                if a <= t <= b:
                    k = (t - a) / (b - a)
                    c = tuple(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3))
                    break
            for dy in range(s):
                for dx in range(s):
                    px[x + dx, y + dy] = (*c, 255)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.2266), fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    c = n / 2
    w = int(n * 34 / 512)
    for r, alpha in ((n * 126 / 512, 242), (n * 212 / 512, 180)):
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        box = [c - r, c - r, c + r, c + r]
        d.arc(box, -45, 45, fill=(255, 255, 255, 255), width=w)
        d.arc(box, 135, 225, fill=(255, 255, 255, 255), width=w)
        layer.putalpha(layer.getchannel("A").point(lambda v, a=alpha: v * a // 255))
        img = Image.alpha_composite(img, layer)
    d = ImageDraw.Draw(img)
    dot = n * 46 / 512
    d.ellipse([c - dot, c - dot, c + dot, c + dot], fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    big = render(1024)
    big.save(WEB / "icon.png")
    big.resize((512, 512), Image.LANCZOS).save(WEB / "icon-512.png")
    big.resize((192, 192), Image.LANCZOS).save(WEB / "icon-192.png")
    big.save(WEB / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icons written to", WEB)


if __name__ == "__main__":
    main()

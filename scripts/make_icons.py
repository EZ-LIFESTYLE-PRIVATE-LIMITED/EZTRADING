"""Generate the PWA / favicon PNGs (static/icons/) and Android TWA icons (android/.../res/) from an "EZ" mark.

Dev-only (needs Pillow): python scripts/make_icons.py
The PNGs are committed, so the app itself never needs Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ACCENT = (37, 99, 235)  # --accent
WHITE = (255, 255, 255)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"
RES = ROOT / "android" / "app" / "src" / "main" / "res"
SUPERSAMPLE = 4


def _font(px: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


def render(size: int, *, maskable: bool = False, glyph_only: bool = False, glyph_scale: float = 0.34) -> Image.Image:
    """maskable=True: full-bleed square with the mark inside the 80% safe zone.
    glyph_only=True: white "EZ" on transparent (adaptive-icon foreground, notification icon)."""
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if glyph_only:
        text_px = int(s * glyph_scale)
    elif maskable:
        draw.rectangle((0, 0, s, s), fill=ACCENT)
        text_px = int(s * 0.34)
    else:
        draw.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=ACCENT)
        text_px = int(s * 0.46)
    font = _font(text_px)
    box = draw.textbbox((0, 0), "EZ", font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((s - w) / 2 - box[0], (s - h) / 2 - box[1]), "EZ", font=font, fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    targets = {
        "icon-192.png": (192, False),
        "icon-512.png": (512, False),
        "maskable-512.png": (512, True),
        "apple-touch-icon.png": (180, True),  # iOS applies its own rounding
        "favicon-32.png": (32, False),
    }
    for name, (size, maskable) in targets.items():
        render(size, maskable=maskable).save(OUT / name, optimize=True)
        print("wrote", OUT / name)

    # Android: legacy launcher icons, adaptive foreground, splash and notification icon.
    for density, size in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        _save(render(size, maskable=False), RES / f"mipmap-{density}" / "ic_launcher.png")
    _save(render(432, glyph_only=True, glyph_scale=0.24), RES / "drawable-nodpi" / "ic_launcher_foreground.png")
    _save(render(384, maskable=False), RES / "drawable-nodpi" / "splash.png")
    _save(render(96, glyph_only=True, glyph_scale=0.5), RES / "drawable-nodpi" / "ic_notification_icon.png")


def _save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print("wrote", path)


if __name__ == "__main__":
    main()

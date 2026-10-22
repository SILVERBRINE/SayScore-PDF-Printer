"""Builds the SayScore PDF icon: the SayScore brand mark with a "PDF" badge.

    python tools/icon/make_icon.py

Reads tools/icon/sayscore-brand.png and writes easy_output/assets/sayscore.ico
(+ a 256px PNG). Needs Pillow and a bold Windows font (Arial Bold / Segoe UI
Bold). The generated files are committed, so builds do not run this.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1] / "easy_output" / "assets"
SIZE = 1024  # draw large and downsample for smooth edges
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# SayScore brand colours (theme #6d4aff, gradient purple).
PURPLE_TOP, PURPLE_BOTTOM = (154, 92, 247), (61, 43, 212)


def font(size):
    for name in ("arialbd.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    raise SystemExit("Arial Bold or Segoe UI Bold is required")


def brand_tile():
    # The brand PNG has no alpha and black outside its rounded tile; cut it out.
    brand = Image.open(HERE / "sayscore-brand.png").convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    mask = Image.new("L", (SIZE, SIZE), 0)
    inset = round(SIZE * 0.012)
    ImageDraw.Draw(mask).rounded_rectangle((inset, inset, SIZE - inset, SIZE - inset),
                                           radius=round(SIZE * 0.17), fill=255)
    tile = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tile.paste(brand, (0, 0), mask)
    return tile


def badge(tile, with_text):
    box = (round(SIZE * 0.45), round(SIZE * 0.61), round(SIZE * 0.94), round(SIZE * 0.92))
    width, height = box[2] - box[0], box[3] - box[1]
    radius = round(height * 0.3)
    border = round(SIZE * 0.028)

    gradient = Image.new("RGBA", (1, height))
    for y in range(height):
        t = y / (height - 1)
        gradient.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(PURPLE_TOP, PURPLE_BOTTOM)) + (255,))
    fill_mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(fill_mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)

    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((box[0] - border, box[1] - border, box[2] + border, box[3] + border),
                        radius=radius + border, fill=(255, 255, 255, 255))
    tile.paste(gradient.resize((width, height)), box[:2], fill_mask)
    if with_text:
        d.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), "PDF",
               font=font(round(height * 0.62)), fill=(255, 255, 255, 255), anchor="mm")
    return tile


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    full = badge(brand_tile(), with_text=True).resize((256, 256), Image.LANCZOS)
    plain = badge(brand_tile(), with_text=False).resize((256, 256), Image.LANCZOS)
    # Below 32px the letters would blur into noise; keep the badge shape only.
    frames = [(full if n >= 32 else plain).resize((n, n), Image.LANCZOS) for n in SIZES]
    full.save(OUT / "sayscore.png")
    frames[-1].save(OUT / "sayscore.ico", sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    print(OUT / "sayscore.ico")


if __name__ == "__main__":
    main()

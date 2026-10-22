"""Draws the SayScore PDF icon and writes easy_output/assets/sayscore.ico (+ a 256px PNG).

    python tools/icon/make_icon.py

Needs Pillow and a bold Windows font (Arial Bold / Segoe UI Bold). The generated
files are committed, so builds do not run this.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "easy_output" / "assets"
SCALE = 4  # draw at 1024px and downsample for smooth edges
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

TEAL_TOP, TEAL_BOTTOM = (34, 179, 154), (19, 128, 110)
BODY = (31, 45, 58)
PAPER = (255, 255, 255)
LINE = (196, 206, 214)
RED = (229, 72, 77)


def s(*values):
    return [v * SCALE for v in values]


def font(size):
    for name in ("arialbd.ttf", "segoeuib.ttf"):
        try:
            return ImageFont.truetype(name, size * SCALE)
        except OSError:
            pass
    raise SystemExit("Arial Bold or Segoe UI Bold is required")


def draw(detail=True):
    size = 256 * SCALE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    gradient = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        gradient.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(TEAL_TOP, TEAL_BOTTOM)) + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(s(8, 8, 248, 248), radius=56 * SCALE, fill=255)
    image.paste(gradient.resize((size, size)), (0, 0), mask)

    d = ImageDraw.Draw(image)
    # Sheet going into the printer, with a folded corner.
    d.polygon(s(70, 30, 160, 30, 186, 56, 186, 130, 70, 130), fill=PAPER)
    d.polygon(s(160, 30, 160, 56, 186, 56), fill=LINE)
    if detail:
        for y in (64, 82, 100):
            d.rounded_rectangle(s(88, y, 168 if y != 100 else 140, y + 8), radius=4 * SCALE, fill=LINE)
    # Printer body.
    d.rounded_rectangle(s(30, 112, 226, 196), radius=26 * SCALE, fill=BODY)
    d.ellipse(s(190, 130, 204, 144), fill=TEAL_TOP)
    # Printed PDF coming out.
    d.rectangle(s(62, 168, 194, 236), fill=PAPER)
    d.rectangle(s(62, 168, 194, 176), fill=LINE)
    d.rounded_rectangle(s(76, 184, 180, 228), radius=8 * SCALE, fill=RED)
    if detail:
        d.text((128 * SCALE, 207 * SCALE), "PDF", font=font(34), fill=PAPER, anchor="mm")
    return image


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    full = draw(detail=True).resize((256, 256), Image.LANCZOS)
    small = draw(detail=False).resize((256, 256), Image.LANCZOS)
    frames = [(full if n >= 40 else small).resize((n, n), Image.LANCZOS) for n in SIZES]
    full.save(OUT / "sayscore.png")
    frames[-1].save(OUT / "sayscore.ico", sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    print(OUT / "sayscore.ico")


if __name__ == "__main__":
    main()

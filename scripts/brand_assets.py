"""Generate the Human in the Hyperloop mark (recreated from the lockup PDF) as SVG and PNGs.

    uv run --no-sync python scripts/brand_assets.py

Writes assets/brand/: hyperloop-mark.svg, hyperloop-logo.png, hyperloop-mark-small.png, favicon.png.
If the official PNGs are dropped into assets/brand/ under the same names, the app uses them instead.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BLUE, GREEN, NAVY = (89, 154, 245, 255), (63, 207, 142, 255), (10, 37, 69, 255)
OUT = Path(__file__).resolve().parents[1] / "assets" / "brand"

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 110" role="img" aria-label="Human in the Hyperloop mark">
  <defs>
    <clipPath id="blue"><polygon points="62,0 200,0 200,110 138,110 138,55 62,55"/></clipPath>
    <clipPath id="green"><polygon points="0,0 62,0 62,55 138,55 138,110 0,110"/></clipPath>
  </defs>
  <rect x="17" y="17" width="166" height="76" rx="38" fill="none" stroke="#3FCF8E" stroke-width="22" clip-path="url(#green)"/>
  <rect x="17" y="17" width="166" height="76" rx="38" fill="none" stroke="#599AF5" stroke-width="22" clip-path="url(#blue)"/>
  <circle cx="100" cy="55" r="15" fill="currentColor"/>
</svg>
"""


def draw_mark(width: int, height: int, scale: int = 4) -> Image.Image:
    """The loop mark on a transparent canvas: blue top + right arc, green bottom + left arc, navy dot."""
    w, h = width * scale, height * scale
    pad = round(min(w, h) * 0.06)
    stroke = round(h * 0.2)
    outer = [pad, pad + (h - 2 * pad) * 0.04, w - pad, h - pad - (h - 2 * pad) * 0.04]
    radius = (outer[3] - outer[1]) / 2
    ring = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(ring)
    d.rounded_rectangle(outer, radius=radius, fill=255)
    inner = [outer[0] + stroke, outer[1] + stroke, outer[2] - stroke, outer[3] - stroke]
    d.rounded_rectangle(inner, radius=max(1, radius - stroke), fill=0)

    split = Image.new("L", (w, h), 0)  # blue region: top-right
    ImageDraw.Draw(split).polygon([(w * 0.31, 0), (w, 0), (w, h), (w * 0.69, h), (w * 0.69, h / 2), (w * 0.31, h / 2)],
                                  fill=255)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    green = Image.new("RGBA", (w, h), GREEN)
    blue = Image.new("RGBA", (w, h), BLUE)
    img.paste(green, (0, 0), ring)
    blue_mask = Image.composite(ring, Image.new("L", (w, h), 0), split)
    img.paste(blue, (0, 0), blue_mask)
    r = h * 0.14
    ImageDraw.Draw(img).ellipse([w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], fill=NAVY)
    return img.resize((width, height), Image.LANCZOS)


def square(img: Image.Image, size: int, background=None) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
    mark = img.copy()
    mark.thumbnail((size, size), Image.LANCZOS)
    canvas.paste(mark, ((size - mark.width) // 2, (size - mark.height) // 2), mark)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hyperloop-mark.svg").write_text(SVG, encoding="utf-8")
    draw_mark(1200, 660).save(OUT / "hyperloop-logo.png")
    square(draw_mark(256, 141), 128).save(OUT / "hyperloop-mark-small.png")
    square(draw_mark(128, 70), 64, background=(255, 255, 255, 255)).save(OUT / "favicon.png")
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()

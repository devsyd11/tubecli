"""
Generates icon.ico for TubeCLI.
YouTube-inspired: red rounded rectangle + white play triangle.
Modifications: darker crimson red, larger corner radius, small white
audio-dot in bottom-right corner to signal MP3/audio focus.
"""
from PIL import Image, ImageDraw


def create_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    red   = (185, 0, 0, 255)   # #B90000 — darker/more crimson than YouTube's #FF0000
    white = (255, 255, 255, 255)

    # Rounded rectangle — slightly more rounded corners than YouTube
    pad = max(size // 10, 1)
    r   = size // 4
    x0, y0 = pad, pad * 2
    x1, y1 = size - pad, size - pad * 2

    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=red)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=red)
    draw.ellipse([x0,        y0,        x0 + r*2, y0 + r*2], fill=red)
    draw.ellipse([x1 - r*2,  y0,        x1,       y0 + r*2], fill=red)
    draw.ellipse([x0,        y1 - r*2,  x0 + r*2, y1      ], fill=red)
    draw.ellipse([x1 - r*2,  y1 - r*2,  x1,       y1      ], fill=red)

    # White play triangle (centred, slightly left-of-centre for visual balance)
    cx = int(size * 0.48)
    cy = size // 2
    th = int(size * 0.38)
    tw = int(size * 0.32)
    draw.polygon([
        (cx - tw // 2, cy - th // 2),
        (cx - tw // 2, cy + th // 2),
        (cx + tw,      cy),
    ], fill=white)

    # Small white circle in bottom-right — signals "audio" (not just video)
    if size >= 32:
        dr = max(size // 10, 3)
        dx = x1 - dr - max(size // 14, 2)
        dy = y1 - dr - max(size // 14, 2)
        draw.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=white)

    return img


if __name__ == "__main__":
    sizes  = [16, 32, 48, 64, 128, 256]
    images = [create_icon(s) for s in sizes]
    images[0].save(
        "icon.ico",
        format="ICO",
        append_images=images[1:],
        sizes=[(s, s) for s in sizes],
    )
    print("icon.ico created successfully.")

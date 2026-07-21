from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

svg_dir = Path(__file__).parent

# Helper to load a truetype font if available, else default
def load_font(size=12):
    try:
        return ImageFont.truetype("seguisym.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            return ImageFont.load_default()

# Chip: rounded rectangle with icon and text
def make_chip(path, text, bgcolor, fgcolor, width=160, height=32):
    img = Image.new("RGBA", (width, height), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    radius = height // 2
    draw.rounded_rectangle([0,0,width,height], radius=radius, fill=bgcolor)
    # icon circle
    icon_x = 12
    icon_y = height//2
    r = 8
    draw.ellipse([icon_x-r, icon_y-r, icon_x+r, icon_y+r], fill=fgcolor)
    # text
    font = load_font(12)
    draw.text((36, (height-12)//2), text, fill=fgcolor, font=font)
    img.save(path)
    print(f"Saved {path}")

# Icon: circular icon with center text
def make_icon(path, symbol, circle_color, txt_color, size=28):
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([0,0,size-1,size-1], fill=circle_color)
    font = load_font(14)
    try:
        w,h = font.getsize(symbol)
    except Exception:
        # fallback
        w,h = draw.textbbox((0,0), symbol, font=font)[2:]
    draw.text(((size-w)/2, (size-h)/2), symbol, fill=txt_color, font=font)
    img.save(path)
    print(f"Saved {path}")

# Generate
make_chip(svg_dir / "chip_success.png", "Δ +1,234 (+2.3%)", "#eaf8ef", "#2D9B66", 160, 32)
make_chip(svg_dir / "chip_error.png", "Δ -1,234 (-2.3%)", "#fdecea", "#C94758", 160, 32)
make_icon(svg_dir / "icon_money.png", "$", "#4E8AC7", "#ffffff", 28)
make_icon(svg_dir / "icon_paid.png", "✓", "#2D9B66", "#ffffff", 28)
print("Pillow generation done")

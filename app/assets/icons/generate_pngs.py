import cairosvg
from pathlib import Path

svg_dir = Path(__file__).parent
conversions = [
    ("chip_success.svg","chip_success.png",160,32),
    ("chip_error.svg","chip_error.png",160,32),
    ("icon_money.svg","icon_money.png",28,28),
    ("icon_paid.svg","icon_paid.png",28,28),
]
for src, dst, w, h in conversions:
    srcp = svg_dir / src
    dstp = svg_dir / dst
    if srcp.exists():
        try:
            cairosvg.svg2png(url=str(srcp), write_to=str(dstp), output_width=w, output_height=h)
            print(f"Converted {src} -> {dst}")
        except Exception as e:
            print(f"Failed {src}: {e}")
    else:
        print(f"Missing {src}")
print("done")

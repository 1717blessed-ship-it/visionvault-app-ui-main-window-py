from pathlib import Path
from math import cos, pi

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "mascots"
MASCOTS = ASSETS / "doccione-mascots.png"
LOGO_SOURCE = ASSETS / "doccione-logo-original.png"
OUTPUT = ASSETS / "doccione-mascots-form-logo.gif"
OUTPUT_LIGHT = ASSETS / "doccione-mascots-form-logo-light.gif"


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * cos(pi * t)


def crop_alpha(image: Image.Image) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        raise RuntimeError("Imagen sin contenido visible")
    return image.crop(bbox)


def prepare_logo() -> Image.Image:
    original = Image.open(LOGO_SOURCE).convert("L")
    # Restore the body area hidden by the white DOCCIONE lettering.
    draw = ImageDraw.Draw(original)
    draw.rectangle((440, 425, 1160, 545), fill=0)
    alpha = original.point(lambda p: 255 if p < 205 else 0)
    black = Image.new("RGBA", original.size, (0, 0, 0, 255))
    black.putalpha(alpha)
    return crop_alpha(black)


def split_mascots() -> tuple[Image.Image, Image.Image]:
    source = Image.open(MASCOTS).convert("RGBA")
    middle = source.width // 2
    return crop_alpha(source.crop((0, 0, middle, source.height))), crop_alpha(
        source.crop((middle, 0, source.width, source.height))
    )


def fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    ratio = min(max_width / image.width, max_height / image.height)
    return image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)


def turned_sprite(sprite: Image.Image, turn: float) -> Image.Image:
    # A shrinking horizontal axis simulates a character rotating in place.
    axis = cos(pi * turn)
    width = max(2, round(sprite.width * abs(axis)))
    result = sprite.resize((width, sprite.height), Image.Resampling.LANCZOS)
    if axis < 0:
        result = result.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return result


def composite_mascots(canvas_size, left, right, progress, turn) -> Image.Image:
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    left_frame = turned_sprite(left, turn)
    right_frame = turned_sprite(right, turn)
    center_x = canvas_size[0] // 2
    gap = round(190 * (1.0 - progress) - 92 * progress)
    baseline = 506
    lx = center_x - gap // 2 - left_frame.width
    rx = center_x + gap // 2
    canvas.alpha_composite(left_frame, (lx, baseline - left_frame.height))
    canvas.alpha_composite(right_frame, (rx, baseline - right_frame.height))
    return canvas


def main() -> None:
    canvas_size = (900, 540)
    left_raw, right_raw = split_mascots()
    left = fit(left_raw, 310, 450)
    right = fit(right_raw, 310, 450)
    logo = fit(prepare_logo(), 700, 500)
    logo_canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    logo_canvas.alpha_composite(
        logo,
        ((canvas_size[0] - logo.width) // 2, (canvas_size[1] - logo.height) // 2),
    )

    frames = []
    total = 112
    for index in range(total):
        phase = index / (total - 1)
        # The second half reverses the first, producing a smooth endless loop.
        journey = phase * 2 if phase <= 0.5 else (1.0 - phase) * 2
        if journey < 0.16:
            merge = 0.0
            turn = 0.0
            logo_mix = 0.0
        elif journey < 0.54:
            local = ease((journey - 0.16) / 0.38)
            merge = local
            turn = local
            logo_mix = 0.0
        elif journey < 0.72:
            merge = 1.0
            turn = 1.0
            logo_mix = ease((journey - 0.54) / 0.18)
        else:
            merge = 1.0
            turn = 1.0
            logo_mix = 1.0

        mascots = composite_mascots(canvas_size, left, right, merge, turn)
        frames.append(Image.blend(mascots, logo_canvas, logo_mix))

    # Transparent application version.
    transparent_frames = []
    for frame in frames:
        rgb = Image.new("RGB", canvas_size, (255, 255, 255))
        rgb.paste(frame, mask=frame.getchannel("A"))
        indexed = rgb.quantize(colors=254)
        mask = frame.getchannel("A").point(lambda value: 255 if value < 32 else 0)
        indexed.paste(255, mask=mask)
        indexed.info["transparency"] = 255
        transparent_frames.append(indexed)
    transparent_frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=transparent_frames[1:],
        duration=55,
        loop=0,
        disposal=2,
        transparency=255,
        optimize=False,
    )

    # Light preview version for easy viewing.
    light_frames = []
    for frame in frames:
        light = Image.new("RGB", canvas_size, (246, 246, 242))
        light.paste(frame, mask=frame.getchannel("A"))
        light_frames.append(light.quantize(colors=128))
    light_frames[0].save(
        OUTPUT_LIGHT,
        save_all=True,
        append_images=light_frames[1:],
        duration=55,
        loop=0,
        disposal=2,
        optimize=True,
    )
    print(OUTPUT)
    print(OUTPUT_LIGHT)


if __name__ == "__main__":
    main()

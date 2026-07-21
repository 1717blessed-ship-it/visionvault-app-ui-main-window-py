from pathlib import Path
from math import cos, pi, sin

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "mascots"
SOURCE = ASSETS / "doccione-logo-original.png"
OUTPUT = ASSETS / "doccione-original-gargoyles.gif"
OUTPUT_LIGHT = ASSETS / "doccione-original-gargoyles-light.gif"
STATIC = ASSETS / "doccione-original-silhouette.png"


def ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 0.5 - 0.5 * cos(pi * value)


def prepare_exact_logo() -> Image.Image:
    gray = Image.open(SOURCE).convert("L")
    # The lettering was printed as white holes over an otherwise solid torso.
    # This band is fully inside the joined body, so restoring it does not alter
    # the external silhouette or any original brush edge.
    ImageDraw.Draw(gray).rectangle((545, 520, 1460, 690), fill=0)
    alpha = gray.point(lambda pixel: 255 if pixel < 210 else 0)
    result = Image.new("RGBA", gray.size, (0, 0, 0, 255))
    result.putalpha(alpha)
    bbox = alpha.getbbox()
    if not bbox:
        raise RuntimeError("No se encontró el logo")
    return result.crop(bbox)


def fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    ratio = min(max_width / image.width, max_height / image.height)
    return image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)


def place(canvas: Image.Image, sprite: Image.Image, x: int, y: int) -> None:
    canvas.alpha_composite(sprite, (round(x), round(y)))


def make_frames() -> list[Image.Image]:
    canvas_size = (900, 540)
    exact = fit(prepare_exact_logo(), 650, 500)
    exact.save(STATIC)
    middle = exact.width // 2
    left = exact.crop((0, 0, middle, exact.height))
    right = exact.crop((middle, 0, exact.width, exact.height))
    frames = []
    total = 112

    for index in range(total):
        phase = index / (total - 1)
        # Separate and return along the same path for a clean continuous loop.
        journey = phase * 2 if phase <= 0.5 else (1.0 - phase) * 2
        if journey < 0.16:
            amount = 0.0
        elif journey < 0.58:
            amount = ease((journey - 0.16) / 0.42)
        else:
            amount = 1.0

        # Only rigid movement is applied: the actual artwork is never redrawn.
        angle = 5.5 * amount
        left_frame = left.rotate(-angle, Image.Resampling.BICUBIC, expand=True)
        right_frame = right.rotate(angle, Image.Resampling.BICUBIC, expand=True)
        separation = round(120 * amount)
        lift = round(5 * sin(pi * amount))
        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        joined_x = (canvas_size[0] - exact.width) // 2
        joined_y = (canvas_size[1] - exact.height) // 2
        place(canvas, left_frame, joined_x - separation - (left_frame.width - left.width) // 2, joined_y - lift)
        place(canvas, right_frame, joined_x + middle + separation - (right_frame.width - right.width) // 2, joined_y - lift)
        frames.append(canvas)
    return frames


def save_gifs(frames: list[Image.Image]) -> None:
    size = frames[0].size
    transparent = []
    light = []
    for frame in frames:
        white = Image.new("RGB", size, (255, 255, 255))
        white.paste(frame, mask=frame.getchannel("A"))
        indexed = white.quantize(colors=254)
        invisible = frame.getchannel("A").point(lambda alpha: 255 if alpha < 28 else 0)
        indexed.paste(255, mask=invisible)
        indexed.info["transparency"] = 255
        transparent.append(indexed)

        preview = Image.new("RGB", size, (246, 246, 242))
        preview.paste(frame, mask=frame.getchannel("A"))
        light.append(preview.quantize(colors=128))

    transparent[0].save(
        OUTPUT, save_all=True, append_images=transparent[1:], duration=55,
        loop=0, disposal=2, transparency=255, optimize=False,
    )
    light[0].save(
        OUTPUT_LIGHT, save_all=True, append_images=light[1:], duration=55,
        loop=0, disposal=2, optimize=True,
    )


if __name__ == "__main__":
    generated = make_frames()
    save_gifs(generated)
    print(OUTPUT)
    print(OUTPUT_LIGHT)
    print(STATIC)

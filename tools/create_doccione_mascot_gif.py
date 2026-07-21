from pathlib import Path
from math import cos, pi, sin

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "mascots" / "doccione-mascots.png"
OUTPUT = ROOT / "assets" / "mascots" / "doccione-mascots-intro.gif"
OUTPUT_LIGHT = ROOT / "assets" / "mascots" / "doccione-mascots-intro-light.gif"
PREVIEW = ROOT / "assets" / "mascots" / "doccione-mascots-intro-preview.png"


def ease(t: float) -> float:
    return 0.5 - 0.5 * cos(pi * max(0.0, min(1.0, t)))


def crop_half(source: Image.Image, left: bool) -> Image.Image:
    midpoint = source.width // 2
    half = source.crop((0 if left else midpoint, 0, midpoint if left else source.width, source.height))
    alpha = half.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        raise RuntimeError("No se encontró la silueta")
    return half.crop(bbox)


def mascot_frame(sprite: Image.Image, scale: float, angle: float) -> Image.Image:
    size = (round(sprite.width * scale), round(sprite.height * scale))
    resized = sprite.resize(size, Image.Resampling.LANCZOS)
    return resized.rotate(angle, Image.Resampling.BICUBIC, expand=True)


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    left = crop_half(source, True)
    right = crop_half(source, False)

    canvas_size = (900, 540)
    frames: list[Image.Image] = []
    frame_count = 84

    for index in range(frame_count):
        phase = index / frame_count
        # Closed -> separate -> friendly bounce/pose -> reunite for a seamless loop.
        if phase < 0.14:
            separation = 0.0
        elif phase < 0.40:
            separation = ease((phase - 0.14) / 0.26)
        elif phase < 0.73:
            separation = 1.0
        else:
            separation = 1.0 - ease((phase - 0.73) / 0.27)

        pose = sin(pi * max(0.0, min(1.0, (phase - 0.38) / 0.36))) if 0.38 <= phase <= 0.74 else 0.0
        bounce = -round(7 * pose * abs(sin(phase * 8 * pi)))
        scale = 0.43 + 0.012 * pose
        tilt = 2.2 * pose

        left_frame = mascot_frame(left, scale, tilt)
        right_frame = mascot_frame(right, scale, -tilt)
        center_gap = 18 + round(150 * separation)
        center_x = canvas_size[0] // 2
        baseline = 510 + bounce

        lx = center_x - center_gap // 2 - left_frame.width
        rx = center_x + center_gap // 2
        ly = baseline - left_frame.height
        ry = baseline - right_frame.height

        canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        canvas.alpha_composite(left_frame, (lx, ly))
        canvas.alpha_composite(right_frame, (rx, ry))
        frames.append(canvas)

    # GIF transparency is palette based. A shared adaptive palette avoids color flicker.
    matte = Image.new("RGBA", canvas_size, (255, 255, 255, 0))
    palette_source = Image.alpha_composite(matte, frames[frame_count // 2]).convert("RGB")
    palette = palette_source.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    gif_frames = []
    for frame in frames:
        rgb = Image.new("RGB", canvas_size, (255, 255, 255))
        rgb.paste(frame, mask=frame.getchannel("A"))
        quantized = rgb.quantize(palette=palette)
        alpha = frame.getchannel("A")
        transparent_mask = alpha.point(lambda value: 255 if value < 24 else 0)
        quantized.paste(255, mask=transparent_mask)
        quantized.info["transparency"] = 255
        gif_frames.append(quantized)

    gif_frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=gif_frames[1:],
        duration=55,
        loop=0,
        disposal=2,
        transparency=255,
        optimize=False,
    )
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
    frames[frame_count // 2].save(PREVIEW)
    print(OUTPUT)
    print(OUTPUT_LIGHT)
    print(PREVIEW)


if __name__ == "__main__":
    main()

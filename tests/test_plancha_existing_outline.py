from PIL import Image, ImageDraw

from app.planchas.editor import prepare_sticker_for_target


def test_preoutlined_sticker_receives_inner_white_and_outer_black_outline():
    image = Image.new("RGBA", (100, 100))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 91, 91), fill="white")
    draw.ellipse((17, 17, 82, 82), fill=(220, 30, 30, 255))

    result = prepare_sticker_for_target(image, (300, 300), outlined=True)

    opaque_black = sum(
        alpha > 240 and red < 20 and green < 20 and blue < 20
        for red, green, blue, alpha in result.get_flattened_data()
    )
    assert opaque_black > 0
    assert result.getpixel((150, 150))[:3] == (220, 30, 30)

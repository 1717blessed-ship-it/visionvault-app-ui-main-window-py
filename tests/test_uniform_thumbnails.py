from pathlib import Path

from PIL import Image

from app.indexer.thumbnails import prepare_thumbnail, thumbnail_png_bytes


def _source(path: Path, size: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    Image.new("RGBA", size, color).save(path)


def test_uniform_thumbnail_uses_the_same_long_side_and_visible_black_border(
    tmp_path: Path,
):
    horizontal = tmp_path / "horizontal.png"
    vertical = tmp_path / "vertical.png"
    _source(horizontal, (20, 10), (255, 0, 0, 255))
    _source(vertical, (10, 20), (0, 255, 0, 255))

    horizontal_preview = prepare_thumbnail(
        str(horizontal), 100, 100, horizontal.stat().st_mtime, border=2, upscale=True
    )
    vertical_preview = prepare_thumbnail(
        str(vertical), 100, 100, vertical.stat().st_mtime, border=2, upscale=True
    )

    assert horizontal_preview.size == (100, 52)
    assert vertical_preview.size == (52, 100)
    assert max(horizontal_preview.size) == max(vertical_preview.size) == 100
    assert horizontal_preview.getpixel((0, 0)) == (0, 0, 0, 255)
    assert vertical_preview.getpixel((0, 0)) == (0, 0, 0, 255)


def test_http_thumbnail_bytes_are_reused_in_memory(tmp_path: Path):
    source = tmp_path / "source.png"
    _source(source, (24, 12), (0, 0, 255, 255))
    modified = source.stat().st_mtime
    thumbnail_png_bytes.cache_clear()

    first = thumbnail_png_bytes(
        str(source), 100, 100, modified, border=2, upscale=True
    )
    second = thumbnail_png_bytes(
        str(source), 100, 100, modified, border=2, upscale=True
    )

    assert first == second
    assert thumbnail_png_bytes.cache_info().hits == 1


def test_catalog_thumbnail_trims_transparent_hitbox_without_drawing_a_frame(
    tmp_path: Path,
):
    source = tmp_path / "transparent-canvas.png"
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (10, 15, 30, 25))
    image.save(source)

    preview = prepare_thumbnail(
        str(source),
        100,
        100,
        source.stat().st_mtime,
        upscale=True,
        trim_transparency=True,
    )

    assert preview.size == (100, 50)
    assert preview.getpixel((0, 0)) == (255, 0, 0, 255)


def test_catalog_thumbnail_ignores_nearly_invisible_alpha_residue(tmp_path: Path):
    source = tmp_path / "dirty-alpha.png"
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    image.putpixel((1, 1), (255, 255, 255, 4))
    image.paste((255, 0, 0, 255), (40, 20, 60, 80))
    image.save(source)

    preview = prepare_thumbnail(
        str(source), 100, 100, source.stat().st_mtime,
        upscale=True, trim_transparency=True,
    )

    # El diseño vertical ocupa la altura de la tarjeta; el residuo de la
    # esquina no vuelve a convertir la miniatura en un cuadrado diminuto.
    assert preview.height == 100
    assert preview.width < 50

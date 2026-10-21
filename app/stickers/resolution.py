"""Salida nativa y conversiones entre coordenadas fuente y producción."""
from PIL import Image, ImageFilter
import numpy as np


def render_native(processor, clean, output, *, content_scale, existing_border,
                  cut_inset_mm, inner_white=False, cut_override=None,
                  progress=lambda *_: None):
    """Conserva cada píxel de diseño y rasteriza el borde al DPI efectivo.

    El maestro legacy sigue midiendo los píxeles del perfil de impresión.
    Esta salida complementaria evita perder detalle o aparentar detalle
    adicional cuando la fuente es pequeña. Nunca parte de una miniatura.
    """
    profile = processor.profile
    native_scale = 1.0 / content_scale
    side = max(max(clean.size), round(profile.master_pixels * native_scale))
    if side * side > 40_000_000:
        raise ValueError(
            "La salida nativa cuadrada supera 40 megapíxeles. "
            "Recortá márgenes innecesarios o dividí el diseño; la fuente no se redujo.")
    dpi = side * 2.54 / profile.resolved_asset_target_size_cm
    ratio = dpi / profile.dpi
    offset = ((side - clean.width) // 2, (side - clean.height) // 2)
    design = Image.new("RGBA", (side, side))
    design.alpha_composite(clean, offset)
    binary = design.getchannel("A").point(lambda value: 255 if value > 12 else 0)
    progress(75, "Construyendo salida a resolución nativa")
    # Morphological closing on the canvas boundary uses an implicit nonzero
    # border. Work on a zero-padded temporary raster to avoid flattened caps.
    support = max(4, round((profile.final_white_px + profile.smooth_px + 4) * ratio))
    padded = np.pad(np.asarray(binary), support)
    base, _ = processor._build_unified_white_base(
        padded, final_white_px=0 if existing_border else max(0, round(profile.final_white_px * ratio)),
        merge_regions_mm=profile.merge_regions_mm, dpi=dpi,
    )
    base = Image.fromarray(base)
    if profile.smooth_px:
        base = base.filter(ImageFilter.GaussianBlur(profile.smooth_px * ratio / 2)).point(
            lambda value: 255 if value >= 128 else 0)
    base = base.crop((support, support, support + side, support + side))
    # La limpieza de microburbujas ya se aplica a la máscara fuente y al
    # maestro; no se vuelve a erosionar el diseño nativo.
    native = Image.new("RGBA", (side, side), "white")
    native.putalpha(base)
    native.alpha_composite(design)
    if inner_white:
        layer = processor._build_inner_white_stroke(base, max(1, round(min(2, profile.inner_white_px) * ratio)), design)
        native.alpha_composite(layer)
    cut = processor._contract(base, max(0, round(cut_inset_mm * dpi / 25.4))).point(
        lambda value: 255 if value > 127 else 0)
    if cut_override is not None:
        cut = cut_override.resize((side, side), Image.Resampling.NEAREST)
    artifacts = {}
    for name, image in (("native_master", native), ("native_printable_base", base), ("native_cut", cut)):
        path = output / f"{name}.png"
        image.save(path, dpi=(dpi, dpi), optimize=False)
        artifacts[name] = str(path)
    progress(79, "Salida nativa guardada")
    return artifacts, {"pixels": [side, side], "dpi": dpi,
                       "source_to_native_scale": 1.0,
                       "master_to_native_scale": ratio,
                       "design_offset": list(offset),
                       "physical_size_cm": profile.resolved_asset_target_size_cm,
                       "border_px": 0 if existing_border else round(profile.final_white_px * ratio),
                       "cut_inset_px": round(cut_inset_mm * dpi / 25.4)}

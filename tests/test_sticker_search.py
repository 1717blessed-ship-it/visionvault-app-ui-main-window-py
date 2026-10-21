import pytest
from pathlib import Path
from PIL import Image, ImageDraw
from app.ai.visual_search import find_similar, _precise_similarity
from app.ai import visual_search

def create_circle_image(path: Path, color=(255, 0, 0, 255), bg_color=(0, 0, 0, 0), size=(100, 100)):
    """Crea una imagen de un círculo sólido en un fondo dado."""
    img = Image.new("RGBA", size, bg_color)
    draw = ImageDraw.Draw(img)
    w, h = size
    # Dibujar círculo centrado
    margin = min(w, h) // 10
    draw.ellipse([margin, margin, w - margin, h - margin], fill=color)
    img.save(path)

def create_square_image(path: Path, color=(255, 0, 0, 255), bg_color=(0, 0, 0, 0), size=(100, 100)):
    """Crea una imagen de un cuadrado sólido en un fondo dado."""
    img = Image.new("RGBA", size, bg_color)
    draw = ImageDraw.Draw(img)
    w, h = size
    margin = min(w, h) // 10
    draw.rectangle([margin, margin, w - margin, h - margin], fill=color)
    img.save(path)

def create_circle_with_cross_image(path: Path, color=(255, 0, 0, 255), cross_color=(0, 0, 0, 255), size=(100, 100)):
    """Crea una imagen de un círculo rojo con una cruz negra encima."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    margin = min(w, h) // 10
    draw.ellipse([margin, margin, w - margin, h - margin], fill=color)
    # Dibujar cruz
    draw.line([0, 0, w, h], fill=cross_color, width=8)
    draw.line([0, h, w, 0], fill=cross_color, width=8)
    img.save(path)

def create_blue_triangle_image(path: Path, color=(0, 0, 255, 255), size=(100, 100)):
    """Crea una imagen de un triángulo azul en fondo transparente."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    w, h = size
    draw.polygon([(w // 2, 10), (10, h - 10), (w - 10, h - 10)], fill=color)
    img.save(path)

def create_asymmetric_design(path: Path, size=(100, 100)):
    """Diseño con una orientación inequívoca para validar rotaciones."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon([(18, 82), (50, 12), (82, 82)], fill=(245, 173, 25, 255))
    draw.ellipse((42, 31, 58, 47), fill=(35, 45, 70, 255))
    draw.rectangle((47, 48, 53, 73), fill=(35, 45, 70, 255))
    img.save(path)


def test_sticker_search_logic(tmp_path, monkeypatch):
    # Rutas de archivos de prueba
    orig_path = tmp_path / "original.png"
    resized_path = tmp_path / "resized.png"
    canvas_path = tmp_path / "canvas.png"
    square_path = tmp_path / "square.png"
    cross_path = tmp_path / "cross.png"
    unrelated_path = tmp_path / "unrelated.png"

    # 1. Crear las imágenes de prueba
    create_circle_image(orig_path, size=(100, 100))
    create_circle_image(resized_path, size=(50, 50))  # Versión redimensionada
    create_circle_image(canvas_path, size=(200, 200))  # Lienzo transparente de diferente tamaño
    create_square_image(square_path)  # Comparte colores (rojo) pero forma distinta
    create_circle_with_cross_image(cross_path)  # Mismo personaje pero diseño visual diferente
    create_blue_triangle_image(unrelated_path)  # Imagen sin relación

    # Formar la lista de candidatos para la búsqueda
    candidates = [
        {"path": str(resized_path), "name": "resized", "modified": 1.0, "visual_signature": "", "tags": "circulo · rojo"},
        {"path": str(canvas_path), "name": "canvas", "modified": 1.0, "visual_signature": "", "tags": "circulo · rojo"},
        {"path": str(square_path), "name": "square", "modified": 1.0, "visual_signature": "", "tags": "cuadrado · rojo"},
        {"path": str(cross_path), "name": "cross", "modified": 1.0, "visual_signature": "", "tags": "circulo · cruz · rojo"},
        {"path": str(unrelated_path), "name": "unrelated", "modified": 1.0, "visual_signature": "", "tags": "triangulo · azul"}
    ]
    monkeypatch.setattr(visual_search, "get_resnet_embedding", lambda *_args, **_kwargs: [1.0, 0.0])
    for candidate in candidates:
        modified = Path(candidate["path"]).stat().st_mtime
        candidate["modified"] = modified
        candidate["visual_signature_modified"] = modified
        candidate["visual_signature"] = visual_search.build_visual_signature(
            candidate["path"], embedding=[1.0, 0.0], text=candidate["tags"]
        )

    # Pruebas de la Segunda Etapa directa (_precise_similarity)
    # Redimensionado debe dar similitud muy alta (casi 100%) ya que tras crop e resize son idénticos
    res_resized = _precise_similarity(str(orig_path), str(resized_path))
    shape_sim_r, color_sim_r, hash_sim_r, dist_r = res_resized
    assert shape_sim_r >= 0.95
    assert color_sim_r >= 0.95

    # Diferente lienzo transparente debe seguir siendo idéntico tras el recortado
    res_canvas = _precise_similarity(str(orig_path), str(canvas_path))
    shape_sim_c, color_sim_c, hash_sim_c, dist_c = res_canvas
    assert shape_sim_c >= 0.95
    assert color_sim_c >= 0.95

    # Cuadrado vs círculo comparte color pero su forma (IoU) y hash estructural deben ser bajos
    res_square = _precise_similarity(str(orig_path), str(square_path))
    shape_sim_s, color_sim_s, hash_sim_s, dist_s = res_square
    assert shape_sim_s < 0.82  # La intersección de círculo y cuadrado es menor al 80%

    oriented_path = tmp_path / "oriented.png"
    rotated_path = tmp_path / "rotated.png"
    create_asymmetric_design(oriented_path)
    with Image.open(oriented_path) as oriented:
        oriented.rotate(90, expand=True).save(rotated_path)
    shape_sim_rot, color_sim_rot, hash_sim_rot, _ = _precise_similarity(str(oriented_path), str(rotated_path))
    assert shape_sim_rot >= 0.95
    assert color_sim_rot >= 0.95
    assert hash_sim_rot >= 0.90

    # El diseño debe encontrarse dentro de una composición aunque tenga marco
    # y una marca de agua semitransparente.
    collage_path = tmp_path / "collage.png"
    collage = Image.new("RGBA", (260, 140), (0, 0, 0, 0))
    with Image.open(oriented_path) as design:
        collage.alpha_composite(design, (12, 20))
    other = Image.new("RGBA", (75, 75), (0, 0, 0, 0))
    ImageDraw.Draw(other).ellipse((8, 8, 67, 67), fill=(70, 130, 245, 255))
    collage.alpha_composite(other, (164, 32))
    collage_draw = ImageDraw.Draw(collage)
    collage_draw.rectangle((0, 0, 259, 139), outline=(0, 0, 0, 255), width=2)
    collage_draw.text((95, 112), "MUESTRA", fill=(255, 255, 255, 80))
    collage.save(collage_path)
    shape_sim_multi, color_sim_multi, hash_sim_multi, _ = _precise_similarity(str(oriented_path), str(collage_path))
    assert shape_sim_multi >= 0.90
    assert color_sim_multi >= 0.90
    assert hash_sim_multi >= 0.80

    # Pruebas con find_similar
    # 2. Comprobar que una versión redimensionada sí es encontrada en modo casi exacto (min 96%)
    matches_exact = find_similar(str(orig_path), candidates, minimum_score=96.0, mode="casi_exacto")
    match_paths_exact = [m[0] for m in matches_exact]
    assert str(resized_path) in match_paths_exact
    assert str(canvas_path) in match_paths_exact

    # 3. Comprobar que dos diseños del mismo personaje pero visualmente diferentes (cross) no aparezcan en casi exacto
    assert str(cross_path) not in match_paths_exact

    # 4. Comprobar que una imagen que sólo comparte colores (square) sea descartada en modo casi exacto y estricto
    matches_strict = find_similar(str(orig_path), candidates, minimum_score=90.0, mode="estricto")
    match_paths_strict = [m[0] for m in matches_strict]
    assert str(square_path) not in match_paths_strict
    assert str(square_path) not in match_paths_exact

    # 5. Comprobar que un resultado de 89% no aparezca con un mínimo de 90%
    # Si creamos un candidato falso que tenga un score artificial, o validamos con los umbrales
    # Simulamos una llamada con un umbral de 90% y comprobamos que no haya ningún elemento con score < 90%
    for path, score in matches_strict:
        assert score >= 90.0

    # 6. Comprobar que los resultados se ordenen de mayor a menor similitud
    scores = [score for path, score in matches_strict]
    assert scores == sorted(scores, reverse=True)

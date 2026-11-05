"""Búsqueda visual avanzada en dos etapas para encontrar stickers iguales o muy parecidos."""

import base64
import json
import time
from hashlib import sha256
import numpy as np
import cv2
from pathlib import Path
from typing import Optional, Tuple

# Variable global para guardar de forma diferida el modelo de embedding
_resnet_model = None
_resnet_transforms = None

# Configuración de logging para diagnóstico
_diagnostic_log_enabled = False
_diagnostic_log_path = None

# Versión del índice visual - incrementar cuando cambie el formato de normalización o firma
VISUAL_INDEX_VERSION = 4
_BIT_COUNTS = np.array([value.bit_count() for value in range(256)], dtype=np.uint8)


def _unified_normalize_image(image_path: str, target_size: int = 224, ignore_background: bool = True) -> Optional[Tuple]:
    """Normalización unificada para consulta y banco de imágenes.

    Aplica el mismo procesamiento a ambas imágenes para garantizar comparabilidad:
    - Convertir a RGBA
    - Detectar transparencia y fondos blancos cercanos al blanco
    - Generar máscara real del objeto
    - Eliminar márgenes transparentes o blancos exteriores
    - Recortar por bounding box del contenido
    - Centrar el objeto en un lienzo cuadrado
    - Redimensionar siempre al mismo tamaño

    Returns:
        (normalized_pil_image, mask_array, original_rgba) or None on error
    """
    from PIL import Image, ImageOps

    try:
        with Image.open(image_path) as img:
            original = img.convert("RGBA")
    except Exception:
        return None

    rgba = original.copy()
    width, height = rgba.size

    # Detectar transparencia
    alpha = rgba.getchannel("A")
    alpha_arr = np.array(alpha)
    has_transparency = alpha_arr.min() < 250

    # Crear máscara inicial basada en transparencia
    if has_transparency:
        # Usar umbral más estricto para transparencia real
        mask = alpha_arr > 25
    else:
        # Sin transparencia: estimar fondo si es uniforme
        rgb = np.array(rgba.convert("RGB"))

        if ignore_background:
            # Muestrear esquinas para detectar fondo
            corner_size = min(10, width // 4, height // 4)
            corners = [
                rgb[0:corner_size, 0:corner_size],
                rgb[0:corner_size, -corner_size:],
                rgb[-corner_size:, 0:corner_size],
                rgb[-corner_size:, -corner_size:]
            ]
            corner_pixels = np.vstack([c.reshape(-1, 3) for c in corners])
            bg_color = np.median(corner_pixels, axis=0)

            # Crear máscara basada en diferencia del fondo
            diff = np.abs(rgb.astype(np.int16) - bg_color.astype(np.int16))
            mask = np.any(diff > 25, axis=2)
        else:
            # No ignorar fondo: todo es contenido
            mask = np.ones((height, width), dtype=bool)

    # Limpiar máscara con operaciones morfológicas
    mask_uint8 = (mask.astype(np.uint8) * 255)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_uint8 = cv2.morphologyEx(mask_uint8, cv2.MORPH_CLOSE, kernel)
    mask_uint8 = cv2.morphologyEx(mask_uint8, cv2.MORPH_OPEN, kernel)

    # Encontrar bounding box del contenido
    mask_pil = Image.fromarray(mask_uint8, mode="L")
    bbox = mask_pil.getbbox()

    if not bbox:
        # Si no hay contenido, usar imagen completa
        bbox = (0, 0, width, height)

    # Recortar al bounding box con pequeño margen
    margin = max(2, int(min(width, height) * 0.01))
    bbox = (
        max(0, bbox[0] - margin),
        max(0, bbox[1] - margin),
        min(width, bbox[2] + margin),
        min(height, bbox[3] + margin)
    )

    cropped = rgba.crop(bbox)
    cropped_mask = mask_uint8[bbox[1]:bbox[3], bbox[0]:bbox[2]]

    # Centrar en lienzo cuadrado manteniendo proporción
    cropped_w, cropped_h = cropped.size
    max_dim = max(cropped_w, cropped_h)

    # Crear lienzo cuadrado transparente
    canvas = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
    mask_canvas = np.zeros((max_dim, max_dim), dtype=np.uint8)
    offset_x = (max_dim - cropped_w) // 2
    offset_y = (max_dim - cropped_h) // 2
    canvas.paste(cropped, (offset_x, offset_y), cropped)
    mask_canvas[offset_y:offset_y + cropped_h, offset_x:offset_x + cropped_w] = cropped_mask

    # Redimensionar al tamaño objetivo
    if max_dim != target_size:
        canvas = canvas.resize((target_size, target_size), Image.Resampling.LANCZOS)
        mask_canvas = cv2.resize(mask_canvas, (target_size, target_size), interpolation=cv2.INTER_NEAREST)

    return canvas, (mask_canvas > 127), original


def get_resnet_embedding(image_path: str, use_unified_normalize: bool = False) -> list[float]:
    """Obtiene un vector de embedding visual de 512 dimensiones usando ResNet-18.

    Args:
        image_path: Ruta a la imagen
        use_unified_normalize: Si True, usa normalización unificada para consistencia
    """
    global _resnet_model, _resnet_transforms
    try:
        import torch
        import torchvision.models as models
        import torchvision.transforms as transforms
        from PIL import Image

        if _resnet_model is None:
            # Cargamos de forma local/diferida
            from torchvision.models import resnet18, ResNet18_Weights
            weights = ResNet18_Weights.DEFAULT
            model = resnet18(weights=weights)
            # Removemos la última capa fc sustituyéndola por una identidad
            model.fc = torch.nn.Identity()
            model.eval()
            _resnet_model = model

            # Transformaciones estándar de ResNet
            _resnet_transforms = transforms.Compose([
                transforms.Resize(256),
                transforms.CenterCrop(224),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225]
                ),
            ])

        if use_unified_normalize:
            # Usar normalización unificada
            normalized_result = _unified_normalize_image(image_path, target_size=224)
            if normalized_result is None:
                return [0.0] * 512
            img_rgb = normalized_result[0].convert("RGB")
        else:
            # Usar método original para compatibilidad
            with Image.open(image_path) as img:
                img_rgb = img.convert("RGB")

        tensor = _resnet_transforms(img_rgb).unsqueeze(0)
        with torch.no_grad():
            feat = _resnet_model(tensor).squeeze(0)
            # Normalizamos L2 para simplificar la similitud coseno como producto punto
            feat = feat / (torch.norm(feat) + 1e-8)
            return feat.tolist()
    except Exception:
        # Vector de fallback en caso de error
        return [0.0] * 512


def _signature_for_image(source) -> tuple[str, bytes, tuple[float, ...]]:
    from PIL import Image, ImageOps, ImageStat

    source = source.convert("RGBA")
    alpha_box = source.getchannel("A").point(lambda value: 255 if value > 8 else 0).getbbox()
    if alpha_box:
        source = source.crop(alpha_box)
    # Un fondo uniforme hace comparables PNGs transparentes y JPGs.
    background = Image.new("RGBA", source.size, "#111314")
    background.alpha_composite(source)
    image = ImageOps.fit(background.convert("RGB"), (32, 32), method=Image.Resampling.LANCZOS)
    raw = image.tobytes()
    grayscale = np.asarray(image.convert("L"), dtype=np.uint8).reshape(-1)
    average = float(grayscale.mean())
    perceptual = [int(value >= average) for value in grayscale]
    packed_bits = bytes(sum(perceptual[offset + bit] << (7 - bit) for bit in range(8)) for offset in range(0, len(perceptual), 8))
    stats = ImageStat.Stat(image)
    # Promedio y variación de color
    colors = tuple(round(value, 2) for value in (*stats.mean, *stats.var))
    return sha256(raw).hexdigest(), packed_bits, colors


def signature_variants(path: str) -> list[tuple[str, bytes, tuple[float, ...]]]:
    """Huellas de los cuatro ángulos principales de un mismo sticker."""
    from PIL import Image

    with Image.open(path) as source:
        original = source.convert("RGBA")
    return [
        _signature_for_image(original.rotate(angle, expand=True, fillcolor=(0, 0, 0, 0)))
        for angle in range(0, 360, 30)
    ]


def visual_index_features(path: str, text: str = "") -> dict:
    """Extrae color y silueta compactos, persistibles e invariantes a rotación."""
    normalized = _unified_normalize_image(path, target_size=128)
    if normalized is None:
        return {"color_hist": [], "hu": [], "aspect": 1.0, "occupancy": 0.0, "text": text.strip()}
    image, mask, _original = normalized
    rgb = np.array(image.convert("RGB"))
    mask = np.asarray(mask, dtype=bool)
    visible = rgb[mask]

    color_hist = np.zeros(12, dtype=np.float32)
    if visible.size:
        hsv = cv2.cvtColor(visible.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
        chromatic = hsv[(hsv[:, 1] >= 42) & (hsv[:, 2] >= 28)]
        if chromatic.size:
            color_hist, _ = np.histogram(chromatic[:, 0], bins=12, range=(0, 180))
            color_hist = color_hist.astype(np.float32)
            color_hist /= max(1.0, float(color_hist.sum()))

    mask_u8 = mask.astype(np.uint8) * 255
    hu_raw = cv2.HuMoments(cv2.moments(mask_u8)).flatten()
    hu = [float(-np.sign(value) * np.log10(abs(value) + 1e-30)) for value in hu_raw]
    y_points, x_points = np.nonzero(mask)
    radial = np.zeros(16, dtype=np.float32)
    if x_points.size:
        distances = np.hypot(x_points - x_points.mean(), y_points - y_points.mean())
        distances /= max(1e-6, float(distances.max()))
        radial, _ = np.histogram(distances, bins=16, range=(0.0, 1.0))
        radial = radial.astype(np.float32)
        radial /= max(1.0, float(radial.sum()))
    points = cv2.findNonZero(mask_u8)
    if points is None:
        aspect = 1.0  # Default to square aspect ratio
    else:
        _x, _y, width, height = cv2.boundingRect(points)
        # Preserve orientation: >1 for horizontal, <1 for vertical, =1 for square
        aspect = width / max(1, height)
    return {
        "color_hist": [round(float(value), 6) for value in color_hist],
        "hu": [round(value, 6) for value in hu],
        "radial": [round(float(value), 6) for value in radial],
        "aspect": round(float(aspect), 6),
        "occupancy": round(float(mask.mean()), 6),
        "text": " ".join(str(text or "").casefold().split())[:500],
    }


def signature_to_text(signatures, embedding=None, phash=None, dhash=None, features=None) -> str:
    """Formato corto para persistir la huella e incluye el embedding visual en versión 3.

    Ahora incluye VISUAL_INDEX_VERSION para detectar cambios en el formato.
    Versión 4 incluye phash y dhash pre-calculados para evitar recalcular en cada búsqueda.
    """
    if signatures and isinstance(signatures[0], str):
        signatures = [signatures]
    encoded = [(digest, base64.b64encode(bits).decode("ascii"), colors) for digest, bits, colors in signatures]
    data = {"version": 4, "index_version": VISUAL_INDEX_VERSION, "angles": encoded}
    if embedding is not None:
        data["embedding"] = embedding
    if phash is not None:
        data["phash"] = base64.b64encode(phash).decode("ascii")
    if dhash is not None:
        data["dhash"] = base64.b64encode(dhash).decode("ascii")
    if features:
        data["features"] = features
    return json.dumps(data, separators=(",", ":"))


def build_visual_signature(path: str, embedding=None, text: str = "") -> str:
    """Construye todo lo que una búsqueda posterior necesita sin reabrir el archivo."""
    signatures = signature_variants(path)
    if embedding is None:
        embedding = get_resnet_embedding(path)
    phash, dhash = _compute_phash_dhash(path)
    return signature_to_text(
        signatures,
        embedding,
        phash,
        dhash,
        visual_index_features(path, text),
    )


def signature_from_text(value: str):
    try:
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            decoded = decoded.get("angles", [])
        elif isinstance(decoded, list) and len(decoded) == 3 and isinstance(decoded[0], str):
            decoded = [decoded]
        return [(str(digest), base64.b64decode(bits), tuple(float(color) for color in colors)) for digest, bits, colors in decoded]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def signature_and_embedding_from_text(value: str):
    """Devuelve la huella visual original y el embedding de versión 3.

    También retorna la versión del índice para detectar migraciones necesarias.
    Versión 4 incluye phash y dhash pre-calculados.
    """
    try:
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            angles_data = decoded.get("angles", [])
            embedding = decoded.get("embedding", None)
            index_version = decoded.get("index_version", 1)  # Default to version 1 if not present
            phash_b64 = decoded.get("phash", None)
            dhash_b64 = decoded.get("dhash", None)

            phash = base64.b64decode(phash_b64) if phash_b64 else None
            dhash = base64.b64decode(dhash_b64) if dhash_b64 else None
            features = decoded.get("features") or {}

            signatures = [(str(digest), base64.b64decode(bits), tuple(float(color) for color in colors))
                          for digest, bits, colors in angles_data]
            return signatures, embedding, index_version, phash, dhash, features
        return None, None, 1, None, None, {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None, 1, None, None, {}


def _tags(value: str) -> set[str]:
    return {tag.strip().casefold() for tag in (value or "").split("·") if tag.strip()}


def _compute_phash_dhash(image_path: str) -> tuple:
    """Calcula pHash y dHash de una imagen para búsqueda por hash."""
    from PIL import Image

    try:
        with Image.open(image_path) as img:
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_arr = np.array(alpha)

            # Crear máscara simple
            has_transparency = alpha_arr.min() < 250
            if has_transparency:
                mask = alpha_arr > 25
            else:
                rgb = np.array(rgba.convert("RGB"))
                corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
                bg_color = np.median(corners, axis=0)
                diff = np.abs(rgb.astype(np.int16) - bg_color.astype(np.int16))
                mask = np.any(diff > 25, axis=2)

            # Aplicar máscara
            rgb = np.array(rgba.convert("RGB"))
            masked = rgb.copy()
            masked[~mask] = 0

            # Convertir a gris
            gray = cv2.cvtColor(masked, cv2.COLOR_RGB2GRAY)

            # dHash
            dhash_img = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
            dhash_bits = dhash_img[:, 1:] > dhash_img[:, :-1]
            dhash_bytes = np.packbits(dhash_bits.reshape(-1)).tobytes()

            # pHash
            phash_img = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
            dct = cv2.dct(np.float32(phash_img))
            dct_block = dct[:8, :8]
            median = np.median(dct_block)
            phash_bits = dct_block > median
            phash_bytes = np.packbits(phash_bits.reshape(-1)).tobytes()

            return phash_bytes, dhash_bytes
    except Exception:
        return None, None


def _hamming_distance(hash1: bytes, hash2: bytes) -> int:
    """Calcula distancia Hamming entre dos hashes."""
    if not hash1 or not hash2 or len(hash1) != len(hash2):
        return 64
    return sum(bin(a ^ b).count('1') for a, b in zip(hash1, hash2))


def _enable_diagnostic_log(log_path: str = None):
    """Activa el logging de diagnóstico para visual search."""
    global _diagnostic_log_enabled, _diagnostic_log_path
    _diagnostic_log_enabled = True
    _diagnostic_log_path = log_path or "visual_search_diagnostic.log"


def _log_diagnostic(message: str):
    """Escribe mensaje al log de diagnóstico si está activado."""
    global _diagnostic_log_enabled, _diagnostic_log_path
    if _diagnostic_log_enabled and _diagnostic_log_path:
        try:
            from datetime import datetime
            with open(_diagnostic_log_path, "a", encoding="utf-8") as f:
                timestamp = datetime.now().isoformat()
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            pass


def _tag_bonus(query_tags: str, candidate_tags: str) -> float:
    """Las etiquetas afinan la búsqueda sin reemplazar la comparación visual."""
    query = _tags(query_tags)
    candidate = _tags(candidate_tags)
    if not query or not candidate:
        return 0.0
    overlap = len(query & candidate)
    return min(12.0, 12.0 * overlap / max(1, len(query)))


def visual_impact(path: str) -> float:
    """Puntaje de impacto: color, contraste y superficie visible del sticker."""
    from PIL import Image, ImageStat

    with Image.open(path) as source:
        image = source.convert("RGBA")
        alpha = image.getchannel("A").resize((48, 48))
        visible = sum(value > 20 for value in alpha.getdata()) / (48 * 48)
        canvas = Image.new("RGBA", image.size, "#111314")
        canvas.alpha_composite(image)
        rgb = canvas.convert("RGB").resize((48, 48))
        stat = ImageStat.Stat(rgb)
        contrast = sum(stat.var) / (3 * 255 * 255)
        saturation = sum(max(pixel) - min(pixel) for pixel in rgb.getdata()) / (48 * 48 * 255)
    return round((contrast * 0.48 + saturation * 0.42 + visible * 0.10) * 100, 2)


def _design_variants(path: str, ignore_background: bool):
    """Genera vistas limpias del contenido y de cada diseño grande de una imagen.

    Las líneas finas que recorren un borde y los componentes muy pequeños se
    descartan: normalmente corresponden a marcos, firmas o marcas de agua.
    """
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGBA")
    rgb = np.array(image.convert("RGB"))
    alpha = np.array(image.getchannel("A"))
    height, width = alpha.shape

    if alpha.min() < 250:
        # Las marcas de agua semitransparentes no forman parte del diseño.
        mask = alpha > 160
    elif ignore_background:
        corners = np.array([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
        background = np.median(corners, axis=0)
        mask = np.any(np.abs(rgb.astype(np.int16) - background.astype(np.int16)) > 30, axis=2)
    else:
        mask = alpha > 18

    # Una línea decorativa o marco toca los cuatro extremos y es muy fino.
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    clean_mask = np.zeros_like(mask, dtype=np.uint8)
    components = []
    total_area = max(1, int(mask.sum()))
    min_area = max(20, int(total_area * 0.004))
    for label in range(1, component_count):
        x, y, component_width, component_height, area = stats[label]
        thin = min(component_width, component_height) <= max(2, int(min(width, height) * 0.025))
        spans_edges = x == 0 and y == 0 and x + component_width >= width and y + component_height >= height
        if area < min_area or (thin and spans_edges):
            continue
        clean_mask[labels == label] = 255
        # Componentes importantes se comparan por separado para que una hoja
        # con varios stickers pueda encontrar cualquiera de ellos.
        if area >= total_area * 0.05:
            components.append((x, y, component_width, component_height))

    if not np.any(clean_mask):
        clean_mask = (mask.astype(np.uint8) * 255)
    bbox = Image.fromarray(clean_mask, mode="L").getbbox()
    if not bbox:
        return [image]

    def make_variant(box):
        cropped = image.crop(box)
        cropped.putalpha(Image.fromarray(clean_mask, mode="L").crop(box))
        return cropped

    variants = [make_variant(bbox)]
    padding = max(2, int(min(width, height) * 0.02))
    for index, (x, y, component_width, component_height) in enumerate(components):
        box = (max(0, x - padding), max(0, y - padding), min(width, x + component_width + padding), min(height, y + component_height + padding))
        variants.append(make_variant(box))
    return variants


def _precise_similarity(query_path: str, candidate_path: str, ignore_background: bool = True, search_duplicates_only: bool = False, max_distance: float = 4.0, _rotation_aware: bool = True, _candidate_rotation: int = 0, _prepared_query_variants=None):
    """Realiza la comparación visual fina de la segunda etapa.

    OPTIMIZACIÓN: Cuando search_duplicates_only=True, salta la detección de rotación
    y variantes de diseño para acelerar la búsqueda de duplicados exactos.
    """
    from PIL import Image
    err_val = 0.0 if search_duplicates_only else (0.0, 0.0, 0.0, 64.0)

    # OPTIMIZACIÓN: Para búsqueda de duplicados, saltar rotación y variantes
    if search_duplicates_only:
        _rotation_aware = True

    def principal_orientation(image):
        """Estimate a continuous orientation from the visible silhouette."""
        rgba = image.convert("RGBA")
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
        y_points, x_points = np.nonzero(alpha > 18)
        if x_points.size < 8:
            return None
        points = np.column_stack((x_points, y_points)).astype(np.float64)
        points -= points.mean(axis=0, keepdims=True)
        covariance = np.cov(points, rowvar=False)
        values, vectors = np.linalg.eigh(covariance)
        vector = vectors[:, int(np.argmax(values))]
        return float(np.degrees(np.arctan2(vector[1], vector[0])))

    # Primero aislamos los diseños para que un marco, una marca de agua o una
    # composición con varios stickers no afecte la comparación.
    if _rotation_aware:
        query_variants = _prepared_query_variants or _design_variants(query_path, ignore_background)
        candidate_variants = _design_variants(candidate_path, ignore_background)
            # La orientación no debe ocultar el mismo diseño. Evaluamos ocho
            # ángulos de cada diseño aislado del candidato.
        alternatives = []
        for q_image in query_variants:
            for c_image in candidate_variants:
                q_angle = principal_orientation(q_image)
                c_angle = principal_orientation(c_image)
                estimated_angles = set()
                if q_angle is not None and c_angle is not None:
                    estimated = c_angle - q_angle
                    estimated_angles.update({
                        estimated % 360,
                        (-estimated) % 360,
                        (estimated + 180) % 360,
                        (-estimated + 180) % 360,
                    })
                estimated_results = [
                    _precise_similarity(
                        q_image, c_image, ignore_background, search_duplicates_only,
                        max_distance, False, angle,
                    )
                    for angle in estimated_angles
                ]
                alternatives.extend(estimated_results)
                if search_duplicates_only:
                    aligned = max(estimated_results, default=0.0) >= 98.0
                else:
                    aligned = any(
                        result[0] >= 0.95 and result[1] >= 0.90 and result[2] >= 0.90
                        for result in estimated_results
                    )
                if aligned:
                    continue
                alternatives.extend(
                    _precise_similarity(
                        q_image, c_image, ignore_background, search_duplicates_only,
                        max_distance, False, angle,
                    )
                    for angle in range(0, 360, 45)
                )
        if search_duplicates_only:
            return max(alternatives, default=0.0)
        return max(alternatives, key=lambda result: result[0] * 0.40 + result[1] * 0.25 + result[2] * 0.35, default=err_val)

    try:
        def load_rgba(source):
            if isinstance(source, Image.Image):
                return source.copy().convert("RGBA")
            with Image.open(source) as opened:
                return opened.convert("RGBA")

        q_rgba = load_rgba(query_path)
        c_rgba = load_rgba(candidate_path)
        if _candidate_rotation:
            c_rgba = c_rgba.rotate(_candidate_rotation, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0, 0))
    except Exception:
        return err_val

    def prepare_and_crop(img_rgba, ignore_bg):
        alpha = img_rgba.getchannel("A")
        alpha_mask = alpha.point(lambda v: 255 if v > 18 else 0)
        bbox = alpha_mask.getbbox()

        is_transparent = alpha.getextrema()[0] < 250

        # Para imágenes sin canal de transparencia, estimamos fondo si es uniforme
        if not is_transparent and ignore_bg:
            sample_img = img_rgba.resize((128, 128), Image.Resampling.BOX)
            pixels = np.array(sample_img.convert("RGB"))
            corners = [pixels[0, 0], pixels[0, 127], pixels[127, 0], pixels[127, 127]]
            bg_color = np.median(corners, axis=0)

            full_pixels = np.array(img_rgba.convert("RGB"))
            diff = np.abs(full_pixels - bg_color)
            foreground = np.any(diff > 30, axis=2)

            fg_mask = Image.fromarray((foreground.astype(np.uint8) * 255), mode="L")
            bbox = fg_mask.getbbox()
            if bbox:
                cropped = img_rgba.crop(bbox)
                cropped_fg_mask = fg_mask.crop(bbox)
                res_img = cropped.copy()
                res_img.putalpha(cropped_fg_mask)
                return res_img, cropped_fg_mask

        if bbox:
            cropped = img_rgba.crop(bbox)
            cropped_mask = alpha_mask.crop(bbox)
            return cropped, cropped_mask

        return img_rgba, alpha_mask

    try:
        q_cropped, q_mask = prepare_and_crop(q_rgba, ignore_background)
        c_cropped, c_mask = prepare_and_crop(c_rgba, ignore_background)

        # Normalizamos tamaño a 64x64
        q_norm = q_cropped.resize((64, 64), Image.Resampling.LANCZOS)
        c_norm = c_cropped.resize((64, 64), Image.Resampling.LANCZOS)

        q_mask_norm = q_mask.resize((64, 64), Image.Resampling.NEAREST)
        c_mask_norm = c_mask.resize((64, 64), Image.Resampling.NEAREST)

        q_mask_arr = np.array(q_mask_norm) > 18
        c_mask_arr = np.array(c_mask_norm) > 18

        # 1. Contorno: IoU de la máscara visible
        intersection = np.logical_and(q_mask_arr, c_mask_arr)
        union = np.logical_or(q_mask_arr, c_mask_arr)
        sum_union = np.sum(union)
        shape_sim = np.sum(intersection) / sum_union if sum_union > 0 else 1.0

        # 2. Color comparison using HSV for better hue detection
        q_rgb = np.array(q_norm.convert("RGB"))
        c_rgb = np.array(c_norm.convert("RGB"))

        # Initialize color_sim
        color_sim = 0.0

        # Sólo comparamos colores en la intersección de píxeles visibles
        intersect_indices = np.where(intersection)
        if len(intersect_indices[0]) > 0:
            q_pixels = q_rgb[intersect_indices]
            c_pixels = c_rgb[intersect_indices]

            # Convert to HSV for better hue detection
            # Need uint8 for OpenCV HSV conversion
            q_pixels_uint8 = q_pixels.astype(np.uint8)
            c_pixels_uint8 = c_pixels.astype(np.uint8)

            q_hsv = cv2.cvtColor(q_pixels_uint8.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)
            c_hsv = cv2.cvtColor(c_pixels_uint8.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV).reshape(-1, 3)

            # Hue difference (circular, 0-180 in OpenCV)
            hue_diff = np.abs(q_hsv[:, 0].astype(np.float32) - c_hsv[:, 0].astype(np.float32))
            hue_diff = np.minimum(hue_diff, 180 - hue_diff)  # Handle circular nature
            mean_hue_diff = np.mean(hue_diff)
            hue_sim = max(0.0, 1.0 - mean_hue_diff / 45.0)  # Normalize: 0° diff = 1.0, 45° diff = 0.0

            # Saturation and value differences
            sat_diff = np.abs(q_hsv[:, 1].astype(np.float32) - c_hsv[:, 1].astype(np.float32))
            val_diff = np.abs(q_hsv[:, 2].astype(np.float32) - c_hsv[:, 2].astype(np.float32))
            sat_sim = 1.0 - np.mean(sat_diff) / 255.0
            val_sim = 1.0 - np.mean(val_diff) / 255.0

            # Combined color similarity with emphasis on hue
            color_sim = (hue_sim * 0.60 + sat_sim * 0.20 + val_sim * 0.20)
            color_sim = max(0.0, min(1.0, color_sim))

            _log_diagnostic(f"Color debug: hue_diff={mean_hue_diff:.1f}, hue_sim={hue_sim:.2f}, sat_sim={sat_sim:.2f}, val_sim={val_sim:.2f}, color_sim={color_sim:.2f}")

            # Update the color_sim variable for use in reason strings
            # This ensures the HSV-based value is used throughout
        else:
            if not np.any(q_mask_arr) and not np.any(c_mask_arr):
                color_sim = 1.0
            else:
                color_sim = 0.0

        # 3. Estructura del diseño (pHash / dHash)
        # Normalizamos el fondo de ambos a negro puro
        q_masked = q_rgb.copy()
        q_masked[~q_mask_arr] = 0
        c_masked = c_rgb.copy()
        c_masked[~c_mask_arr] = 0

        q_gray = cv2.cvtColor(q_masked, cv2.COLOR_RGB2GRAY)
        c_gray = cv2.cvtColor(c_masked, cv2.COLOR_RGB2GRAY)

        # dHash
        q_dhash_img = cv2.resize(q_gray, (9, 8), interpolation=cv2.INTER_AREA)
        c_dhash_img = cv2.resize(c_gray, (9, 8), interpolation=cv2.INTER_AREA)
        q_dhash_bits = q_dhash_img[:, 1:] > q_dhash_img[:, :-1]
        c_dhash_bits = c_dhash_img[:, 1:] > c_dhash_img[:, :-1]
        dhash_dist = np.sum(q_dhash_bits != c_dhash_bits)
        dhash_sim = 1.0 - (dhash_dist / 64.0)

        # pHash
        q_phash_img = cv2.resize(q_gray, (32, 32), interpolation=cv2.INTER_AREA)
        c_phash_img = cv2.resize(c_gray, (32, 32), interpolation=cv2.INTER_AREA)
        q_dct = cv2.dct(np.float32(q_phash_img))
        c_dct = cv2.dct(np.float32(c_phash_img))
        q_dct_block = q_dct[:8, :8]
        c_dct_block = c_dct[:8, :8]
        q_median = np.median(q_dct_block)
        c_median = np.median(c_dct_block)
        q_phash_bits = q_dct_block > q_median
        c_phash_bits = c_dct_block > c_median
        phash_dist = np.sum(q_phash_bits != c_phash_bits)
        phash_sim = 1.0 - (phash_dist / 64.0)

        combined_dist = (dhash_dist + phash_dist) / 2.0
        hash_sim = (dhash_sim + phash_sim) / 2.0

        if search_duplicates_only:
            if combined_dist <= max_distance:
                # Retorna un porcentaje basado en la distancia
                return round((1.0 - combined_dist / 64.0) * 100, 1)
            else:
                return 0.0

        return shape_sim, color_sim, hash_sim, combined_dist

    except Exception:
        return err_val


def _signature_arrays(signatures):
    if not signatures:
        return None
    byte_length = len(signatures[0][1])
    if not byte_length or any(len(signature[1]) != byte_length for signature in signatures):
        return None
    bits = np.frombuffer(b"".join(signature[1] for signature in signatures), dtype=np.uint8)
    bits = bits.reshape(len(signatures), byte_length)
    colors = np.asarray([signature[2][:3] for signature in signatures], dtype=np.float32)
    return bits, colors


def _signature_similarity(query_signatures, candidate_signatures, prepared_query=None) -> float:
    """Estimación rápida de color y diseño, invariante a la rotación."""
    if not query_signatures or not candidate_signatures:
        return 0.0
    query_arrays = prepared_query or _signature_arrays(query_signatures)
    candidate_arrays = _signature_arrays(candidate_signatures)
    if query_arrays is None or candidate_arrays is None:
        return 0.0
    query_bits, query_colors = query_arrays
    candidate_bits, candidate_colors = candidate_arrays
    if query_bits.shape[1] != candidate_bits.shape[1]:
        return 0.0

    xor = np.bitwise_xor(query_bits[:, None, :], candidate_bits[None, :, :])
    different_bits = _BIT_COUNTS[xor].sum(axis=2, dtype=np.int32)
    design = 1.0 - different_bits / float(query_bits.shape[1] * 8)
    color_distance = np.abs(
        query_colors[:, None, :] - candidate_colors[None, :, :]
    ).sum(axis=2) / (3.0 * 255.0)
    color = np.maximum(0.0, 1.0 - color_distance)
    return float(np.max(design * 0.60 + color * 0.40))


def _dominant_color_channel(signatures) -> int | None:
    """Devuelve R/G/B solo cuando el diseño tiene un color claramente dominante.

    Los diseños multicolor, grises o muy claros no se filtran por color: así
    evitamos perder coincidencias legítimas. En cambio, un sticker netamente
    verde puede descartar temprano los candidatos rojos y azules.
    """
    if not signatures:
        return None
    means = [sum(signature[2][index] for signature in signatures) / len(signatures) for index in range(3)]
    ordered = sorted(means, reverse=True)
    if ordered[0] - ordered[1] < 28 or ordered[0] - ordered[2] < 40:
        return None
    return max(range(3), key=means.__getitem__)


def _indexed_feature_similarity(query: dict, candidate: dict) -> tuple[float, float, float, float]:
    """Color, silueta, geometría y texto sin abrir nuevamente las imágenes."""
    query_hist = np.asarray(query.get("color_hist") or [], dtype=np.float32)
    candidate_hist = np.asarray(candidate.get("color_hist") or [], dtype=np.float32)
    if query_hist.size == candidate_hist.size and query_hist.size:
        color = float(np.minimum(query_hist, candidate_hist).sum())
    else:
        color = 0.5

    query_radial = np.asarray(query.get("radial") or [], dtype=np.float32)
    candidate_radial = np.asarray(candidate.get("radial") or [], dtype=np.float32)
    if query_radial.size == candidate_radial.size and query_radial.size:
        silhouette = float(np.minimum(query_radial, candidate_radial).sum())
    else:
        query_hu = np.asarray(query.get("hu") or [], dtype=np.float32)
        candidate_hu = np.asarray(candidate.get("hu") or [], dtype=np.float32)
        silhouette = (
            float(np.exp(-np.mean(np.abs(query_hu - candidate_hu)) / 2.5))
            if query_hu.size == candidate_hu.size and query_hu.size else 0.5
        )

    query_aspect = float(query.get("aspect") or 1.0)
    candidate_aspect = float(candidate.get("aspect") or 1.0)
    # La búsqueda debe ser invariante a una rotación de 90/180 grados: usar
    # siempre lado mayor/lado menor evita penalizar un mismo diseño vertical.
    query_shape_ratio = max(query_aspect, 1.0 / max(query_aspect, 1e-6))
    candidate_shape_ratio = max(candidate_aspect, 1.0 / max(candidate_aspect, 1e-6))
    aspect_delta = abs(query_shape_ratio - candidate_shape_ratio)

    occupancy_delta = abs(float(query.get("occupancy") or 0.0) - float(candidate.get("occupancy") or 0.0))
    # Las rotaciones con expansión de lienzo cambian ligeramente la caja
    # ocupada; no deben convertir una coincidencia en un descarte.
    geometry = max(0.0, 1.0 - aspect_delta * 0.4 - occupancy_delta * 0.5)

    query_words = set(str(query.get("text") or "").split())
    candidate_words = set(str(candidate.get("text") or "").split())
    text = len(query_words & candidate_words) / len(query_words) if query_words else 1.0
    return color, silhouette, geometry, text


def _dominant_hue(features: dict) -> tuple[int | None, float]:
    histogram = list(features.get("color_hist") or [])
    if not histogram:
        return None, 0.0
    strongest = max(range(len(histogram)), key=histogram.__getitem__)
    concentration = float(histogram[strongest])
    return (strongest, concentration) if concentration >= 0.58 else (None, concentration)


def _hue_distance(left: int, right: int, bins: int = 12) -> int:
    distance = abs(left - right)
    return min(distance, bins - distance)


def find_similar(
    query_path: str,
    candidates: list[dict],
    progress=None,
    limit: int = 1000,
    cancelled=None,
    signature_ready=None,
    minimum_score: float = 90.0,
    query_tags: str = "",
    mode: str = "estricto",
    search_duplicates_only: bool = False,
    ignore_background: bool = True,
    max_distance: float = 4.0,
    time_budget_seconds: float | None = None,
    timed_out=None,
    details_ready=None,
) -> list[tuple[str, float]] | None:
    """Devuelve coincidencias visuales filtradas y validadas en dos etapas.

    Mejoras implementadas:
    - Unión de candidatos desde múltiples fuentes (embedding, pHash, dHash, nombre)
    - Puntuación combinada sin umbrales duros que eliminen coincidencias válidas
    - Fallback visual cuando ningún resultado supera el mínimo
    - Logging diagnóstico de los mejores candidatos
    - Manejo simétrico de ignorar fondo/transparencia
    """
    progress = progress or (lambda _done, _total: None)
    cancelled = cancelled or (lambda: False)
    signature_ready = signature_ready or (lambda _rows: None)
    timed_out = timed_out or (lambda: None)
    details_ready = details_ready or (lambda _details: None)
    deadline = time.perf_counter() + max(0.1, float(time_budget_seconds)) if time_budget_seconds else None

    def out_of_time() -> bool:
        return deadline is not None and time.perf_counter() >= deadline

    _log_diagnostic(f"=== INICIO BÚSQUEDA VISUAL ===")
    _log_diagnostic(f"Query: {query_path}")
    _log_diagnostic(f"Modo: {mode}, Umbral: {minimum_score}%, Ignorar fondo: {ignore_background}")
    _log_diagnostic(f"Candidatos totales: {len(candidates)}")

    # 1. Obtener embedding visual y hashes de la query
    query_embedding = get_resnet_embedding(query_path)
    query_embedding_np = np.array(query_embedding)
    query_signatures = signature_variants(query_path)
    prepared_query_signatures = _signature_arrays(query_signatures)
    query_features = visual_index_features(query_path, query_tags)
    dominant_query_hue, _query_hue_strength = _dominant_hue(query_features)
    query_phash, query_dhash = _compute_phash_dhash(query_path)
    embedding_available = bool(np.linalg.norm(query_embedding_np) > 1e-8)

    total = len(candidates)
    updates = []

    # Cache para evitar recalcular hashes en la misma búsqueda

    # Diccionarios para diferentes fuentes de candidatos
    embedding_candidates = {}  # path -> (item, score)
    phash_candidates = {}      # path -> (item, score)
    dhash_candidates = {}      # path -> (item, score)
    name_candidates = {}       # path -> (item, score)
    color_discarded = 0
    unindexed_discarded = 0

    _log_diagnostic(f"Iniciando comparación global de hashes contra {total} candidatos")

    # Procesar candidatos para Stage 1
    for index, item in enumerate(candidates, start=1):
        if cancelled():
            return None
        if out_of_time():
            _log_diagnostic(f"Presupuesto de tiempo agotado durante etapa 1: {index - 1} de {total} candidatos.")
            timed_out()
            break

        signature = None
        embedding = None
        item_phash = None
        item_dhash = None
        item_features = {}
        sig_text = item.get("visual_signature", "")
        modified_matches = float(item.get("visual_signature_modified", -1)) == float(item.get("modified", -2))
        item_path = item["path"]

        try:
            if sig_text.startswith('{"version":4') and modified_matches:
                signature, embedding, index_version, item_phash, item_dhash, item_features = signature_and_embedding_from_text(sig_text)
                # Si la versión del índice no coincide, recalcular
                if index_version != VISUAL_INDEX_VERSION:
                    signature = None
                    embedding = None
                    item_phash = None
                    item_dhash = None
            elif sig_text.startswith('{"version":3') and modified_matches:
                signature, embedding, index_version, item_phash, item_dhash, item_features = signature_and_embedding_from_text(sig_text)
                # Si la versión del índice no coincide, recalcular
                if index_version != VISUAL_INDEX_VERSION:
                    signature = None
                    embedding = None
            elif sig_text.startswith('{"version":2') and modified_matches:
                unindexed_discarded += 1
                continue
                signature = signature_from_text(sig_text)
                if signature:
                    embedding = get_resnet_embedding(item["path"])
                    updates.append((signature_to_text(signature, embedding), float(item.get("modified", -1)), item["path"]))
                    updates.pop()

            if signature is None:
                unindexed_discarded += 1
                continue
                signature = signature_variants(item["path"])
                embedding = get_resnet_embedding(item["path"], use_unified_normalize=True)
                # Calcular hashes para migración
                item_phash, item_dhash = _compute_phash_dhash(item["path"])
                updates.append((signature_to_text(signature, embedding, item_phash, item_dhash), float(item.get("modified", -1)), item["path"]))
            if not item_phash or not item_dhash or not item_features:
                unindexed_discarded += 1
                continue
        except Exception:
            continue

        # Filtro temprano: si la consulta es claramente de un color (por
        # ejemplo, verde), no se invierte tiempo en embeddings, hashes ni
        # comparación precisa de diseños con otro color dominante.
        candidate_hue, _candidate_hue_strength = _dominant_hue(item_features)
        if dominant_query_hue is not None and candidate_hue is not None:
            if _hue_distance(dominant_query_hue, candidate_hue) > 1:
                color_discarded += 1
                continue

        if updates and (len(updates) >= 50 or index == total):
            signature_ready(updates)
            updates = []

        if index == total or index % 100 == 0:
            progress(int(index * 0.3 / total * 100), total)

        if embedding is not None:
            emb_np = np.array(embedding)
            emb_sim = float(np.dot(query_embedding_np, emb_np)) if embedding_available else 0.0
            signature_sim = _signature_similarity(
                query_signatures, signature, prepared_query_signatures
            )
            indexed_color, silhouette, geometry, text_sim = _indexed_feature_similarity(query_features, item_features)
            retrieval_score = (
                emb_sim * 0.38 + signature_sim * 0.24 + silhouette * 0.18
                + indexed_color * 0.12 + geometry * 0.08
                if embedding_available
                else signature_sim * 0.42 + silhouette * 0.30 + indexed_color * 0.18 + geometry * 0.10
            )
            item = dict(item)
            item["_stage1_metrics"] = {
                "embedding": emb_sim,
                "signature": signature_sim,
                "color_index": indexed_color,
                "silhouette_index": silhouette,
                "geometry_index": geometry,
                "text_index": text_sim,
            }

            # Candidatos por embedding (top 150)
            embedding_candidates[item_path] = (item, retrieval_score)

        # Candidatos por pHash - COMPARACIÓN GLOBAL contra todo el índice
        if query_phash:
            try:
                # Usar hashes pre-calculados del índice si están disponibles
                if item_phash:
                    phash_dist = _hamming_distance(query_phash, item_phash)
                    phash_sim = 1.0 - (phash_dist / 64.0)
                    if phash_sim > 0.40:  # Umbral muy relajado para pHash para incluir más candidatos
                        phash_candidates[item_path] = (item, phash_sim)
            except Exception:
                pass

        # Candidatos por dHash - COMPARACIÓN GLOBAL contra todo el índice
        if query_dhash:
            try:
                # Usar hashes pre-calculados del índice si están disponibles
                if item_dhash:
                    dhash_dist = _hamming_distance(query_dhash, item_dhash)
                    dhash_sim = 1.0 - (dhash_dist / 64.0)
                    if dhash_sim > 0.40:  # Umbral muy relajado para dHash para incluir más candidatos
                        dhash_candidates[item_path] = (item, dhash_sim)
            except Exception:
                pass

        # Candidatos por nombre/archivo (coincidencia parcial)
        query_name = Path(query_path).stem.lower()
        cand_name = Path(item_path).stem.lower()
        if query_name and cand_name and (query_name in cand_name or cand_name in query_name):
            name_candidates[item_path] = (item, 0.85)  # Alta prioridad por nombre

    # Crear unión de candidatos eliminando duplicados
    all_candidates = {}
    for path, (item, score) in embedding_candidates.items():
        all_candidates[path] = (item, score, "embedding")
    for path, (item, score) in phash_candidates.items():
        if path in all_candidates:
            # Mejorar score si ya existe
            existing_item, existing_score, source = all_candidates[path]
            combined_score = max(existing_score, score)
            all_candidates[path] = (existing_item, combined_score, f"{source}+phash")
        else:
            all_candidates[path] = (item, score, "phash")
    for path, (item, score) in dhash_candidates.items():
        if path in all_candidates:
            existing_item, existing_score, source = all_candidates[path]
            combined_score = max(existing_score, score)
            all_candidates[path] = (existing_item, combined_score, f"{source}+dhash")
        else:
            all_candidates[path] = (item, score, "dhash")
    for path, (item, score) in name_candidates.items():
        if path in all_candidates:
            existing_item, existing_score, source = all_candidates[path]
            combined_score = max(existing_score, score)
            all_candidates[path] = (existing_item, combined_score, f"{source}+nombre")
        else:
            all_candidates[path] = (item, score, "nombre")

    _log_diagnostic(f"Candidatos: {len(all_candidates)}; color descartó {color_discarded}; sin índice completo {unindexed_discarded}")

    # Eliminar filtrado por umbral - procesar TODOS los candidatos del banco
    stage1_filtered = [(item, score, source) for path, (item, score, source) in all_candidates.items()]

    # Ordenar todos los candidatos por score
    stage1_sorted = sorted(stage1_filtered, key=lambda x: x[1], reverse=True)

    _log_diagnostic(f"Candidatos Stage 2: {len(stage1_sorted)} de {len(all_candidates)} totales (sin filtrar)")

    # Stage 2: Validación precisa
    matches = []
    all_results = []  # Para fallback y diagnóstico
    num_stage2 = len(stage1_sorted)

    try:
        prepared_query_variants = _design_variants(query_path, ignore_background)
    except Exception:
        prepared_query_variants = None

    for i, (item, retrieval_score, source) in enumerate(stage1_sorted, start=1):
        if cancelled():
            return None
        if out_of_time():
            _log_diagnostic(f"Presupuesto de tiempo agotado durante etapa 2: {i - 1} de {num_stage2} candidatos.")
            timed_out()
            break

        res = _precise_similarity(
            query_path, item["path"], ignore_background, search_duplicates_only, max_distance,
            _prepared_query_variants=prepared_query_variants,
        )

        if search_duplicates_only:
            score = res
            final_score = score
            accepted_by = "final_score"
            reason = "duplicates_only"
        else:
            shape_sim, color_sim, hash_sim, combined_dist = res

            # Fórmula de puntuación combinada sin umbrales duros
            # La puntuación mostrada es independiente del criterio de aceptación
            if mode == "relacionado":
                # Relacionado: prioriza similitud semántica y visual general
                score = (retrieval_score * 0.50 + shape_sim * 0.25 + color_sim * 0.15 + hash_sim * 0.10) * 100
                score = min(100.0, score + _tag_bonus(query_tags, item.get("tags", "")))
                accepted_by = "final_score"
                reason = f"relacionado (emb:{retrieval_score:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f}, hash:{hash_sim:.2f})"
            elif mode == "estricto":
                # Estricto: misma composición, tolerando fondo, escala, márgenes
                # Separar puntuación mostrada de criterio de aceptación
                # Umbrales ajustados: muy relajar forma (fondo blanco), muy estrictificar color (evitar hue shift)
                hash_strong = (hash_sim > 0.80)  # Hash fuerte
                hash_very_strong = (hash_sim > 0.92)  # Hash extremadamente fuerte
                shape_acceptable = shape_sim > 0.25  # Muy relajado para tolerar márgenes/fondo blanco
                shape_good = shape_sim > 0.50
                shape_very_good = shape_sim > 0.70
                color_acceptable = color_sim > 0.55  # Para final_score (tolera fondo blanco)
                color_good = color_sim > 0.75  # Para strong_hash (rechaza hue shift, variant H tiene 0.74)
                color_excellent = color_sim > 0.85  # Para near_duplicate

                # Puntuación mostrada (siempre calculada)
                if hash_very_strong and color_excellent:
                    score = (hash_sim * 0.50 + shape_sim * 0.30 + color_sim * 0.20) * 100
                elif shape_very_good and color_acceptable:
                    score = (shape_sim * 0.40 + hash_sim * 0.35 + color_sim * 0.20 + retrieval_score * 0.05) * 100
                else:
                    score = (shape_sim * 0.35 + hash_sim * 0.35 + color_sim * 0.20 + retrieval_score * 0.10) * 100

                # Criterio de aceptación (separado de puntuación)
                # Color muy bueno estricto para evitar falsos positivos por hue shift
                if hash_very_strong and shape_good and color_excellent:
                    # Hash extremadamente fuerte + forma buena + color excelente = near_duplicate
                    accepted_by = "near_duplicate"
                    reason = f"estricto_near_duplicate (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                elif hash_strong and shape_acceptable and color_good:
                    # Hash fuerte + forma aceptable + color muy bueno = strong_hash (rechaza hue shift)
                    accepted_by = "strong_hash"
                    reason = f"estricto_strong_hash (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                elif shape_acceptable and color_acceptable and hash_sim > 0.55:
                    # Forma aceptable + color aceptable + hash decente = final_score (tolera fondo blanco)
                    # Si hash es muy alto (>0.90), requerir color más alto para rechazar hue shift
                    if hash_sim > 0.90 and color_sim < 0.75:
                        # Hash muy alto pero color moderado = posible hue shift, rechazar
                        accepted_by = None
                        reason = f"estricto_rejected_hue_shift (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                    else:
                        accepted_by = "final_score"
                        reason = f"estricto_final_score (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                else:
                    # No cumple criterios estrictos
                    accepted_by = None
                    reason = f"estricto_rejected (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"

            elif mode == "identico":
                # Idéntico: no acepta variantes de color, forma o recorte.
                # Las tres señales deben ser excepcionalmente cercanas.
                score = (shape_sim * 0.40 + hash_sim * 0.40 + color_sim * 0.20) * 100
                indexed = item.get("_stage1_metrics") or {}
                text_required = bool(str(query_features.get("text") or "").split())
                text_ok = not text_required or float(indexed.get("text_index", 0.0)) >= 0.80
                indexed_ok = (
                    float(indexed.get("silhouette_index", 0.0)) >= 0.82
                    and float(indexed.get("color_index", 0.0)) >= 0.84
                    and float(indexed.get("geometry_index", 0.0)) >= 0.88
                )
                if shape_sim >= 0.93 and hash_sim >= 0.96 and color_sim >= 0.92 and indexed_ok and text_ok:
                    accepted_by = "identico"
                    reason = f"identico (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                else:
                    accepted_by = None
                    reason = f"identico_rejected (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
            elif mode == "casi_exacto":
                # Casi exacto: exige hashes y geometría muy cercanos
                shape_excellent = shape_sim > 0.85
                hash_excellent = hash_sim > 0.90
                color_excellent = color_sim > 0.80

                if shape_excellent and hash_excellent and color_excellent:
                    score = (shape_sim * 0.40 + hash_sim * 0.40 + color_sim * 0.20) * 100
                    accepted_by = "near_duplicate"
                    reason = f"casi_exacto_near_duplicate (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                elif shape_sim > 0.80 and hash_sim > 0.85 and color_sim > 0.75:
                    score = (shape_sim * 0.40 + hash_sim * 0.40 + color_sim * 0.20) * 100
                    accepted_by = "final_score"
                    reason = f"casi_exacto_final_score (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
                else:
                    score = (shape_sim * 0.35 + hash_sim * 0.35 + color_sim * 0.20 + retrieval_score * 0.10) * 100 * 0.5
                    accepted_by = None
                    reason = f"casi_exacto_rejected (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"
            else:
                score = (shape_sim * 0.50 + color_sim * 0.30 + hash_sim * 0.20) * 100
                accepted_by = "final_score"
                reason = f"default (hash:{hash_sim:.2f}, shape:{shape_sim:.2f}, color:{color_sim:.2f})"

            final_score = round(min(100.0, max(0.0, score)), 1)

        # Guardar todos los resultados para diagnóstico y fallback
        all_results.append({
            "path": item["path"],
            "score": final_score,
            "source": source,
            "reason": reason,
            "accepted_by": accepted_by,
            "shape_sim": shape_sim if not search_duplicates_only else None,
            "color_sim": color_sim if not search_duplicates_only else None,
            "hash_sim": hash_sim if not search_duplicates_only else None,
            "retrieval_score": retrieval_score,
            "indexed": item.get("_stage1_metrics") or {},
        })

        # Eliminar filtrado por umbral - aceptar todos los resultados para mostrar los mejores
        # Agregar todos los resultados, no solo los que superan el umbral
        matches.append((item["path"], final_score))

        if i == num_stage2 or i % 10 == 0:
            progress(int(30 + (i / num_stage2) * 70), total)

    # Logging diagnóstico de los mejores 20 candidatos
    all_results_sorted = sorted(all_results, key=lambda x: x["score"], reverse=True)
    details_ready({result["path"]: result for result in all_results_sorted})
    _log_diagnostic("=== TOP 20 CANDIDATOS ===")
    for i, result in enumerate(all_results_sorted[:20], 1):
        accepted_status = "ACCEPTED" if result.get("accepted_by") else "REJECTED"
        _log_diagnostic(f"{i}. {result['path'][:60]}... Score: {result['score']}% Fuente: {result['source']} Razón: {result['reason']} Status: {accepted_status}")
        if result['shape_sim'] is not None:
            _log_diagnostic(f"   Métricas: shape={result['shape_sim']:.3f}, color={result['color_sim']:.3f}, hash={result['hash_sim']:.3f}, retrieval={result['retrieval_score']:.3f}")

    # Ordenar resultados que superan el umbral
    matches = sorted(matches, key=lambda x: x[1], reverse=True)

    _log_diagnostic(f"Resultados sobre umbral: {len(matches)}")

    # Respetar el umbral solicitado: devolver candidatos débiles aquí hacía
    # que un diseño distinto (por ejemplo, un círculo con una cruz) apareciera
    # como coincidencia casi exacta solo por compartir color.
    qualified = [
        (result["path"], result["score"])
        for result in all_results_sorted
        if result.get("accepted_by") and result["score"] >= minimum_score
    ]
    if qualified:
        _log_diagnostic(f"Retornando {len(qualified[:limit])} resultados sobre umbral")
        return qualified[:limit]
    return []

    _log_diagnostic(f"=== FIN BÚSQUEDA VISUAL ===")
    return matches[:limit]

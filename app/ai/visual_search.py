"""Búsqueda visual avanzada en dos etapas para encontrar stickers iguales o muy parecidos."""

import base64
import json
from hashlib import sha256
from pathlib import Path
import numpy as np
import cv2

# Variable global para guardar de forma diferida el modelo de embedding
_resnet_model = None
_resnet_transforms = None


def get_resnet_embedding(image_path: str) -> list[float]:
    """Obtiene un vector de embedding visual de 512 dimensiones usando ResNet-18."""
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
    grayscale = list(image.convert("L").getdata())
    average = sum(grayscale) / len(grayscale)
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
    return [_signature_for_image(original.rotate(angle, expand=True)) for angle in (0, 90, 180, 270)]


def signature_to_text(signatures, embedding=None) -> str:
    """Formato corto para persistir la huella e incluye el embedding visual en versión 3."""
    if signatures and isinstance(signatures[0], str):
        signatures = [signatures]
    encoded = [(digest, base64.b64encode(bits).decode("ascii"), colors) for digest, bits, colors in signatures]
    data = {"version": 3, "angles": encoded}
    if embedding is not None:
        data["embedding"] = embedding
    return json.dumps(data, separators=(",", ":"))


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
    """Devuelve la huella visual original y el embedding de versión 3."""
    try:
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            angles_data = decoded.get("angles", [])
            embedding = decoded.get("embedding", None)
            angles = [(str(digest), base64.b64decode(bits), tuple(float(color) for color in colors)) for digest, bits, colors in angles_data]
            return angles, embedding
        return None, None
    except Exception:
        return None, None


def _tags(value: str) -> set[str]:
    return {tag.strip().casefold() for tag in (value or "").split("·") if tag.strip()}


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


def _precise_similarity(query_path: str, candidate_path: str, ignore_background: bool = True, search_duplicates_only: bool = False, max_distance: float = 4.0):
    """Realiza la comparación visual fina de la segunda etapa."""
    from PIL import Image
    err_val = 0.0 if search_duplicates_only else (0.0, 0.0, 0.0, 64.0)

    try:
        with Image.open(query_path) as q_img, Image.open(candidate_path) as c_img:
            q_rgba = q_img.convert("RGBA")
            c_rgba = c_img.convert("RGBA")
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

        # 2. Color comparison
        q_rgb = np.array(q_norm.convert("RGB"))
        c_rgb = np.array(c_norm.convert("RGB"))

        # Sólo comparamos colores en la intersección de píxeles visibles
        intersect_indices = np.where(intersection)
        if len(intersect_indices[0]) > 0:
            q_pixels = q_rgb[intersect_indices]
            c_pixels = c_rgb[intersect_indices]
            diff = np.abs(q_pixels.astype(np.float32) - c_pixels.astype(np.float32))
            mean_diff = np.mean(diff)
            color_sim = max(0.0, 1.0 - mean_diff / 255.0)
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


def find_similar(
    query_path: str,
    candidates: list[dict],
    progress=None,
    limit: int = 50,
    cancelled=None,
    signature_ready=None,
    minimum_score: float = 90.0,
    query_tags: str = "",
    mode: str = "estricto",
    search_duplicates_only: bool = False,
    ignore_background: bool = True,
    max_distance: float = 4.0
) -> list[tuple[str, float]] | None:
    """Devuelve coincidencias visuales filtradas y validadas en dos etapas."""
    progress = progress or (lambda _done, _total: None)
    cancelled = cancelled or (lambda: False)
    signature_ready = signature_ready or (lambda _rows: None)

    # 1. Obtener embedding visual de la query
    query_embedding = get_resnet_embedding(query_path)
    query_embedding_np = np.array(query_embedding)

    total = len(candidates)
    updates = []
    stage1_candidates = []

    # Procesar candidatos para Stage 1
    for index, item in enumerate(candidates, start=1):
        if cancelled():
            return None

        signature = None
        embedding = None
        sig_text = item.get("visual_signature", "")
        modified_matches = float(item.get("visual_signature_modified", -1)) == float(item.get("modified", -2))

        try:
            if sig_text.startswith('{"version":3') and modified_matches:
                signature, embedding = signature_and_embedding_from_text(sig_text)
            elif sig_text.startswith('{"version":2') and modified_matches:
                signature = signature_from_text(sig_text)
                if signature:
                    embedding = get_resnet_embedding(item["path"])
                    updates.append((signature_to_text(signature, embedding), float(item.get("modified", -1)), item["path"]))

            if signature is None:
                signature = signature_variants(item["path"])
                embedding = get_resnet_embedding(item["path"])
                updates.append((signature_to_text(signature, embedding), float(item.get("modified", -1)), item["path"]))
        except Exception:
            continue

        if updates and (len(updates) >= 50 or index == total):
            signature_ready(updates)
            updates = []

        if index == total or index % 100 == 0:
            progress(int(index * 0.4 / total * 100), total)

        if embedding is not None:
            emb_np = np.array(embedding)
            emb_sim = float(np.dot(query_embedding_np, emb_np))
            stage1_candidates.append((item, emb_sim))

    # Filtrar candidatos en Stage 1 usando embedding semántico
    min_emb_sim = 0.40 if mode == "relacionado" else 0.45
    stage1_candidates = [c for c in stage1_candidates if c[1] >= min_emb_sim]
    stage1_candidates = sorted(stage1_candidates, key=lambda x: x[1], reverse=True)[:150]

    # Stage 2: Validación precisa
    matches = []
    num_stage2 = len(stage1_candidates)

    for i, (item, emb_sim) in enumerate(stage1_candidates, start=1):
        if cancelled():
            return None

        res = _precise_similarity(item["path"], query_path, ignore_background, search_duplicates_only, max_distance)

        if search_duplicates_only:
            score = res
        else:
            shape_sim, color_sim, hash_sim, combined_dist = res

            if mode == "relacionado":
                # En modo relacionado, el embedding (semántico) pesa bastante
                score = (emb_sim * 0.5 + shape_sim * 0.25 + color_sim * 0.25) * 100
                score = min(100.0, score + _tag_bonus(query_tags, item.get("tags", "")))
            elif mode == "estricto":
                # Estricto exige formas y composición/estructura.
                score = (shape_sim * 0.45 + hash_sim * 0.45 + color_sim * 0.10) * 100
                # Descartar si el contorno, la estructura o el color difieren notablemente
                if shape_sim < 0.65 or hash_sim < 0.65 or color_sim < 0.50:
                    score *= 0.1
            elif mode == "casi_exacto":
                # Casi exacto exige casi duplicado visual
                score = (shape_sim * 0.4 + hash_sim * 0.4 + color_sim * 0.2) * 100
                if shape_sim < 0.85 or hash_sim < 0.90 or color_sim < 0.80:
                    score *= 0.1
            else:
                score = (shape_sim * 0.62 + color_sim * 0.38) * 100

        score = round(min(100.0, max(0.0, score)), 1)
        if score >= minimum_score:
            matches.append((item["path"], score))

        if i == num_stage2 or i % 10 == 0:
            progress(int(40 + (i / num_stage2) * 60), total)

    # Ordenar todos los resultados desde el mayor porcentaje de coincidencia al menor
    matches = sorted(matches, key=lambda x: x[1], reverse=True)
    return matches[:limit]

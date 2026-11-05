"""Empaqueta las vistas previas del banco de stickers dentro de Doccione Mobile.

Uso:
  python scripts/build_mobile_sticker_bank.py --database C:\\ruta\\doccione.db

No copia originales: genera PNGs de 192 px y el manifiesto que consume Flutter.
Ejecutarlo antes de compilar una nueva APK/IPA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "mobile" / "doccione_mobile" / "assets" / "sticker_bank"


def design_id(file_path: str) -> str:
    return hashlib.sha256(file_path.encode("utf-8", errors="surrogatepass")).hexdigest()[:24]


def thumbnail(source: Path, target: Path) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            image = image.crop(bbox)
        image.thumbnail((192, 192), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
        canvas.alpha_composite(image, ((192 - image.width) // 2, (192 - image.height) // 2))
        canvas.save(target, "PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit(f"No existe la base de Studio: {args.database}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    setting = conn.execute(
        "SELECT setting_value FROM app_settings WHERE setting_key = 'mobile_catalog.access_mode'"
    ).fetchone()
    where = "1 = 1" if not setting or setting[0] == "all" else "images.is_reusable = 1 AND images.is_private = 0"
    rows = conn.execute(
        f"""SELECT images.path, images.name, images.category, images.caption,
                   images.visible_width, images.visible_height, images.modified,
                   (SELECT GROUP_CONCAT(tags.name, ' · ') FROM image_tags
                    JOIN tags ON tags.id = image_tags.tag_id
                    WHERE image_tags.image_path = images.path) AS tags
              FROM images WHERE {where} ORDER BY images.name COLLATE NOCASE"""
    ).fetchall()

    designs = []
    for row in rows:
        raw_path = str(row["path"])
        source = Path(raw_path)
        if not source.is_file():
            continue
        # Debe coincidir byte a byte con el ID que genera Studio desde images.path.
        identifier = design_id(raw_path)
        target = OUTPUT / f"{identifier}.png"
        try:
            # Permite retomar una exportación grande si se interrumpe.
            if not target.is_file():
                thumbnail(source, target)
        except (OSError, ValueError):
            continue
        designs.append({
            "id": identifier,
            "name": row["name"] or "Diseño",
            "category": row["category"] or "Sin categoría",
            "caption": row["caption"] or "",
            "tags": [tag.strip() for tag in (row["tags"] or "").split(" · ") if tag.strip()],
            "preview_url": "",
            "visible_width": int(row["visible_width"] or 0),
            "visible_height": int(row["visible_height"] or 0),
            "modified_ms": int(float(row["modified"] or 0) * 1000),
            "asset_preview_path": f"assets/sticker_bank/{identifier}.png",
        })
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"designs": designs}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Banco móvil generado: {len(designs)} vistas previas en {OUTPUT}")


if __name__ == "__main__":
    main()

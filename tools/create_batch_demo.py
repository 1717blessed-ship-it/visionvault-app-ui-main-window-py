"""Crea la base ficticia A/B/C para validar Producción por tandas."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from PIL import Image, ImageDraw

from app.database.database import ImageDatabase


def create_demo(database_path: Path) -> Path:
    database_path = database_path.resolve()
    if database_path.exists():
        raise ValueError(f"La base de demostración ya existe: {database_path}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    assets = database_path.parent / f"{database_path.stem}-assets"
    assets.mkdir(exist_ok=False)
    db = ImageDatabase(database_path)
    try:
        specs = (
            ("Cliente A", 20, "Vinilo blanco", "A", "line-demo-a", "#8a1f3d"),
            ("Cliente B", 12, "Vinilo blanco", "B", "line-demo-b", "#2563eb"),
            ("Cliente C", 10, "Vinilo especial", "C", "line-demo-c", "#ca8a04"),
        )
        for client, quantity, material, label, line_id, color in specs:
            image_path = assets / f"sticker-{label.lower()}.png"
            image = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((35, 35, 465, 465), radius=90, fill=color)
            draw.text((225, 220), label, fill="white")
            image.save(image_path)
            stat = image_path.stat()
            db.connection.execute(
                """INSERT INTO images(path,name,extension,size,modified,caption,visible_width,visible_height)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (str(image_path), image_path.name, ".png", stat.st_size, stat.st_mtime,
                 "Dato ficticio para validar tandas", 430, 430),
            )
            order_id = db.create_order(client, jobs=[{
                "title": "Stickers", "material": material, "size": "5 cm", "quantity": quantity,
            }])
            job_id = db.order_jobs(order_id)[0]["id"]
            db.link_design_to_order(
                order_id, str(image_path), quantity=quantity, size_cm=5,
                order_job_id=job_id, design_line_id=line_id,
            )
            db.connection.execute(
                """UPDATE order_design_demand_lines
                   SET unit_kind='item',packing_mode='standard_five_bands',workspace_format='a4'
                   WHERE design_line_id=?""", (line_id,),
            )
        db.connection.commit()
    finally:
        db.close()
    return database_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)
    print(create_demo(args.database))


if __name__ == "__main__":
    main()

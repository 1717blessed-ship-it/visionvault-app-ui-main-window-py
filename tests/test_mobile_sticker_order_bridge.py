import json
from pathlib import Path
from types import SimpleNamespace

from app.api.mobile_jobs import MobileJobsHandler
from app.database.database import ImageDatabase
from app.events.event_repository import EventRepository
from app.ui.main_window import VisionVaultApp


def _register_image(database: ImageDatabase, path: Path, caption: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")
    database.connection.execute(
        """INSERT INTO images(path, name, extension, size, modified, caption)
           VALUES(?, ?, ?, ?, ?, ?)""",
        (str(path), path.name, path.suffix, path.stat().st_size, path.stat().st_mtime, caption),
    )


def test_mobile_images_are_separated_and_marked_when_sent_to_creator(tmp_path: Path):
    database = ImageDatabase(tmp_path / "orders.db")
    try:
        order_id = database.create_order("Cliente móvil", material="Stickers")
        mobile_path = tmp_path / "mobile_uploads" / "foto.jpg"
        catalog_path = tmp_path / "catalog" / "sticker.png"
        _register_image(
            database, mobile_path,
            caption="Imagen recibida desde Doccione Mobile",
        )
        _register_image(database, catalog_path)
        database.connection.execute(
            """INSERT INTO order_designs(order_id, image_path, source)
               VALUES(?, ?, 'mobile')""",
            (order_id, str(mobile_path)),
        )
        database.connection.execute(
            """INSERT INTO order_designs(order_id, image_path, source)
               VALUES(?, ?, 'catalog')""",
            (order_id, str(catalog_path)),
        )
        database.connection.commit()

        assert [row["image_path"] for row in database.mobile_order_images(order_id)] == [
            str(mobile_path)
        ]

        updated = database.mark_mobile_images_sent_to_creator(
            order_id, [str(mobile_path), str(catalog_path)]
        )

        assert updated == 1
        mobile = database.connection.execute(
            """SELECT creator_status, creator_queued_at
               FROM order_designs WHERE order_id = ? AND image_path = ?""",
            (order_id, str(mobile_path)),
        ).fetchone()
        catalog = database.connection.execute(
            """SELECT creator_status, creator_queued_at
               FROM order_designs WHERE order_id = ? AND image_path = ?""",
            (order_id, str(catalog_path)),
        ).fetchone()
        assert mobile["creator_status"] == "Enviado"
        assert mobile["creator_queued_at"]
        assert catalog["creator_status"] == "Pendiente"
        assert catalog["creator_queued_at"] == ""

        event = database.order_events(order_id, limit=1)[0]
        assert event["event_type"] == "stickers.creator.queued"
        assert json.loads(event["data_json"])["image_paths"] == [str(mobile_path)]
    finally:
        database.close()


def test_order_autosave_preserves_mobile_creator_metadata(tmp_path: Path):
    database = ImageDatabase(tmp_path / "snapshot.db")
    try:
        order_id = database.create_order("Cliente móvil", material="Stickers")
        mobile_path = tmp_path / "mobile_uploads" / "foto.png"
        _register_image(
            database, mobile_path,
            caption="Imagen recibida desde Doccione Mobile",
        )
        database.link_design_to_order(
            order_id, str(mobile_path), source="mobile",
        )
        assert database.mark_mobile_images_sent_to_creator(
            order_id, [str(mobile_path)]
        ) == 1
        designs = database.order_designs(order_id)
        # Simula un borrador generado por una versión anterior de Studio.
        for key in ("source", "creator_status", "creator_queued_at"):
            designs[0].pop(key, None)

        database.save_order_snapshot(
            order_id,
            {
                "client": "Cliente móvil",
                "status": "Nuevo",
                "material": "Stickers",
                "quantity": 1,
                "price": 0,
            },
            designs,
        )

        restored = database.mobile_order_images(order_id)
        assert len(restored) == 1
        assert restored[0]["source"] == "mobile"
        assert restored[0]["creator_status"] == "Enviado"
        assert restored[0]["creator_queued_at"]
    finally:
        database.close()


def test_legacy_mobile_uploads_are_backfilled_on_database_open(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    mobile_path = tmp_path / "mobile_uploads" / "anterior.webp"
    database = ImageDatabase(db_path)
    try:
        order_id = database.create_order("Cliente anterior", material="Stickers")
        _register_image(
            database, mobile_path,
            caption="Imagen recibida desde Doccione Mobile",
        )
        database.connection.execute(
            """INSERT INTO order_designs(order_id, image_path, source)
               VALUES(?, ?, '')""",
            (order_id, str(mobile_path)),
        )
        database.connection.commit()
    finally:
        database.close()

    reopened = ImageDatabase(db_path)
    try:
        rows = reopened.mobile_order_images(order_id)
        assert len(rows) == 1
        assert rows[0]["source"] == "mobile"
    finally:
        reopened.close()


def test_mobile_api_records_catalog_and_phone_origins_separately(tmp_path: Path):
    database = ImageDatabase(tmp_path / "api.db")
    try:
        catalog_path = tmp_path / "catalog" / "publicado.png"
        _register_image(database, catalog_path)
        response = {}
        published_events = []
        handler = object.__new__(MobileJobsHandler)
        handler.event_repo = EventRepository(database.connection)
        handler.event_bus = type(
            "EventBus",
            (),
            {"publish": lambda _self, **payload: published_events.append(payload)},
        )()
        handler._read_multipart_images = lambda: (
            {
                "client": "Pedido app",
                "whatsapp": "123",
                "observations": "Desde el celular",
                "mode": "Plancha A4",
                "catalog_design_ids": ["catalog-id"],
                "client_request_id": "request-with-mockup-1",
                "reference_metadata": [{
                    "design_id": "catalog-id",
                    "design_name": "Publicado",
                    "size_cm": 12,
                    "surface": "bottle",
                    "surface_label": "Botella",
                    "material": "Vinilo transparente",
                    "comment": "Centrar con la etiqueta",
                    "approval": "changesRequested",
                    "approval_label": "Requiere cambios",
                    "curved": True,
                }],
            },
            [("camara.jpg", b"valid-payload-for-contract", "image/jpeg")],
            [("mockup.png", b"valid-reference-payload", "image/png")],
        )
        handler._catalog_design_by_id = lambda design_id: (
            {"path": str(catalog_path)} if design_id == "catalog-id" else None
        )
        handler._sticker_quote = lambda _mode, _count: ({"total": 5000}, None)
        handler._send_json_response = lambda status, body: response.update(
            {"status": status, "body": body}
        )
        handler._send_error = lambda status, message: response.update(
            {"status": status, "error": message}
        )

        handler._create_sticker_order({"id": 7})

        assert response["status"] == 201
        order_id = response["body"]["order_id"]
        rows = database.connection.execute(
            """SELECT image_path, source FROM order_designs
               WHERE order_id = ? ORDER BY source""",
            (order_id,),
        ).fetchall()
        assert [row["source"] for row in rows] == ["catalog", "mobile"]
        mobile_rows = database.mobile_order_images(order_id)
        assert len(mobile_rows) == 1
        assert Path(mobile_rows[0]["image_path"]).parent.name == "mobile_uploads"
        assert published_events[0]["payload"]["source"] == "mobile_stickers"
        mockup_event = next(
            event for event in database.order_events(order_id)
            if event["event_type"] == "order.mockups.mobile"
        )
        mockup = json.loads(mockup_event["data_json"])["mockups"][0]
        assert mockup["size_cm"] == 12
        assert mockup["surface"] == "bottle"
        assert mockup["material"] == "Vinilo transparente"
        assert mockup["comment"] == "Centrar con la etiqueta"
        assert mockup["approval"] == "changesRequested"
        assert mockup["curved"] is True
    finally:
        database.close()


def test_studio_dispatches_only_selected_mobile_images(tmp_path: Path):
    selected_path = tmp_path / "selected.png"
    ignored_path = tmp_path / "ignored.png"
    selected_path.write_bytes(b"selected")
    ignored_path.write_bytes(b"ignored")
    opened = []
    marked = []
    statuses = []
    tab = SimpleNamespace(
        mobile_image_selection={str(selected_path)},
        order_design_state=[],
    )
    database = SimpleNamespace(
        mobile_order_images=lambda _order_id: [
            {"image_path": str(selected_path)},
            {"image_path": str(ignored_path)},
        ],
        mark_mobile_images_sent_to_creator=lambda order_id, paths: (
            marked.append((order_id, paths)) or len(paths)
        ),
        order_designs=lambda _order_id: [{"image_path": str(selected_path)}],
    )
    studio = SimpleNamespace(
        order_tabs={42: tab},
        database=database,
        open_sticker_studio=lambda initial_paths: opened.append(initial_paths) or True,
        render_mobile_order_images=lambda _tab: None,
        status=SimpleNamespace(set=statuses.append),
    )

    VisionVaultApp.send_mobile_images_to_sticker_creator(studio, 42)

    assert opened == [[str(selected_path)]]
    assert marked == [(42, [str(selected_path)])]
    assert tab.order_design_state == [{"image_path": str(selected_path)}]
    assert "1 imagen(es)" in statuses[-1]

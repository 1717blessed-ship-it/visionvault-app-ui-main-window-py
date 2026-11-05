import json

from tools import mobile_sticker_bank


def _configure_bank(monkeypatch, tmp_path):
    bank = tmp_path / "sticker_bank"
    bank.mkdir()
    catalog = bank / "manifest.json"
    lock = tmp_path / "sticker_bank.lock.json"
    catalog.write_text(
        json.dumps(
            {
                "designs": [
                    {"asset_preview_path": "assets/sticker_bank/a.png"},
                    {"asset_preview_path": "assets/sticker_bank/b.png"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (bank / "a.png").write_bytes(b"a")
    (bank / "b.png").write_bytes(b"bb")
    monkeypatch.setattr(mobile_sticker_bank, "BANK", bank)
    monkeypatch.setattr(mobile_sticker_bank, "CATALOG", catalog)
    monkeypatch.setattr(mobile_sticker_bank, "LOCK", lock)
    return bank, catalog, lock


def test_mobile_sticker_bank_lock_and_verify(monkeypatch, tmp_path):
    bank, _catalog, lock = _configure_bank(monkeypatch, tmp_path)

    assert mobile_sticker_bank.create_lock() == 0
    document = json.loads(lock.read_text(encoding="utf-8"))
    assert document["file_count"] == 2
    assert document["total_bytes"] == 3
    assert mobile_sticker_bank.verify(allow_manifest_only=False) == 0

    (bank / "b.png").write_bytes(b"changed")
    assert mobile_sticker_bank.verify(allow_manifest_only=False) == 1


def test_mobile_sticker_bank_manifest_only_checkout(monkeypatch, tmp_path):
    bank, _catalog, _lock = _configure_bank(monkeypatch, tmp_path)
    assert mobile_sticker_bank.create_lock() == 0
    (bank / "a.png").unlink()
    (bank / "b.png").unlink()

    assert mobile_sticker_bank.verify(allow_manifest_only=True) == 0
    assert mobile_sticker_bank.verify(allow_manifest_only=False) == 1


def test_mobile_sticker_bank_rejects_unsafe_catalog_path(monkeypatch, tmp_path):
    _bank, catalog, _lock = _configure_bank(monkeypatch, tmp_path)
    catalog.write_text(
        json.dumps(
            {
                "designs": [
                    {"asset_preview_path": "assets/sticker_bank/../escape.png"}
                ]
            }
        ),
        encoding="utf-8",
    )

    try:
        mobile_sticker_bank.create_lock()
    except ValueError as error:
        assert "insegura" in str(error)
    else:
        raise AssertionError("se aceptó una ruta insegura")

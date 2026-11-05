import tempfile
from pathlib import Path

from app.indexer.scanner import scan_folder


def test_scan_folder_ignores_sticker_trash():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "visible.png").write_bytes(b"visible")
        trash = root / ".trash"
        trash.mkdir()
        (trash / "deleted.png").write_bytes(b"deleted")

        names = {item["name"] for item in scan_folder(root)}

    assert names == {"visible.png"}

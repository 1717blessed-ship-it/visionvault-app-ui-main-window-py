import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database.database import ImageDatabase


class TestStickerBankNaming(unittest.TestCase):
    def test_startup_import_numbers_and_indexes_external_designs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            db = ImageDatabase(str(temp_dir / "visionvault.db"))
            bank_dir = temp_dir / "bank"
            bank_dir.mkdir()
            (bank_dir / "05015.png").write_bytes(b"existing")
            external = bank_dir / "diseno-de-otra-app.jpg"
            external.write_bytes(b"external")
            db.save_library_root(str(bank_dir))

            imported = db.import_and_number_external_library_images()

            expected = (bank_dir / "05016.jpg").resolve()
            self.assertEqual(imported, [{"path": str(expected), "name": "05016.jpg"}])
            self.assertTrue(expected.is_file())
            self.assertFalse(external.exists())
            image = db.connection.execute(
                "SELECT name, is_private, is_reusable, import_status FROM images WHERE path = ?",
                (str(expected),),
            ).fetchone()
            self.assertEqual(tuple(image), ("05016.jpg", 0, 1, "Biblioteca"))
            db.close()

    def test_approve_processed_sticker_assigns_sequence_number_to_bank_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            db_path = temp_dir / "visionvault.db"
            db = ImageDatabase(str(db_path))
            bank_dir = temp_dir / "bank"
            bank_dir.mkdir(parents=True, exist_ok=True)

            (bank_dir / "05015.png").write_bytes(b"old-alpha")
            (bank_dir / "05016.png").write_bytes(b"old-beta")
            (bank_dir / "nombre-anterior.png").write_bytes(b"old-name")

            with patch.object(db, "get_library_root", return_value=str(bank_dir)):
                work_dir = temp_dir / "work" / "job"
                work_dir.mkdir(parents=True, exist_ok=True)
                master = work_dir / "sticker_master.png"
                master.write_bytes(b"new-image")

                result = {
                    "job_id": "abc12345",
                    "source_path": str(temp_dir / "source.png"),
                    "artifacts": {"master": str(master), "print": str(master)},
                }

                db.approve_processed_sticker(result, category="Test", tags=["Nuevo"])

            db.close()
            published_files = sorted(p.name for p in bank_dir.glob("*.png"))
            self.assertIn("05017.png", published_files)
            self.assertEqual(len(published_files), 4)

    def test_discarding_automatic_processing_removes_source_and_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            db = ImageDatabase(str(temp_dir / "visionvault.db"))
            source = temp_dir / "automatic-source.png"
            source.write_bytes(b"source")
            workspace = Path(tempfile.gettempdir()) / "visionvault_auto" / "test-discard-job"
            workspace.mkdir(parents=True, exist_ok=True)
            artifact = workspace / "sticker_master.png"
            artifact.write_bytes(b"artifact")

            db.upsert({
                "path": str(source), "name": source.name, "extension": ".png",
                "size": source.stat().st_size, "modified": source.stat().st_mtime, "caption": "",
            })
            db.connection.execute(
                """INSERT INTO sticker_processing_jobs
                   (id, source_path, status, analysis, artifacts, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                ("automatic-job", str(source), "Completado", '{"auto_process": true}', '{}'),
            )
            db.connection.execute(
                "INSERT INTO sticker_artifacts(job_id, kind, path) VALUES (?, ?, ?)",
                ("automatic-job", "master", str(artifact)),
            )
            db.connection.commit()

            self.assertTrue(db.discard_processed_sticker("automatic-job"))
            self.assertFalse(source.exists())
            self.assertFalse(workspace.exists())
            self.assertEqual(
                db.connection.execute(
                    "SELECT status FROM sticker_processing_jobs WHERE id = ?", ("automatic-job",)
                ).fetchone()[0],
                "Descartado",
            )
            db.close()


if __name__ == "__main__":
    unittest.main()

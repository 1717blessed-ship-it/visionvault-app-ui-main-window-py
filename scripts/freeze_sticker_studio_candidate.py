"""Crea un respaldo verificable y no destructivo del candidato productivo."""

from __future__ import annotations

from datetime import datetime
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts/sticker-studio-production-candidate/freeze-backup"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    candidates = [ROOT / "ui_settings.json", ROOT / "work/stickers/studio_v2_session.json"]
    candidates += sorted((ROOT / "work/stickers").glob("*/perfil_produccion.json"))
    copied = []
    for source in candidates:
        if not source.is_file():
            continue
        relative = source.relative_to(ROOT)
        destination = OUT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append({"source": str(relative), "backup": str(destination.relative_to(ROOT)),
                       "bytes": destination.stat().st_size, "sha256": sha(destination)})
    profile = __import__("app.stickers.models", fromlist=["ProcessingProfile"]).ProcessingProfile()
    git_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {
        "candidate": "2.0.0-rc.1", "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_head_before_candidate_commit": git_head,
        "classic_editor_preserved": (ROOT / "app/stickers/editor.py").is_file(),
        "profile_defaults": asdict(profile), "files": copied,
        "calibrations_modified_by_freeze": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "SHA256SUMS.txt").write_text(
        "".join(f"{row['sha256']}  {row['backup']}\n" for row in copied), encoding="utf-8")
    print(json.dumps({"files": len(copied), "manifest": str(OUT / "manifest.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

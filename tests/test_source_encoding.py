from pathlib import Path


def test_python_sources_do_not_contain_common_mojibake_markers():
    root = Path(__file__).resolve().parents[1] / "app"
    markers = ("Ã", "Â", "â€", "ðŸ")
    failures = []
    for path in root.rglob("*.py"):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        found = [marker for marker in markers if marker in text]
        if found:
            failures.append(f"{path.relative_to(root)}: {', '.join(found)}")
    assert not failures, "Codificación dañada detectada:\n" + "\n".join(failures)

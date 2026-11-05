"""Remove trailing spaces and normalize the final newline of text files."""

from __future__ import annotations

import argparse
from pathlib import Path


def clean(path: Path) -> bool:
    raw = path.read_bytes()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    while lines and lines[-1] == b"":
        lines.pop()
    cleaned = newline.join(line.rstrip(b" \t") for line in lines) + newline
    if cleaned == raw:
        return False
    path.write_bytes(cleaned)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    changed = [str(path) for path in args.paths if clean(path)]
    print(f"Archivos normalizados: {len(changed)}")
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

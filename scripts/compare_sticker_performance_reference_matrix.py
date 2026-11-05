"""Exige identidad binaria y semántica entre dos matrices de referencia."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    before = json.loads((args.baseline / "manifest.json").read_text(encoding="utf-8"))
    after = json.loads((args.candidate / "manifest.json").read_text(encoding="utf-8"))
    left = {(row["source_sha256"], row["case"]): row for row in before["rows"]}
    right = {(row["source_sha256"], row["case"]): row for row in after["rows"]}
    keys_equal = left.keys() == right.keys()
    differences = []
    for key in sorted(left.keys() & right.keys()):
        if left[key]["rasters"] != right[key]["rasters"]:
            differences.append({"key": key, "kind": "raster_sha256"})
        if left[key]["production_contract"] != right[key]["production_contract"]:
            differences.append({"key": key, "kind": "production_contract"})
        if left[key]["options"] != right[key]["options"]:
            differences.append({"key": key, "kind": "options"})
    report = {"keys_equal": keys_equal, "runs_compared": len(left.keys() & right.keys()),
              "differences": differences, "all_equal": keys_equal and not differences}
    destination = args.output or args.candidate / "comparison.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not report["all_equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

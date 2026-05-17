from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.punctuation import restore_punctuation_blocks  # noqa: E402
from app.segmenter import RawSegment, merge_segments  # noqa: E402


def repair_file(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_segments = [
        RawSegment(start=float(item["start"]), end=float(item["end"]), text=str(item["text"]))
        for item in data.get("segments", [])
    ]
    blocks = restore_punctuation_blocks(merge_segments(raw_segments))
    data["segments"] = [
        {"start": block.start, "end": block.end, "text": block.text}
        for block in blocks
    ]
    data["duration"] = round(max((block.end for block in blocks), default=data.get("duration", 0)), 2)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"repaired {path}")


def main() -> None:
    for path in (ROOT / "data" / "items").glob("*/result.json"):
        repair_file(path)


if __name__ == "__main__":
    main()

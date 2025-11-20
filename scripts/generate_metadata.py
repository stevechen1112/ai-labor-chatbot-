from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "data" / "laws"
OUT = ROOT / "data" / "index" / "metadata.json"


def slugify(name: str) -> str:
    s = name.strip()
    for ch in [" ", "/", "\\", "(", ")", "[", "]", "【", "】", "（", "）", "，", ",", "。", "."]:
        s = s.replace(ch, "-")
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    data = {}
    for p in sorted(LAWS_DIR.glob("*.md")):
        title = p.stem
        try:
            first = p.read_text(encoding="utf-8", errors="ignore").splitlines()[0].strip()
            if first and first.startswith("#"):
                title = first.lstrip("#").strip()
        except Exception:
            pass
        law_id = slugify(p.stem)
        checksum = sha256_of(p)
        prev_entry = prev.get(p.name, {}) if isinstance(prev, dict) else {}
        entry = {
            "title": title,
            "law_id": law_id,
            "checksum": checksum,
            # placeholders preserved if previously filled
            "source_url": prev_entry.get("source_url", ""),
            "last_amended": prev_entry.get("last_amended", ""),
            "law_version": prev_entry.get("law_version", ""),
            "keywords": prev_entry.get("keywords", []),
        }
        data[p.name] = entry

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote metadata -> {OUT}")


if __name__ == "__main__":
    main()

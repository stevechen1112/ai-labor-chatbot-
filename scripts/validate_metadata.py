from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List
import hashlib

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "data" / "laws"
META_PATH = ROOT / "data" / "index" / "metadata.json"
REPORT = ROOT / "data" / "index" / "metadata_report.json"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def is_date(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", s or ""))


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def validate() -> Dict:
    if not META_PATH.exists():
        raise SystemExit("metadata.json 不存在，請先執行 scripts/generate_metadata.py")
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    errors: List[Dict] = []
    warnings: List[Dict] = []
    ok = 0
    total = 0
    for name, entry in meta.items():
        total += 1
        p = LAWS_DIR / name
        miss = []
        # required fields presence
        for fld in ["title", "law_id", "checksum", "last_amended", "source_url", "law_version"]:
            if not str(entry.get(fld, "")).strip():
                miss.append(fld)
        # checksum
        cs = entry.get("checksum", "")
        if p.exists():
            real = sha256_of(p)
            if cs and cs != real:
                warnings.append({"file": name, "type": "checksum_mismatch", "expected": cs, "actual": real})
        else:
            warnings.append({"file": name, "type": "missing_file"})
        # formats
        if entry.get("last_amended") and not is_date(entry.get("last_amended", "")):
            warnings.append({"file": name, "type": "last_amended_format", "value": entry.get("last_amended")})
        if entry.get("source_url") and not is_url(entry.get("source_url", "")):
            warnings.append({"file": name, "type": "source_url_format", "value": entry.get("source_url")})

        if miss:
            errors.append({"file": name, "missing": miss})
        else:
            ok += 1

    report = {"total": total, "ok": ok, "errors": errors, "warnings": warnings}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote report -> {REPORT}")
    return report


if __name__ == "__main__":
    validate()


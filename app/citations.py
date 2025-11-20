from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
META_PATH = ROOT / "data" / "index" / "metadata.json"


@lru_cache(maxsize=1)
def load_metadata() -> Dict[str, Dict]:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def citation_from(title: str, heading: str) -> str:
    title = title.strip() if title else ""
    heading = heading.strip() if heading else ""
    if title and heading:
        return f"{title}｜{heading}"
    return title or heading or ""


def decorate_citation(c: Dict) -> Dict:
    meta = load_metadata()
    source = c.get("source_file", "")
    heading = c.get("heading", "")
    title = meta.get(source, {}).get("title") or source.rsplit(".", 1)[0]
    cite = citation_from(title, heading)
    c2 = dict(c)
    c2["title"] = title
    c2["citation"] = cite
    c2["citation_md"] = f"- {cite}"
    return c2


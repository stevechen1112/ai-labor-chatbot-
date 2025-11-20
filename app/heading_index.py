from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
INDEX_JSON = ROOT / "data" / "index" / "index.json"


class HeadingIndex:
    """Lightweight lookup table for article numbers / keywords."""

    def __init__(self, index_path: Path = INDEX_JSON):
        self.index_path = index_path
        self.docs: List[Dict] = []
        self.article_map: Dict[str, List[Dict]] = {}
        self.keyword_map: Dict[str, List[Dict]] = {}
        self._load()

    def _load(self) -> None:
        if not self.index_path.exists():
            raise RuntimeError(f"heading index source not found: {self.index_path}")
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        docs = data.get("docs", [])
        self.docs = docs
        for doc in docs:
            art = str(doc.get("article_no") or "").strip()
            if art:
                self.article_map.setdefault(art, []).append(doc)
                # article numbers sometimes written without leading zeros
                art_no_wo_zero = art.lstrip("0")
                if art_no_wo_zero and art_no_wo_zero != art:
                    self.article_map.setdefault(art_no_wo_zero, []).append(doc)
            heading = doc.get("heading") or ""
            if heading:
                tokens = self._tokenize_heading(heading)
                for token in tokens:
                    self.keyword_map.setdefault(token, []).append(doc)

    @staticmethod
    def _tokenize_heading(heading: str) -> List[str]:
        # Keep only CJK/ASCII alphanumerics, split by whitespace/punctuation.
        heading = re.sub(r"[^\w\u4e00-\u9fff\-]", " ", heading)
        tokens = [t for t in heading.split() if t]
        return tokens

    def search_by_article(
        self,
        article_no: str,
        preferred_laws: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[Dict]:
        key = str(article_no or "").strip()
        if not key:
            return []
        matches = list(self.article_map.get(key, []))
        if not matches:
            return []
        preferred = []
        others = []
        preferred_laws = preferred_laws or []
        for doc in matches:
            law_id = doc.get("law_id") or ""
            if any(pref and pref in law_id for pref in preferred_laws):
                preferred.append(doc)
            else:
                others.append(doc)
        ordered = preferred + others
        unique = []
        seen = set()
        for doc in ordered:
            doc_id = doc.get("id")
            if doc_id and doc_id not in seen:
                unique.append(doc)
                seen.add(doc_id)
            if len(unique) >= limit:
                break
        return unique

    def search_by_keyword(self, keyword: str, limit: int = 5) -> List[Dict]:
        key = keyword.strip()
        if not key:
            return []
        matches = self.keyword_map.get(key)
        if not matches:
            return []
        seen = set()
        result = []
        for doc in matches:
            doc_id = doc.get("id")
            if doc_id and doc_id not in seen:
                result.append(doc)
                seen.add(doc_id)
            if len(result) >= limit:
                break
        return result


@lru_cache(maxsize=1)
def get_heading_index() -> HeadingIndex:
    return HeadingIndex()

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "law_guides.yaml"


class LawGuideEngine:
    """Topic-to-law routing data derived from law_guides.yaml."""

    def __init__(self, guide_path: Path = GUIDE_PATH):
        if not guide_path.exists():
            raise RuntimeError(f"law guide not found: {guide_path}")
        raw = yaml.safe_load(guide_path.read_text(encoding="utf-8"))
        self.guides: Dict[str, Dict] = raw.get("topics", {})

    def match_topic(self, query: str) -> Tuple[Optional[str], Optional[Dict]]:
        query = query or ""
        for topic_id, guide in self.guides.items():
            keywords = guide.get("keywords") or []
            if any(kw and kw in query for kw in keywords):
                return topic_id, guide
        return None, None

    def get_preferred_laws(self, topic_id: Optional[str]) -> List[str]:
        if not topic_id or topic_id not in self.guides:
            return []
        laws = []
        for item in self.guides[topic_id].get("core_articles", []):
            law = item.get("law")
            if law:
                laws.append(law)
        return laws

    def get_blocked_laws(self, topic_id: Optional[str]) -> List[str]:
        if not topic_id or topic_id not in self.guides:
            return []
        return self.guides[topic_id].get("blocked_laws", []) or []

    def get_prior_articles(self, topic_id: Optional[str]) -> List[str]:
        if not topic_id or topic_id not in self.guides:
            return []
        priors: List[str] = []
        for entry in self.guides[topic_id].get("core_articles", []):
            for art in entry.get("articles", []):
                priors.append(str(art))
        return priors

    def boost_results(
        self,
        items: List[Tuple[float, Dict]],
        topic_id: Optional[str],
    ) -> List[Tuple[float, Dict]]:
        if not topic_id or topic_id not in self.guides:
            return items
        core = self.guides[topic_id].get("core_articles", [])
        if not core:
            return items
        boosted: List[Tuple[float, Dict]] = []
        for score, doc in items:
            new_score = score
            law = doc.get("law_id") or doc.get("title") or ""
            art = str(doc.get("article_no") or "").strip()
            for entry in core:
                core_law = entry.get("law") or ""
                articles = [str(a) for a in entry.get("articles", [])]
                priority = float(entry.get("priority") or 1.0)
                if core_law and core_law in law and (not articles or art in articles):
                    new_score *= priority
                    break
            boosted.append((new_score, doc))
        boosted.sort(key=lambda x: x[0], reverse=True)
        return boosted

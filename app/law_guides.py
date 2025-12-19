from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple, NamedTuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "data" / "law_guides.yaml"


class TopicMatch(NamedTuple):
    """Represents a matched topic with scoring details."""
    topic_id: str
    guide: Dict
    hit_count: int      # Number of keyword matches
    priority: float     # Max priority from core_articles
    category: str       # definition / procedure / penalty / general
    score: float        # Final weighted score


# Category priority mapping (definition queries need foundational articles)
CATEGORY_WEIGHT = {
    "definition": 1.5,    # 定義性條文優先（第2條等）
    "procedure": 1.2,     # 程序性條文
    "right": 1.3,         # 權益性條文
    "penalty": 1.0,       # 罰則
    "general": 1.0,       # 一般
}


class LawGuideEngine:
    """Topic-to-law routing data derived from law_guides.yaml."""

    def __init__(self, guide_path: Path = GUIDE_PATH):
        if not guide_path.exists():
            raise RuntimeError(f"law guide not found: {guide_path}")
        raw = yaml.safe_load(guide_path.read_text(encoding="utf-8"))
        self.guides: Dict[str, Dict] = raw.get("topics", {})

    # ==================== 🆕 Phase 2.7: Multi-topic Matching ====================
    
    def match_topics(self, query: str, max_topics: int = 3) -> List[TopicMatch]:
        """
        Match query against ALL topics, return ranked list of matches.
        
        Scoring formula: score = hit_count × priority × category_weight
        
        This fixes the "first match wins" problem by:
        1. Counting how many keywords match (hit_count)
        2. Considering topic priority from YAML
        3. Weighting by category (definition > procedure > penalty)
        4. Returning ALL matches sorted by score
        """
        query = (query or "").lower()
        matches: List[TopicMatch] = []
        
        for topic_id, guide in self.guides.items():
            keywords = guide.get("keywords") or []
            
            # Count keyword hits (case-insensitive)
            hit_count = sum(1 for kw in keywords if kw and kw.lower() in query)
            
            if hit_count == 0:
                continue
            
            # Get max priority from core_articles
            max_priority = 1.0
            for entry in guide.get("core_articles", []):
                p = float(entry.get("priority") or 1.0)
                if p > max_priority:
                    max_priority = p
            
            # Get category (default to "general")
            category = guide.get("category", "general")
            category_weight = CATEGORY_WEIGHT.get(category, 1.0)
            
            # Calculate final score
            score = hit_count * max_priority * category_weight
            
            matches.append(TopicMatch(
                topic_id=topic_id,
                guide=guide,
                hit_count=hit_count,
                priority=max_priority,
                category=category,
                score=score
            ))
        
        # Sort by score descending
        matches.sort(key=lambda m: m.score, reverse=True)
        
        return matches[:max_topics]
    
    def match_topic(self, query: str) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Legacy API: Return best matching topic (backward compatible).
        Now uses match_topics() internally.
        """
        matches = self.match_topics(query, max_topics=1)
        if matches:
            return matches[0].topic_id, matches[0].guide
        return None, None
    
    def get_merged_prior_articles(self, matches: List[TopicMatch]) -> List[str]:
        """
        Merge prior_articles from ALL matched topics.
        De-duplicate and preserve priority order.
        """
        seen = set()
        result: List[str] = []
        
        for match in matches:
            for entry in match.guide.get("core_articles", []):
                for art in entry.get("articles", []):
                    art_str = str(art)
                    if art_str not in seen:
                        seen.add(art_str)
                        result.append(art_str)
        
        return result
    
    def get_merged_preferred_laws(self, matches: List[TopicMatch]) -> List[str]:
        """
        Merge preferred_laws from ALL matched topics.
        De-duplicate and preserve priority order.
        """
        seen = set()
        result: List[str] = []
        
        for match in matches:
            for entry in match.guide.get("core_articles", []):
                law = entry.get("law")
                if law and law not in seen:
                    seen.add(law)
                    result.append(law)
        
        return result
    
    def get_merged_blocked_laws(self, matches: List[TopicMatch]) -> List[str]:
        """
        Merge blocked_laws from ALL matched topics.
        """
        seen = set()
        result: List[str] = []
        
        for match in matches:
            for b in match.guide.get("blocked_laws", []) or []:
                if b and b not in seen:
                    seen.add(b)
                    result.append(b)
        
        return result

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

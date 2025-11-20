from __future__ import annotations



from typing import Dict, List, Tuple, Optional

import re



# 🆕 Phase 1: Use centralized reranker module
from .reranker import get_reranker as _get_reranker_instance, is_available as reranker_available

def _get_reranker():
    """Get reranker instance (backward compatible wrapper)"""
    if not reranker_available():
        return None
    try:
        return _get_reranker_instance()
    except Exception as e:
        print(f"[Retrieval] Reranker initialization failed: {e}")
        return None





from .rag_utils import search as tfidf_search

from .vector_store import is_available as vector_available, search as vector_search

from .heading_index import get_heading_index

from .law_guides import LawGuideEngine


_GUIDE_ENGINE: Optional[LawGuideEngine] = None


def _get_guide_engine() -> Optional[LawGuideEngine]:

    global _GUIDE_ENGINE

    if _GUIDE_ENGINE is not None:

        return _GUIDE_ENGINE

    try:

        _GUIDE_ENGINE = LawGuideEngine()

    except Exception:

        _GUIDE_ENGINE = None

    return _GUIDE_ENGINE


def _extract_article_no(q: str) -> str | None:

    q = q.strip()

    m = re.search(r"\u7B2C\s*([\u4E00-\u9FFF0-9]+)\s*\u689D", q)

    if m:

        return m.group(1)

    m = re.search(r"([0-9]{1,3})\s*\u689D", q)

    if m:

        return m.group(1)

    m = re.search(r"\u7B2C\s*([0-9]{1,3})", q)

    if m:

        return m.group(1)

    return None


def _extract_chapter_token(q: str) -> str | None:

    m = re.search(r"\u7B2C\s*([\u4E00-\u9FFF0-9]+)\s*\u7AE0", q.strip())

    return m.group(0) if m else None


def _extract_keywords(q: str, max_tokens: int = 3) -> List[str]:

    tokens = re.findall(r"[\u4e00-\u9fff]{2,}", q)

    uniq: List[str] = []

    for tok in tokens:

        if tok not in uniq:

            uniq.append(tok)

        if len(uniq) >= max_tokens:

            break

    return uniq



def hybrid_search(
    query: str,
    top_k: int = 5,
    w_vec: float = 0.6,
    w_lex: float = 0.4,
    use_rerank: bool = False,
    rerank_top_k: int = 20,
    preferred_laws: Optional[List[str]] = None,
    blocked_laws: Optional[List[str]] = None,
    required_phrases: Optional[List[str]] = None,
    prior_articles: Optional[List[str]] = None,
    strict_whitelist: bool = False,
) -> List[Tuple[float, Dict]]:
    # Gather candidates
    cand: Dict[str, Dict] = {}
    score_map = {}

    heading_hits: List[Dict] = []
    heading_index = None
    try:
        heading_index = get_heading_index()
    except Exception:
        heading_index = None

    guide_engine = _get_guide_engine()
    topic_id = None
    if guide_engine:
        topic_id, _topic = guide_engine.match_topic(query)
        if _topic:
            topic_pref = guide_engine.get_preferred_laws(topic_id)
            if topic_pref:
                preferred_laws = (preferred_laws or []) + topic_pref
            topic_block = guide_engine.get_blocked_laws(topic_id)
            if topic_block:
                blocked_laws = (blocked_laws or []) + topic_block
            topic_prior = guide_engine.get_prior_articles(topic_id)
            if topic_prior:
                prior_articles = (prior_articles or []) + topic_prior

    if vector_available():
        for s, d in vector_search(query, top_k=max(10, top_k)):
            cand[d["id"]] = d
            score_map.setdefault(d["id"], 0.0)
            score_map[d["id"]] += w_vec * float(s)

    for s, d in tfidf_search(query, top_k=max(10, top_k)):
        cand[d["id"]] = d
        score_map.setdefault(d["id"], 0.0)
        score_map[d["id"]] += w_lex * float(s)

    article_hint = _extract_article_no(query)
    if heading_index:
        try:
            if article_hint:
                heading_hits.extend(
                    heading_index.search_by_article(
                        article_hint, preferred_laws=preferred_laws, limit=5
                    )
                )
            for kw in _extract_keywords(query):
                heading_hits.extend(heading_index.search_by_keyword(kw, limit=3))
        except Exception:
            heading_hits = []

    for doc in heading_hits:
        doc_id = doc.get("id")
        if not doc_id or doc_id in cand:
            continue
        cand[doc_id] = doc
        score_map.setdefault(doc_id, 0.0)
        score_map[doc_id] += 1.0

    art = article_hint
    chap_tok = _extract_chapter_token(query)
    items: List[Tuple[float, Dict]] = []
    # Optional required phrases filter helper
    def _has_required(d: Dict) -> bool:
        if not required_phrases:
            return True
        txt = (d.get("text") or "") + "\n" + (d.get("heading") or "")
        return any(rp in txt for rp in required_phrases)
    keys = list(score_map.keys())
    for i in keys:
        s = score_map[i]
        d = cand[i]
        law_id = d.get("law_id") or ""
        src = (d.get("source_file") or "")
        title = d.get("title") or ""
        # Strict whitelist: drop non-preferred entirely
        if strict_whitelist and preferred_laws:
            if not any((p and (p in law_id or p in src or p in title)) for p in preferred_laws):
                continue
        if art and d.get("heading") and art in d.get("heading", ""):
            s += 0.15
        if chap_tok and d.get("chapter") and chap_tok in d.get("chapter", ""):
            s += 0.10
        # required phrases
        if not _has_required(d):
            s -= 0.5
        # Apply law-level preferences
        # Blocked laws: strong penalty
        if blocked_laws:
            for b in blocked_laws:
                if not b:
                    continue
                if (b in law_id) or (b in src) or (b in title):
                    s -= 1e6
        # Preferred laws: boost preferred, mild penalty for others
        if preferred_laws:
            matched_pref = False
            for p in preferred_laws:
                if not p:
                    continue
                if (p in law_id) or (p in src) or (p in title):
                    matched_pref = True
                    break
            if matched_pref:
                s += 0.20
            else:
                s -= 0.05
        # prior articles boost
        if prior_articles:
            a = (d.get("article_no") or "")
            if any((pa == a) or (pa in (d.get("heading") or "")) for pa in prior_articles):
                s += 0.20
        # Civil law penalty (unless explicitly mentioned in query)
        if "民法" in law_id or "民法" in title:
            # Only penalize if user didn't explicitly ask for civil law
            if not any(kw in query for kw in ["民法", "債編", "僱傭", "債務", "侵權"]):
                s -= 0.5  # Significant penalty to prioritize labor laws
        items.append((s, d))
    items.sort(key=lambda x: x[0], reverse=True)

    if topic_id and guide_engine:
        items = guide_engine.boost_results(items, topic_id)
    
    # 🆕 Phase 2.5: Force-retrieve prior_articles if missing
    if prior_articles:
        from .articles import find_article
        # Check which prior articles are missing from current results
        current_articles = set()
        for _, d in items:
            art = d.get("article_no", "").strip()
            if art:
                current_articles.add(art)
        
        missing_articles = [pa for pa in prior_articles if pa not in current_articles]
        
        if missing_articles:
            print(f"[Retrieval] Force-retrieving {len(missing_articles)} missing prior articles: {missing_articles}")
            for missing_art in missing_articles:
                # Try to find the article directly
                # Assume it's from the preferred law (usually first one)
                target_law = preferred_laws[0] if preferred_laws else "勞動基準法"
                result = find_article(target_law, missing_art)
                if result:
                    # Add to items with high score
                    items.insert(0, (100.0, {
                        "id": f"{target_law}_{missing_art}",
                        "law_id": target_law,
                        "article_no": missing_art,
                        "heading": result.get("heading", ""),
                        "text": result.get("text", ""),
                        "source_file": result.get("source_file", ""),
                        "chapter": result.get("chapter", ""),
                        "title": target_law
                    }))
                    print(f"[Retrieval] Force-retrieved article: {target_law} 第{missing_art}條")

    # 🆕 Phase 1: Enhanced Reranker integration
    if use_rerank:
        reranker = _get_reranker()
        if reranker is not None:
            pool = items[: max(rerank_top_k, top_k)]
            # Convert to dict format expected by reranker.rerank()
            candidates = [{"text": d.get("text", ""), "original_score": s, **d} for s, d in pool]
            
            try:
                # Use new reranker API
                reranked_candidates = reranker.rerank(
                    query=query,
                    candidates=candidates,
                    top_k=top_k,
                    text_key="text"
                )
                # Convert back to (score, dict) format
                items = [(c.get('rerank_score', 0), c) for c in reranked_candidates]
            except Exception as e:
                print(f"[Retrieval] Reranker failed, using original scores: {e}")
                # Fallback to original ranking
                items = pool

    return items[:top_k]


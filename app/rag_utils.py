from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "index" / "index.json"


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
    )


def tokenize(text: str):
    import re

    text = text.lower()
    ascii_tokens = re.findall(r"[a-z0-9]+", text)
    ascii_tokens = [t for t in ascii_tokens if len(t) >= 2]
    cjk_seq = [ch for ch in text if is_cjk(ch)]
    cjk_unigrams = cjk_seq
    cjk_bigrams = [cjk_seq[i] + cjk_seq[i + 1] for i in range(len(cjk_seq) - 1)]
    return ascii_tokens + cjk_unigrams + cjk_bigrams


@lru_cache(maxsize=1)
def load_index() -> Dict:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(f"Index not found: {INDEX_PATH}")
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _precompute() -> Tuple[Dict, Dict, float, List[Dict]]:
    """Return (idf, doc_norm, q_norm_default, docs)."""
    index = load_index()
    docs = index["docs"]
    N = index["meta"]["num_docs"]
    idf = {t: math.log((N + 1) / (df + 1)) + 1.0 for t, df in index["meta"]["df"].items()}
    doc_norm = {}
    for d in docs:
        s = 0.0
        for t, c in d["tf"].items():
            w = c * idf.get(t, 0.0)
            s += w * w
        doc_norm[d["id"]] = math.sqrt(s) if s > 0 else 1.0
    return idf, doc_norm, 1.0, docs


def search(query: str, top_k: int = 5) -> List[Tuple[float, Dict]]:
    idf, doc_norm, q_norm_default, docs = _precompute()

    # Query vector
    q_tf: Dict[str, int] = {}
    for t in tokenize(query):
        q_tf[t] = q_tf.get(t, 0) + 1
    q_weights = {t: c * idf.get(t, 0.0) for t, c in q_tf.items()}
    q_norm = math.sqrt(sum(w * w for w in q_weights.values())) or q_norm_default

    # Score
    scores: List[Tuple[float, Dict]] = []
    for d in docs:
        dot = 0.0
        tf = d["tf"]
        for t, qw in q_weights.items():
            if t in tf:
                dot += qw * (tf[t] * idf.get(t, 0.0))
        sim = dot / (q_norm * doc_norm[d["id"]]) if dot > 0 else 0.0
        if sim > 0:
            scores.append((sim, d))
    scores.sort(key=lambda x: x[0], reverse=True)
    return scores[:top_k]


import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "data" / "index" / "index.json"
LAWS_DIR = ROOT / "data" / "laws"


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


def load_index():
    if not INDEX_PATH.exists():
        raise SystemExit(f"Index not found: {INDEX_PATH}. Run: python scripts/build_index.py")
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        idx = json.load(f)
    return idx


def compute_idf(meta_df: dict, N: int):
    # Smooth IDF
    return {t: math.log((N + 1) / (df + 1)) + 1.0 for t, df in meta_df.items()}


def score_query(index: dict, query: str, top_k: int = 5):
    docs = index["docs"]
    N = index["meta"]["num_docs"]
    idf = compute_idf(index["meta"]["df"], N)

    # Build doc vector norms (tf-idf)
    doc_norm = {}
    for d in docs:
        s = 0.0
        for t, c in d["tf"].items():
            w = (c) * idf.get(t, 0.0)
            s += w * w
        doc_norm[d["id"]] = math.sqrt(s) if s > 0 else 1.0

    # Query vector
    q_tf = {}
    for t in tokenize(query):
        q_tf[t] = q_tf.get(t, 0) + 1
    q_weights = {t: c * idf.get(t, 0.0) for t, c in q_tf.items()}
    q_norm = math.sqrt(sum(w * w for w in q_weights.values())) or 1.0

    # Score
    scores = []
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


def main():
    ap = argparse.ArgumentParser(description="Search Taiwan labor laws index (TF-IDF, no deps)")
    ap.add_argument("query", type=str, help="query text")
    ap.add_argument("-k", "--top_k", type=int, default=5)
    args = ap.parse_args()

    index = load_index()
    results = score_query(index, args.query, top_k=args.top_k)

    if not results:
        print("No results.")
        return

    for rank, (score, d) in enumerate(results, start=1):
        preview = d["text"].strip().replace("\n", " ")
        if len(preview) > 160:
            preview = preview[:157] + "..."
        print(f"[{rank}] score={score:.4f} file={d['source_file']} id={d['id']}")
        print(f"    heading: {d['heading']}")
        print(f"    preview: {preview}")


if __name__ == "__main__":
    main()


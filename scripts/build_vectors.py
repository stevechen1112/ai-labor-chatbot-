"""
Build vector index and store embeddings inside ChromaDB.

Default configuration (Phase 1):
    backend = HuggingFace sentence-transformers
    model   = BAAI/bge-large-zh-v1.5

You can still switch to the OpenAI backend with --backend openai.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
INDEX_JSON = ROOT / "data" / "index" / "index.json"
CHROMA_DIR = ROOT / "data" / "index" / "chroma"
API_KEY_FILE = ROOT / "api key.txt"

DEFAULT_BACKEND = "hf"
DEFAULT_MODEL = "BAAI/bge-large-zh-v1.5"
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def read_api_key() -> str:
    if not API_KEY_FILE.exists():
        raise SystemExit("api key.txt 缺失，請放入 OpenAI API key")
    content = API_KEY_FILE.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if "openai" in ln.lower() and i + 1 < len(lines):
            return lines[i + 1]
    for ln in lines:
        if ln.startswith(("sk-", "sk_projec", "sk-proj-")):
            return ln
    if lines:
        return lines[0]
    raise SystemExit("api key.txt 未找到有效的 OpenAI API key")


def load_chunks() -> Tuple[List[str], List[str], List[dict]]:
    if not INDEX_JSON.exists():
        raise SystemExit("缺少 data/index/index.json，請先執行 scripts/build_index.py")
    data = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    docs = data["docs"]
    ids = [d["id"] for d in docs]
    texts = [d["text"] for d in docs]
    metas = [
        {
            "source_file": d["source_file"],
            "heading": d.get("heading", ""),
            "law_id": d.get("law_id", ""),
            "title": d.get("title", ""),
            "last_amended": d.get("last_amended", ""),
            "law_version": d.get("law_version", ""),
            "source_url": d.get("source_url", ""),
            "checksum": d.get("checksum", ""),
            "chapter": d.get("chapter", ""),
            "article_no": d.get("article_no", ""),
        }
        for d in docs
    ]
    return ids, texts, metas


def batch(iterable: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def add_openai_vectors(col, ids, texts, metas, model, batch_size, args):
    from openai import OpenAI

    key = args.api_key or read_api_key()
    client = OpenAI(
        api_key=key,
        base_url=args.base_url or None,
        organization=args.org or None,
        project=args.project or None,
    )
    try:
        col.modify(metadata={"backend": "openai", "model_name": model})
    except Exception:
        pass

    total = len(texts)
    added = 0
    t0 = time.time()
    for b_idx, sl in enumerate(batch(list(range(total)), batch_size), start=1):
        batch_texts = [texts[i] for i in sl]
        batch_ids = [ids[i] for i in sl]
        batch_meta = [metas[i] for i in sl]
        resp = client.embeddings.create(model=model, input=batch_texts)
        vectors: List[List[float]] = [item.embedding for item in resp.data]
        col.add(ids=batch_ids, embeddings=vectors, documents=batch_texts, metadatas=batch_meta)
        added += len(sl)
        if b_idx % 5 == 0:
            dt = time.time() - t0
            print(f"Batch {b_idx}: added {added}/{total} in {dt:.1f}s")


def add_hf_vectors(col, ids, texts, metas, model, batch_size):
    from sentence_transformers import SentenceTransformer

    model_hf = SentenceTransformer(model)

    def encode_passages(txts: List[str]) -> List[List[float]]:
        lower = model.lower()
        if "e5" in lower:
            txts = ["passage: " + t for t in txts]
        # BGE、其他中文模型不需要 passage 標記，只要保持 normalize 即可
        return model_hf.encode(
            txts,
            batch_size=batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
        ).tolist()

    try:
        col.modify(metadata={"backend": "hf", "model_name": model})
    except Exception:
        pass

    total = len(texts)
    added = 0
    t0 = time.time()
    for b_idx, sl in enumerate(batch(list(range(total)), batch_size), start=1):
        batch_texts = [texts[i] for i in sl]
        batch_ids = [ids[i] for i in sl]
        batch_meta = [metas[i] for i in sl]
        vectors = encode_passages(batch_texts)
        col.add(ids=batch_ids, embeddings=vectors, documents=batch_texts, metadatas=batch_meta)
        added += len(sl)
        if b_idx % 5 == 0:
            dt = time.time() - t0
            print(f"Batch {b_idx}: added {added}/{total} in {dt:.1f}s")


def main():
    import chromadb

    ap = argparse.ArgumentParser(description="Build Chroma vectors with embeddings (OpenAI or HF)")
    ap.add_argument("--backend", choices=["openai", "hf"], default=DEFAULT_BACKEND, help="Embedding backend")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Embedding model name")
    ap.add_argument("--batch", type=int, default=256, help="Embedding batch size")
    ap.add_argument("--rebuild", action="store_true", help="Force rebuild collection (delete existing ids)")
    ap.add_argument("--api-key", dest="api_key", default=None, help="Explicit OpenAI API key")
    ap.add_argument("--base-url", dest="base_url", default=None, help="OpenAI base URL override")
    ap.add_argument("--org", dest="org", default=None, help="OpenAI organization id")
    ap.add_argument("--project", dest="project", default=None, help="OpenAI project id")
    args = ap.parse_args()

    ids, texts, metas = load_chunks()

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = client.get_or_create_collection(name="laws", metadata={"hnsw:space": "cosine"})

    if args.rebuild:
        try:
            existing = col.get(ids=ids)["ids"]
            for bid in batch(existing, 500):
                col.delete(ids=bid)
        except Exception:
            pass

    print(f"Total chunks: {len(texts)}. Start embedding with {args.backend}:{args.model} ...")
    if args.backend == "openai":
        add_openai_vectors(col, ids, texts, metas, args.model, max(1, args.batch), args)
    else:
        add_hf_vectors(col, ids, texts, metas, args.model, max(1, args.batch))

    print(f"Done. Stored in {CHROMA_DIR} collection 'laws' with backend={args.backend}, model={args.model}.")


if __name__ == "__main__":
    main()

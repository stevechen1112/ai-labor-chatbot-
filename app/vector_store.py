from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    import chromadb  # type: ignore
except Exception:  # pragma: no cover - optional dep
    chromadb = None

ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = ROOT / "data" / "index" / "chroma"
COLLECTION = "laws"
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def is_available() -> bool:
    if chromadb is None:
        return False
    return CHROMA_DIR.exists()


def _get_collection():
    if chromadb is None:
        raise RuntimeError("chromadb 未安裝")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        return client.get_collection(COLLECTION)
    except Exception:
        # If not created yet, raise for clarity
        raise RuntimeError("找不到 Chroma collection，請先執行 scripts/build_vectors.py")


_HF_CACHE: Dict[str, object] = {}


def _read_api_key() -> Optional[str]:
    path = (ROOT / "api key.txt")
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if "openai" in ln.lower() and i + 1 < len(lines):
                return lines[i + 1]
        for ln in lines:
            if ln.startswith(("sk-", "sk-proj-", "sk_projec")):
                return ln
        if lines:
            return lines[0]
    except Exception:
        return None
    return None


def _format_query_for_model(query: str, model_name: Optional[str]) -> str:
    if not model_name:
        return query
    lower = model_name.lower()
    if "bge" in lower:
        return BGE_QUERY_INSTRUCTION + query
    if "e5" in lower:
        return "query: " + query
    return query


def _ensure_query_embedding(query: str, col) -> List[float]:
    meta = getattr(col, "metadata", None) or {}
    backend = meta.get("backend")
    model_name = meta.get("model_name")
    n_results = 1
    if backend == "openai":
        from openai import OpenAI
        key = _read_api_key()
        if not key:
            raise RuntimeError("找不到 OpenAI 金鑰，無法使用向量檢索（openai 後端）。")
        client = OpenAI(api_key=key)
        resp = client.embeddings.create(model=model_name or "text-embedding-3-small", input=[query])
        return resp.data[0].embedding
    else:
        # default to HF/Flag local model if not specified
        model_name = model_name or "BAAI/bge-large-zh-v1.5"
        from sentence_transformers import SentenceTransformer

        key = f"hf::{model_name}"
        if key not in _HF_CACHE:
            _HF_CACHE[key] = SentenceTransformer(model_name)
        model = _HF_CACHE[key]
        text = _format_query_for_model(query, model_name)
        vec = model.encode([text], normalize_embeddings=True)[0]
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)


def warmup() -> Dict[str, Optional[str]]:
    """Pre-load embedding model according to collection metadata."""
    info: Dict[str, Optional[str]] = {"backend": None, "model_name": None}
    try:
        col = _get_collection()
        meta = getattr(col, "metadata", None) or {}
        backend = meta.get("backend")
        model_name = meta.get("model_name")
        info["backend"] = backend
        info["model_name"] = model_name
        if backend == "openai":
            # No local warmup needed
            return info
        # HF backend: load model and perform a tiny encode
        model_name = model_name or "BAAI/bge-large-zh-v1.5"
        from sentence_transformers import SentenceTransformer
        key = f"hf::{model_name}"
        if key not in _HF_CACHE:
            _HF_CACHE[key] = SentenceTransformer(model_name)
        model = _HF_CACHE[key]
        text = "query: 測試" if "e5" in model_name.lower() else "測試"
        _ = model.encode([text], normalize_embeddings=True)
        return info
    except Exception:
        return info


def search(query: str, top_k: int = 5) -> List[Tuple[float, Dict]]:
    col = _get_collection()
    try:
        # Prefer explicit query embeddings to avoid relying on server-side functions
        qvec = _ensure_query_embedding(query, col)
        res = col.query(query_embeddings=[qvec], n_results=max(1, min(20, top_k)))
    except Exception:
        # Fallback to query_texts if embedding function is configured
        res = col.query(query_texts=[query], n_results=max(1, min(20, top_k)))
    out: List[Tuple[float, Dict]] = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances") or res.get("embeddings")  # distances for cosine
    scores = []
    if dists and isinstance(dists, list) and dists and isinstance(dists[0], list):
        # For cosine, smaller distance -> higher similarity. Convert to similarity score.
        distances = dists[0]
        # Normalize to similarity ~ 1 - distance (rough)
        scores = [1.0 - float(d) for d in distances]
    else:
        scores = [1.0] * len(ids)

    for i in range(len(ids)):
        meta = metas[i] if metas else {}
        out.append(
            (
                float(scores[i]),
                {
                    "id": ids[i],
                    "source_file": meta.get("source_file", ""),
                    "heading": meta.get("heading", ""),
                    "text": docs[i],
                    "law_id": meta.get("law_id"),
                    "title": meta.get("title"),
                    "last_amended": meta.get("last_amended"),
                    "law_version": meta.get("law_version"),
                    "source_url": meta.get("source_url"),
                    "checksum": meta.get("checksum"),
                    "article_no": meta.get("article_no"),
                },
            )
        )
    return out



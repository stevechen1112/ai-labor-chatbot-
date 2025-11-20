from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "data" / "laws"
INDEX_DIR = ROOT / "data" / "index"
INDEX_PATH = INDEX_DIR / "index.json"
META_PATH = INDEX_DIR / "metadata.json"


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


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
    text = text.lower()
    ascii_tokens = re.findall(r"[a-z0-9]+", text)
    ascii_tokens = [t for t in ascii_tokens if len(t) >= 2]
    cjk_seq = [ch for ch in text if is_cjk(ch)]
    cjk_unigrams = cjk_seq
    cjk_bigrams = [cjk_seq[i] + cjk_seq[i + 1] for i in range(len(cjk_seq) - 1)]
    return ascii_tokens + cjk_unigrams + cjk_bigrams


ARTICLE_HEAD_RE = re.compile(r"^\u7B2C.{0,12}\u689D", re.MULTILINE)  # 第…條
CHAPTER_HEAD_RE = re.compile(r"^\u7B2C.{0,8}\u7AE0", re.MULTILINE)  # 第…章


def extract_article_no(heading: str) -> str:
    m = re.match(r"^\u7B2C\s*(.+?)\s*\u689D", heading.strip())
    return m.group(1) if m else ""


def split_into_chunks(content: str):
    positions = [m.start() for m in ARTICLE_HEAD_RE.finditer(content)]
    chunks = []
    if positions:
        chap_marks = [(m.start(), content[m.start():m.end()].strip()) for m in CHAPTER_HEAD_RE.finditer(content)]

        def chapter_at(pos: int) -> str:
            prev = ""
            for p, ch in chap_marks:
                if p <= pos:
                    prev = ch
                else:
                    break
            return prev

        positions.append(len(content))
        for i in range(len(positions) - 1):
            start, end = positions[i], positions[i + 1]
            chunk = content[start:end].strip()
            if chunk:
                heading = chunk.splitlines()[0].strip()
                chunks.append({
                    "heading": heading,
                    "text": chunk,
                    "chapter": chapter_at(start),
                    "article_no": extract_article_no(heading),
                })
        return chunks

    md_positions = [m.start() for m in re.finditer(r"^#{1,4}\s+.+$", content, flags=re.MULTILINE)]
    if md_positions:
        md_positions.append(len(content))
        for i in range(len(md_positions) - 1):
            start, end = md_positions[i], md_positions[i + 1]
            chunk = content[start:end].strip()
            if chunk:
                heading = chunk.splitlines()[0].lstrip('#').strip()
                chunks.append({
                    "heading": heading,
                    "text": chunk,
                    "chapter": "",
                    "article_no": extract_article_no(heading),
                })
        return chunks

    head = content.splitlines()[0].strip() if content.strip() else ""
    return [{"heading": head, "text": content, "chapter": "", "article_no": extract_article_no(head)}]


def build_index():
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    # Load metadata if present
    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    files = sorted([p for p in LAWS_DIR.glob("*.md") if p.is_file()])
    if not files:
        raise SystemExit(f"No Markdown files found in {LAWS_DIR}")

    docs = []
    df = Counter()
    for path in files:
        content = read_text(path)
        for idx, ch in enumerate(split_into_chunks(content)):
            doc_id = f"{path.name}:{idx}"
            tf = Counter(tokenize(ch["text"]))
            for t in tf:
                df[t] += 1
            m = meta.get(path.name, {}) if isinstance(meta, dict) else {}
            docs.append({
                "id": doc_id,
                "source_file": path.name,
                "heading": ch["heading"],
                "text": ch["text"],
                "tf": {k: int(v) for k, v in tf.items()},
                # metadata for traceability
                "title": m.get("title"),
                "law_id": m.get("law_id"),
                "last_amended": m.get("last_amended"),
                "law_version": m.get("law_version"),
                "source_url": m.get("source_url"),
                "checksum": m.get("checksum"),
                # structure
                "chapter": ch.get("chapter", ""),
                "article_no": ch.get("article_no", ""),
            })

    index = {
        "meta": {
            "num_docs": len(docs),
            "df": {k: int(v) for k, v in df.items()},
            "tokenization": "ascii>=2 + CJK uni/bi",
            "chunking": "article|markdown|fallback",
            "metadata_fields": ["law_id","last_amended","law_version","source_url","checksum","chapter","article_no"],
        },
        "docs": docs,
    }

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    print(f"Indexed {index['meta']['num_docs']} chunks from {len(files)} files -> {INDEX_PATH}")


if __name__ == "__main__":
    build_index()

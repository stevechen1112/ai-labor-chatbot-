from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional, Tuple, Dict

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "data" / "laws"
WHITESPACE_CHARS = {" ", "\t", "\r", "\n", "\u3000"}


def _strip_spaces(text: str) -> str:
    return "".join(ch for ch in text if ch not in WHITESPACE_CHARS)


def _normalize_law_key(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return _strip_spaces(normalized).lower()


RAW_LAW_ALIASES: Dict[str, str] = {
    "性平法": "性別平等工作法",
    "性別工作平等法": "性別平等工作法",  # 舊稱
    "性別平等法": "性別平等工作法",
}

LAW_ALIAS_MAP: Dict[str, str] = {
    _normalize_law_key(alias): target for alias, target in RAW_LAW_ALIASES.items()
}


def _apply_law_alias(query: str) -> str:
    normalized = _normalize_law_key(query)
    if normalized in LAW_ALIAS_MAP:
        return LAW_ALIAS_MAP[normalized]
    return query


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def arabic_to_cjk(num: int) -> str:
    units = "零一二三四五六七八九"
    tens = "十"
    if num <= 0:
        return str(num)
    if num < 10:
        return units[num]
    if num < 20:
        return tens + (units[num - 10] if num != 10 else "")
    if num < 100:
        d, r = divmod(num, 10)
        return units[d] + tens + (units[r] if r else "")
    h, r = divmod(num, 100)
    prefix = units[h] + "百"
    if r == 0:
        return prefix
    if r < 10:
        return prefix + "零" + units[r]
    if r < 20:
        return prefix + tens + (units[r - 10] if r != 10 else "")
    t, u = divmod(r, 10)
    return prefix + units[t] + tens + (units[u] if u else "")


def build_article_regex(no: str) -> re.Pattern:
    no = no.strip()
    alts = [re.escape(no)]
    if no.isdigit():
        try:
            n = int(no)
            alts.append(arabic_to_cjk(n))
        except Exception:
            pass
    pattern = r"^第\s*(" + "|".join(alts) + r")\s*條\s*$"
    return re.compile(pattern, flags=re.MULTILINE)


def fuzzy_pick_file(query: str) -> Optional[Path]:
    query = query.strip()
    files = list(LAWS_DIR.glob("*.md"))
    if not query or not files:
        return None

    query = _apply_law_alias(query)
    normalized_query = _normalize_law_key(query)

    # 1) Exact match優先：避免「性別平等工作法」被施行細則搶走
    exact_matches: list[Tuple[int, Path]] = []
    for p in files:
        normalized_name = _normalize_law_key(p.stem)
        if normalized_name == normalized_query:
            exact_matches.append((len(p.stem), p))
    if exact_matches:
        exact_matches.sort(key=lambda item: item[0])
        return exact_matches[0][1]

    # 2) 模糊評分：保留舊邏輯，但加入長度差異與 NFKC 正規化
    best: Tuple[int, int, Path] | None = None
    query_tokens = set(ch for ch in _strip_spaces(query))
    for p in files:
        name = p.stem
        normalized_name = _normalize_law_key(name)
        score = 0
        if query and query in name:
            score += 10
        if normalized_query and normalized_query in normalized_name:
            score += 8
        try:
            first = read_text(p).splitlines()[0]
            if query in first:
                score += 6
        except Exception:
            pass
        score += len([ch for ch in _strip_spaces(name) if ch in query_tokens])
        length_penalty = abs(len(normalized_name) - len(normalized_query))
        ranking_key = (score, -length_penalty)
        if best is None or ranking_key > (best[0], best[1]):
            best = (ranking_key[0], ranking_key[1], p)
    return best[2] if best and best[0] > 0 else None


def find_article(law_query: str, article_no: str) -> Optional[dict]:
    target = fuzzy_pick_file(law_query)
    if not target:
        return None
    content = read_text(target)
    rx = build_article_regex(article_no)
    lines = content.splitlines()
    match_idx = None
    for i, ln in enumerate(lines):
        if rx.match(ln.strip()):
            match_idx = i
            break
    if match_idx is None:
        loose = re.compile(r"^第\s*.*" + re.escape(article_no) + r".*條\s*$")
        for i, ln in enumerate(lines):
            if loose.match(ln.strip()):
                match_idx = i
                break
    if match_idx is None:
        return None
    body = [lines[match_idx]]
    for j in range(match_idx + 1, len(lines)):
        if re.match(r"^第.{0,12}條\s*$", lines[j]):
            break
        body.append(lines[j])
    text = "\n".join(body).strip()
    return {"law_file": target.name, "heading": lines[match_idx].strip(), "text": text}

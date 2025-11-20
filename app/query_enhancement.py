"""Query enhancement utilities used by the retrieval pipeline.

這個模組提供 QueryEnhancer 類別，並在 Phase 2.6 中協助：
1. 透過 HyDE 生成假設性條文，提高語意檢索精準度。
2. 將複雜問題拆解成子題，避免 topic mis-classification。
3. 產出語意擴充查詢，讓多路徑檢索有更多切入點。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import json
import time

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:  # pragma: no cover
    OpenAI = None
    OPENAI_AVAILABLE = False

ROOT = Path(__file__).resolve().parents[1]
API_KEY_PATH = ROOT / "api key.txt"


def _read_api_key() -> Optional[str]:
    """讀取 OpenAI API 金鑰，並容忍常見的 key 檔格式。"""

    if not API_KEY_PATH.exists():
        return None

    encodings = ("utf-8", "cp950", "big5")
    for enc in encodings:
        try:
            content = API_KEY_PATH.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            content = None
    else:  # pragma: no cover - 若皆失敗
        content = None

    if not content:
        return None

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if "openai" in line.lower() and i + 1 < len(lines):
            return lines[i + 1]

    for line in lines:
        if line.startswith(("sk-", "sk-proj-")):
            return line

    return lines[0] if lines else None


class QueryEnhancer:
    """提供 HyDE、查詢拆解與查詢擴充等能力。"""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-5-mini") -> None:
        if not OPENAI_AVAILABLE:
            raise RuntimeError("OpenAI package not installed")

        self.api_key = api_key or _read_api_key()
        if not self.api_key:
            raise RuntimeError("OpenAI API key not found")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        print("[QueryEnhancer] Initialized with OpenAI API")

    def _chat(self, messages: List[dict], max_tokens: int) -> Optional[str]:
        """Call the LLM, switching to Responses API for gpt-5 models."""
        adjusted_tokens = max_tokens
        
        if self.model.startswith('gpt-5'):
            # gpt-5-mini 使用 Responses API
            adjusted_tokens = max(adjusted_tokens, 1024)
            try:
                response = self.client.responses.create(
                    model=self.model,
                    input=messages,
                    temperature=1.0,
                    max_output_tokens=adjusted_tokens,
                )
                text = self._response_to_text(response)
            except Exception as exc:  # pragma: no cover
                print(f"[QueryEnhancer] LLM call failed: {exc}")
                return None
        else:
            # 其他模型使用 Chat Completions API
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=1.0,
                    max_completion_tokens=adjusted_tokens,
                )
                text = response.choices[0].message.content
            except Exception as exc:  # pragma: no cover
                print(f"[QueryEnhancer] LLM call failed: {exc}")
                return None

        if not text:
            return None
        return text.strip()

    @staticmethod
    def _response_to_text(response) -> Optional[str]:
        """Extract plain text from the Responses API payload."""
        text = getattr(response, 'output_text', None)
        if text:
            return text.strip()
        chunks = []
        for item in getattr(response, 'output', []) or []:
            content_list = getattr(item, 'content', None)
            if not content_list:
                continue
            for content in content_list:
                piece = getattr(content, 'text', None)
                if piece is None and isinstance(content, dict):
                    piece = content.get('text')
                if piece:
                    chunks.append(piece)
        if not chunks:
            return None
        return '\n\n'.join(chunks).strip()

    @staticmethod
    def _extract_json_list(text: Optional[str]) -> Optional[List[str]]:
        if not text:
            return None

        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None

        snippet = text[start : end + 1]
        try:
            data = json.loads(snippet)
        except json.JSONDecodeError:
            return None

        cleaned = [item.strip() for item in data if isinstance(item, str) and item.strip()]
        return cleaned or None

    def generate_hypothetical_document(self, query: str, doc_type: str = "法規說明") -> str:
        """使用 HyDE 生成假設性條文。"""

        system_prompt = "你是台灣勞資法律研究員，負責撰寫條文摘要。"
        user_prompt = f"""使用者問題：{query}

請根據 {doc_type} 口吻，撰寫 120-180 字的段落，描述最可能適用的關鍵法規與條文：
1. 儘量引用條號（例如《勞基法》第XX條）。
2. 陳述條文要點與適用條件。
3. 若資訊不足也須說明推論依據。

僅輸出條文說明本身。"""

        start = time.time()
        result = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=320,
        )
        elapsed = time.time() - start
        print(f"[HyDE] Generated hypothetical document in {elapsed:.2f}s")
        return result or query

    def decompose_query(self, query: str, max_subqueries: int = 3) -> List[str]:
        """將複雜問題拆解為多個子題。"""

        normalized = query.strip()
        if len(normalized) < 15:
            return [normalized]

        system_prompt = "你是勞資諮詢系統的查詢規劃師。"
        user_prompt = f"""請將下列勞資法問題拆解為最多 {max_subqueries} 個子題：

{normalized}

輸出需求：
1. 每個子題都需包含核心法律面向。
2. 若原問題單純，可直接輸出原問題。
3. 使用 JSON 陣列格式，例如 ["子題A", "子題B"]."""

        result = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=320,
        )

        parsed = self._extract_json_list(result)
        if not parsed:
            return [normalized]

        return parsed[:max_subqueries]

    def expand_query(self, query: str, expansion_type: str = "synonyms") -> List[str]:
        """生成多種語意擴充查詢。"""

        type_instruction = {
            "synonyms": "請提供 2-3 個語意接近的替代表達。",
            "related": "請提供 2-3 個相關議題的查詢方式。",
            "specific": "請提供 2-3 個更具體的檢索語句。",
        }.get(expansion_type, "請提供 2-3 個語意接近的替代表達。")

        system_prompt = "你是檢索策略顧問，負責提供多種查詢語句。"
        user_prompt = f"""原始問題：{query}
{type_instruction}
僅輸出 JSON 陣列，例如 ["查詢1", "查詢2"]."""

        result = self._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=200,
        )

        parsed = self._extract_json_list(result)
        if not parsed:
            return [query]

        return [query] + parsed[:3]

    def should_use_hyde(self, query: str) -> bool:
        """判斷是否適合啟用 HyDE。"""

        abstract_markers = ["為什麼", "原因", "概念", "如何理解", "意義", "定義"]
        is_abstract = any(marker in query for marker in abstract_markers)

        long_query = len(query) > 40
        has_legal_keywords = any(kw in query for kw in ["勞基法", "條", "規定", "權利", "義務", "契約"])

        return is_abstract or (long_query and not has_legal_keywords)

    def should_decompose(self, query: str) -> bool:
        """判斷是否應該拆解查詢。"""

        question_marks = query.count("？") + query.count("?")
        if question_marks > 1:
            return True

        connectors = ["以及", "或", "還有", "同時", "並", "而且"]
        connector_hits = sum(1 for conn in connectors if conn in query)

        return len(query) > 40 and connector_hits >= 2


_ENHANCER_INSTANCE: Optional[QueryEnhancer] = None


def get_query_enhancer() -> QueryEnhancer:
    """取得單例查詢增強器。"""

    global _ENHANCER_INSTANCE
    if _ENHANCER_INSTANCE is None:
        _ENHANCER_INSTANCE = QueryEnhancer()
    return _ENHANCER_INSTANCE


def is_available() -> bool:
    """確認模組是否具備初始化條件。"""

    return OPENAI_AVAILABLE and API_KEY_PATH.exists()

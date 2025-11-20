"""
智能檢索模組 - Phase 2.5 核心功能

功能：
1. 前置分析（PreRetrievalAnalyzer）- 讓 LLM 分析問題涉及哪些法律面向
2. 迭代式檢索（IterativeRetriever）- LLM 反覆檢查並補足缺失的法條
3. 最終驗證（PostRetrievalValidator）- 生成答案前最後確認

作者：AI Assistant
版本：2.5.0
日期：2025-11-14
"""

from __future__ import annotations

import sys
import io
# 修復 Windows 編碼問題
if sys.platform == 'win32' and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import json
import time
from typing import List, Dict, Optional
import re
from pydantic import BaseModel

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


# ============================================================
# Pydantic Models
# ============================================================

class LegalAspect(BaseModel):
    """法律面向"""
    type: str  # "程序" | "實體權利" | "行政義務" | "罰則"
    description: str
    suggested_laws: List[str]


class PreAnalysisResult(BaseModel):
    """前置分析結果"""
    aspects: List[LegalAspect]
    suggested_laws: List[str]
    estimated_complexity: str  # "simple" | "medium" | "complex"
    reasoning: str


class RetrievalCheckResult(BaseModel):
    """檢索完整性檢查結果"""
    is_sufficient: bool
    reason: str
    missing_articles: List[Dict[str, str]]  # [{"law": "...", "article": "...", "reason": "..."}]
    confidence: float


class FinalValidationResult(BaseModel):
    """最終驗證結果"""
    status: str  # "PASS" | "INSUFFICIENT" | "WARNING"
    concerns: List[str]
    missing_aspects: List[str]


# ============================================================
# Main Intelligent Retriever Class
# ============================================================

class IntelligentRetriever:
    """
    智能檢索器（Phase 2.5 核心）
    
    使用 LLM 參與檢索過程，自動發現並補足缺失的法條。
    
    三層機制：
    1. 前置分析：理解問題涉及的法律面向
    2. 迭代式檢索：反覆檢查並補充缺失的法條
    3. 最終驗證：生成答案前的品質把關
    """
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """
        初始化智能檢索器
        
        Args:
            api_key: OpenAI API 金鑰
            model: LLM 模型名稱（默認 gpt-4o-mini）
        """
        if not OPENAI_AVAILABLE:
            raise RuntimeError("OpenAI package not installed")
        
        if not api_key:
            raise RuntimeError("OpenAI API key not provided")
        
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_iterations = 2  # 最多迭代 2 輪（降低延遲）
        self.confidence_threshold = 0.8  # 高信心時提前退出
        self.last_iterations = 0
        self.last_forced_additions = 0
        
        print(f"[IntelligentRetriever] Initialized with model: {self.model}")
    
    # ========== 第一層：前置分析 ==========
    
    def pre_analyze(self, query: str) -> PreAnalysisResult:
        """
        第一層：前置智能分析
        
        讓 LLM 分析問題涉及的法律面向（程序、實體權利、行政義務、罰則等），
        並建議應該檢索哪些法律。
        
        Args:
            query: 用戶查詢
            
        Returns:
            PreAnalysisResult: 分析結果
        """
        print(f"[Phase 2.5] 第一層：前置分析")
        
        # 🚀 優化：簡化 prompt 減少 token 數
        prompt = f"""你是台灣勞動法律專家。分析問題涉及的法律面向。

問題：{query}

分析面向：程序、實體權利、行政義務、責任

JSON 格式：
{{
    "aspects": [{{"type": "程序", "description": "簡述", "suggested_laws": ["法律名稱"]}}],
    "suggested_laws": ["勞動基準法"],
    "estimated_complexity": "medium",
    "reasoning": "簡要說明"
}}
"""
        
        try:
            start_time = time.time()
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是台灣勞動法律專家，擅長分析法律問題的多維度。回答必須是有效的 JSON 格式。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            elapsed = time.time() - start_time
            
            result_json = json.loads(response.choices[0].message.content)
            result = PreAnalysisResult(**result_json)
            
            print(f"[Phase 2.5] ✓ 前置分析完成 ({elapsed:.2f}s)")
            print(f"[Phase 2.5]   識別 {len(result.aspects)} 個法律面向")
            print(f"[Phase 2.5]   建議法律: {', '.join(result.suggested_laws)}")
            print(f"[Phase 2.5]   複雜度: {result.estimated_complexity}")
            
            return result
        
        except Exception as e:
            print(f"[Phase 2.5] ✗ 前置分析失敗: {e}")
            # 降級：返回簡單的分析結果
            return PreAnalysisResult(
                aspects=[
                    LegalAspect(
                        type="實體權利",
                        description="基本勞動權益",
                        suggested_laws=["勞動基準法"]
                    )
                ],
                suggested_laws=["勞動基準法"],
                estimated_complexity="simple",
                reasoning="分析失敗，使用默認設定"
            )
    
    # ========== 第二層：迭代式檢索 ==========
    
    def iterative_retrieve(
        self, 
        query: str, 
        pre_analysis: PreAnalysisResult,
        initial_results: List[Dict]
    ) -> List[Dict]:
        """
        第二層：迭代式檢索
        
        LLM 反覆檢查當前檢索結果是否完整，如果不足則補檢索缺失的法條。
        
        Args:
            query: 用戶查詢
            pre_analysis: 前置分析結果
            initial_results: 初始檢索結果（dict 格式）
            
        Returns:
            增強後的檢索結果
        """
        print(f"[Phase 2.5] 第二層：迭代式檢索")
        
        results = initial_results.copy()
        iteration = 0
        forced_total = 0
        self.last_iterations = 0
        self.last_forced_additions = 0
        
        while iteration < self.max_iterations:
            iteration += 1
            self.last_iterations = iteration
            print(f"[Phase 2.5] 第 {iteration} 輪檢查...")
            
            # 請 LLM 檢查當前檢索結果是否足夠
            check_result = self._check_retrieval_completeness(
                query, 
                pre_analysis, 
                results
            )
            
            # 如果 LLM 認為足夠，結束迭代
            if check_result.is_sufficient:
                print(f"[Phase 2.5] ✓ LLM 確認檢索完整 (confidence: {check_result.confidence:.2f})")
                break
            
            if check_result.confidence >= self.confidence_threshold and iteration > 1:
                print(f"[Phase 2.5] ⚡ Confidence 達 {check_result.confidence:.2f}，提前結束")
                break
            
            # LLM 認為不足，補檢索缺少的法條
            print(f"[Phase 2.5] ⚠️ LLM 發現缺少 {len(check_result.missing_articles)} 條法規")
            
            補充成功 = 0
            for missing in check_result.missing_articles:
                # 檢查是否已經存在（避免重複補充）
                normalized_article = self._normalize_article_no(missing.get("article", ""))
                already_exists = False
                for r in results:
                    existing_article = self._normalize_article_no(str(r.get("article_no", "")))
                    if (r.get("law_name") == missing["law"] or r.get("law_id") == missing["law"]) and \
                       existing_article == normalized_article:
                        already_exists = True
                        break
                
                if already_exists:
                    print(f"[Phase 2.5]   ➖ 已存在：{missing['law']} 第 {missing['article']} 條")
                    continue
                
                forced = self._force_retrieve(missing["law"], normalized_article)
                if forced:
                    # 插入到結果最前面（高優先級）
                    results.insert(0, forced)
                    print(f"[Phase 2.5]   ✓ 補檢索：{missing['law']} 第 {missing['article']} 條")
                    補充成功 += 1
                    forced_total += 1
                else:
                    print(f"[Phase 2.5]   ✗ 無法檢索：{missing['law']} 第 {missing['article']} 條")
            
            # 如果這輪沒有成功補充任何法條，避免無限循環
            if 補充成功 == 0:
                print(f"[Phase 2.5] ⚠️ 無法補充更多法條，結束迭代")
                break
        
        if iteration >= self.max_iterations:
            print(f"[Phase 2.5] ⚠️ 達到最大迭代次數 ({self.max_iterations})，可能仍有遺漏")
        
        self.last_forced_additions = forced_total
        print(f"[Phase 2.5] ✓ 迭代式檢索完成，最終結果: {len(results)} 條")
        return results
    
    def _check_retrieval_completeness(
        self,
        query: str,
        pre_analysis: PreAnalysisResult,
        results: List[Dict]
    ) -> RetrievalCheckResult:
        """
        讓 LLM 檢查檢索結果是否完整
        
        Args:
            query: 用戶查詢
            pre_analysis: 前置分析結果
            results: 當前檢索結果
            
        Returns:
            RetrievalCheckResult: 檢查結果
        """
        # 格式化當前檢索結果
        citations_summary = self._format_citations_for_check(results)
        aspects_summary = "\n".join([
            f"- {a.type}：{a.description}" for a in pre_analysis.aspects
        ])
        
        # 🚀 優化：簡化 prompt
        prompt = f"""台灣勞動法專家。判斷檢索結果是否完整。

問題：{query}

面向：{aspects_summary}

已檢索：
{citations_summary}

判斷是否完整？缺少哪些法條？

JSON：
{{
    "is_sufficient": false,
    "reason": "缺少XX",
    "missing_articles": [{{"law": "法律", "article": "XX", "reason": "原因"}}],
    "confidence": 0.85
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是檢索品質檢查專家，專門判斷法條檢索是否完整。回答必須是有效的 JSON 格式。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            result_json = json.loads(response.choices[0].message.content)
            result = RetrievalCheckResult(**result_json)
            
            return result
        
        except Exception as e:
            print(f"[Phase 2.5] ✗ 檢查失敗: {e}")
            # 降級：假設檢索已經足夠
            return RetrievalCheckResult(
                is_sufficient=True,
                reason="檢查失敗，假設檢索足夠",
                missing_articles=[],
                confidence=0.5
            )
    
    def _format_citations_for_check(self, results: List[Dict]) -> str:
        """格式化檢索結果供 LLM 檢查"""
        lines = []
        for i, r in enumerate(results[:10], 1):  # 只列出前 10 條
            law = r.get("law_name") or r.get("law_id", "未知法律")
            art = r.get("article_no", "?")
            heading = r.get("heading", "")
            lines.append(f"{i}. {law} 第 {art} 條：{heading}")
        
        if len(results) > 10:
            lines.append(f"... 以及其他 {len(results) - 10} 條")
        
        return "\n".join(lines) if lines else "（尚無檢索結果）"
    
    def _force_retrieve(self, law_name: str, article_no: str) -> Optional[Dict]:
        """
        強制檢索指定法條
        
        Args:
            law_name: 法律名稱
            article_no: 條號
            
        Returns:
            檢索到的法條（dict 格式），如果失敗則返回 None
        """
        try:
            from .articles import find_article
            
            result = find_article(law_name, article_no)
            if result:
                return {
                    "id": f"{law_name}_{article_no}",
                    "law_name": law_name,
                    "law_id": law_name,
                    "article_no": article_no,
                    "heading": result.get("heading", f"第 {article_no} 條"),
                    "text": result.get("text", ""),
                    "source_file": result.get("law_file", ""),
                    "source": "intelligent_retrieval_forced"
                }
            return None
        except Exception as e:
            print(f"[Phase 2.5] ✗ 強制檢索失敗 ({law_name} 第 {article_no} 條): {e}")
            return None

    def _normalize_article_no(self, article: str) -> str:
        """
        正規化條號：移除「第」「條」等字，並嘗試轉換中文數字
        """
        if not article:
            return article
        # 先嘗試擷取數字
        digits = re.findall(r"[0-9]+", article)
        if digits:
            return digits[0]
        # 嘗試中文數字
        chinese = re.sub(r"[第條\s]", "", article)
        value = self._chinese_to_int(chinese)
        if value is not None:
            return str(value)
        return article.strip()

    def _chinese_to_int(self, text: str) -> Optional[int]:
        if not text:
            return None
        mapping = {
            "零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9
        }
        text = text.replace("兩", "二")
        if "十" in text:
            parts = text.split("十")
            tens_part = parts[0]
            ones_part = parts[1] if len(parts) > 1 else ""
            tens = mapping.get(tens_part[-1], 1) if tens_part else 1
            ones = mapping.get(ones_part[0], 0) if ones_part else 0
            return tens * 10 + ones
        total = 0
        for ch in text:
            if ch not in mapping:
                return None
            total = total * 10 + mapping[ch]
        return total
    
    # ========== 第三層：最終驗證 ==========
    
    def final_validate(
        self,
        query: str,
        results: List[Dict],
        pre_analysis: PreAnalysisResult
    ) -> FinalValidationResult:
        """
        第三層：最終驗證
        
        生成答案前，LLM 最後確認一次檢索結果是否完整。
        
        Args:
            query: 用戶查詢
            results: 檢索結果
            pre_analysis: 前置分析結果
            
        Returns:
            FinalValidationResult: 驗證結果
        """
        print(f"[Phase 2.5] 第三層：最終驗證")
        
        citations_summary = self._format_citations_for_check(results)
        aspects_summary = "\n".join([
            f"- {a.type}：{a.description}" for a in pre_analysis.aspects
        ])
        
        # 🚀 優化：簡化 prompt
        prompt = f"""台灣勞動法專家。最後確認法條是否完整。

問題：{query}
面向：{aspects_summary}
法條：{citations_summary}

能完整回答嗎？有遺漏嗎？

JSON：
{{
    "status": "PASS",
    "concerns": [],
    "missing_aspects": []
}}
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是法律答案品質檢查專家。回答必須是有效的 JSON 格式。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            result_json = json.loads(response.choices[0].message.content)
            result = FinalValidationResult(**result_json)
            
            print(f"[Phase 2.5] ✓ 最終驗證: {result.status}")
            if result.concerns:
                print(f"[Phase 2.5]   ⚠️ Concerns: {result.concerns}")
            
            return result
        
        except Exception as e:
            print(f"[Phase 2.5] ✗ 驗證失敗: {e}")
            # 降級：假設通過
            return FinalValidationResult(
                status="WARNING",
                concerns=["最終驗證失敗，請謹慎參考答案"],
                missing_aspects=[]
            )


# ============================================================
# Global Instance (Singleton)
# ============================================================

_INTELLIGENT_RETRIEVER_INSTANCE: Optional[IntelligentRetriever] = None


def get_intelligent_retriever(api_key: Optional[str] = None, model: str = "gpt-4o-mini") -> IntelligentRetriever:
    """
    獲取智能檢索器實例（單例模式）
    
    Args:
        api_key: OpenAI API 金鑰
        model: LLM 模型名稱
        
    Returns:
        IntelligentRetriever 實例
    """
    global _INTELLIGENT_RETRIEVER_INSTANCE
    
    if _INTELLIGENT_RETRIEVER_INSTANCE is None:
        if not api_key:
            raise RuntimeError("API key required for first initialization")
        _INTELLIGENT_RETRIEVER_INSTANCE = IntelligentRetriever(api_key=api_key, model=model)
    
    return _INTELLIGENT_RETRIEVER_INSTANCE


def is_available() -> bool:
    """檢查智能檢索器是否可用"""
    return OPENAI_AVAILABLE


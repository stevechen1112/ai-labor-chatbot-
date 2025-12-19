"""審核員代理：質量控制與驗證"""
from __future__ import annotations

from typing import Dict, List, Optional
import re
from pydantic import BaseModel

from .receptionist import AnalysisResult
from .lawyer import LawyerResponse
from ..citation_validator import CitationValidator
from ..law_guides import LawGuideEngine, TopicMatch


class ReviewResult(BaseModel):
    """審核結果"""
    decision: str  # PASS/REJECT/WARN
    citation_valid: Dict  # 引用驗證結果
    quality_score: float  # 0-1
    feedback: str  # 反饋說明
    errors: List[str] = []  # 錯誤列表
    warnings: List[str] = []  # 警告列表


class SupervisorAgent:
    """
    審核員代理：負責質量控制與驗證
    
    職責：
    1. 引用驗證（整合 Phase 0）
    2. 邏輯完整性檢查
    3. 答案質量評估
    4. 決策（通過/退回/警告）
    """
    
    def __init__(self):
        # 整合 Phase 0 的引用驗證器
        self.citation_validator = CitationValidator()
        try:
            self.law_guide_engine = LawGuideEngine()
        except Exception as exc:
            print(f"[Supervisor] Warning: failed to load law guides: {exc}")
            self.law_guide_engine = None
        
        # 質量閾值
        self.quality_threshold = 0.7
        self.confidence_threshold = 0.6
    
    def review(
        self,
        lawyer_response: LawyerResponse,
        citations: List[Dict],
        analysis: AnalysisResult,
        query: str
    ) -> ReviewResult:
        """
        審核律師生成的答案
        
        Args:
            lawyer_response: 律師代理的回應
            citations: 原始引用
            analysis: 接待員分析結果
            query: 原始查詢
        """
        errors = []
        warnings = []
        
        # 1. 引用驗證（Phase 0）
        citation_valid = self._validate_citations(
            lawyer_response,
            citations,
            analysis,
            query
        )
        
        # 收集引用驗證錯誤/警告
        if not citation_valid.get("exists", True):
            errors.append("引用的條文不存在於資料庫中")
        
        if citation_valid.get("conflicts", False):
            errors.append("引用的條文之間存在邏輯衝突")
        
        if not citation_valid.get("content_match", True):
            warnings.append("引用內容可能與官方版本有細微差異")
        
        # 🆕 Phase 2.7: 主題-條文一致性檢查
        topic_citation_issues = self._check_topic_citation_consistency(
            query, citations
        )
        if topic_citation_issues.get("mismatch"):
            warnings.append(
                f"引用條文可能與查詢主題不一致：{topic_citation_issues['mismatch']}"
            )
        if topic_citation_issues.get("missing_definition"):
            warnings.append(
                f"查詢涉及定義性問題，建議補充：{topic_citation_issues['missing_definition']}"
            )
        
        # 2. 必備條文檢查
        missing_core = self._check_required_articles(analysis.topics, citations)
        if missing_core:
            errors.append(
                "缺少關鍵引用：" + "、".join(missing_core)
            )
        
        # 3. 邏輯完整性檢查
        logic_complete = self._check_logic_completeness(
            lawyer_response,
            analysis
        )
        
        if not logic_complete:
            warnings.append("答案可能未完整覆蓋所有問題面向")
        
        # 4. 答案質量評估
        quality_score = self._assess_quality(
            lawyer_response,
            citation_valid,
            logic_complete
        )
        
        # 5. 決策
        decision, feedback = self._make_decision(
            citation_valid,
            quality_score,
            lawyer_response.confidence,
            errors,
            warnings
        )
        
        return ReviewResult(
            decision=decision,
            citation_valid=citation_valid,
            quality_score=quality_score,
            feedback=feedback,
            errors=errors,
            warnings=warnings
        )
    
    @staticmethod
    def _normalize_law_key(name: Optional[str]) -> str:
        if not name:
            return ""
        cleaned = re.sub(r"\s+", "", name)
        return cleaned.lower()

    def _check_topic_citation_consistency(
        self,
        query: str,
        citations: List[Dict]
    ) -> Dict:
        """
        🆕 Phase 2.7: 主題-條文一致性檢查
        
        使用多主題匹配來確保引用的條文與查詢主題一致。
        
        Returns:
            {
                "mismatch": str or None,  # 不一致描述
                "missing_definition": str or None  # 缺少的定義性條文
            }
        """
        result = {"mismatch": None, "missing_definition": None}
        
        if not self.law_guide_engine:
            return result
        
        # 使用多主題匹配
        matched_topics: List[TopicMatch] = self.law_guide_engine.match_topics(query, max_topics=3)
        
        if not matched_topics:
            return result
        
        # 收集所有匹配主題的核心條文
        expected_articles = set()
        definition_articles = []
        
        for match in matched_topics:
            for entry in match.guide.get("core_articles", []):
                law = entry.get("law", "")
                for art in entry.get("articles", []):
                    expected_articles.add((self._normalize_law_key(law), str(art).strip()))
                    # 標記定義性條文
                    if match.category == "definition":
                        definition_articles.append(f"{law}第{art}條")
        
        # 收集實際引用的條文
        cited_articles = set()
        for c in citations:
            law = c.get("law_name") or c.get("law_id") or ""
            art = str(c.get("article_no", "")).strip()
            if law and art:
                cited_articles.add((self._normalize_law_key(law), art))
        
        # 檢查是否有主要主題的條文完全缺失
        best_topic = matched_topics[0]
        best_topic_articles = set()
        for entry in best_topic.guide.get("core_articles", []):
            law = entry.get("law", "")
            for art in entry.get("articles", []):
                best_topic_articles.add((self._normalize_law_key(law), str(art).strip()))
        
        # 如果最佳匹配主題的所有條文都沒被引用，可能是主題不一致
        if best_topic_articles and not (best_topic_articles & cited_articles):
            topic_name = best_topic.guide.get("name", best_topic.topic_id)
            result["mismatch"] = f"查詢主題為「{topic_name}」，但引用條文未包含相關核心條文"
        
        # 檢查定義性條文是否缺失（對於 definition 類型的主題）
        if definition_articles:
            definition_article_keys = set()
            for match in matched_topics:
                if match.category == "definition":
                    for entry in match.guide.get("core_articles", []):
                        law = entry.get("law", "")
                        for art in entry.get("articles", []):
                            definition_article_keys.add((self._normalize_law_key(law), str(art).strip()))
            
            missing_def = definition_article_keys - cited_articles
            if missing_def and best_topic.category == "definition":
                # Only warn if the primary topic is definition-type
                missing_list = [f"{law}第{art}條" for law, art in list(missing_def)[:2]]
                result["missing_definition"] = "、".join(missing_list)
        
        return result

    def _check_required_articles(
        self,
        topics: List[str],
        citations: List[Dict]
    ) -> List[str]:
        """
        檢查每個主題的核心條文是否已被引用。
        如果缺少則返回缺漏列表（供錯誤提示）。
        """
        if not topics or not self.law_guide_engine:
            return []
        
        seen = {
            (
                self._normalize_law_key(c.get("law_name") or c.get("law_id")),
                str(c.get("article_no", "")).strip()
            )
            for c in citations
        }
        missing: List[str] = []
        
        for topic in topics:
            guide = self.law_guide_engine.guides.get(topic) if self.law_guide_engine else None
            if not guide:
                continue
            topic_name = guide.get("name") or topic
            for entry in guide.get("core_articles", []):
                law_name = entry.get("law")
                articles = entry.get("articles") or []
                for art in articles:
                    art_no = str(art).strip()
                    key = (self._normalize_law_key(law_name), art_no)
                    if key in seen:
                        continue
                    label = f"{topic_name}：{law_name}第{art_no}條"
                    missing.append(label)
        return missing
    
    def _validate_citations(
        self,
        lawyer_response: LawyerResponse,
        citations: List[Dict],
        analysis: AnalysisResult,
        query: str
    ) -> Dict:
        """
        引用驗證（整合 Phase 0）
        
        Returns:
            {
                "exists": bool,  # 條文存在性
                "content_match": bool,  # 內容一致性
                "conflicts": bool,  # 邏輯衝突
                "whitelist_enforced": bool  # 白名單強制
            }
        """
        # 使用 Phase 0 的驗證器
        topic_name = analysis.topics[0] if analysis.topics else None
        
        # 準備引用列表（格式轉換）
        citation_list = []
        for c in citations:
            citation_list.append({
                "law_name": c.get("law_name") or c.get("law_id") or c.get("title"),
                "article_no": c.get("article_no", "").strip(),
                "heading": c.get("heading", ""),
                "text": c.get("text", "")
            })
        
        try:
            # 調用完整驗證
            validation_report = self.citation_validator.validate_all(
                query=query,
                citations=citation_list,
                topic=topic_name
            )
            
            # 轉換為簡化格式
            return {
                "exists": validation_report["overall_status"] != "FAIL",
                "content_match": len(validation_report["errors"]) == 0,
                "conflicts": any("衝突" in err for err in validation_report["errors"]),
                "whitelist_enforced": validation_report["action"] != "BLOCK"
            }
        
        except Exception as e:
            print(f"[Supervisor] Citation validation failed: {e}")
            # 降級處理：只檢查基本存在性
            return {
                "exists": len(citation_list) > 0,
                "content_match": True,  # 無法驗證，預設通過
                "conflicts": False,
                "whitelist_enforced": True
            }
    
    def _check_logic_completeness(
        self,
        lawyer_response: LawyerResponse,
        analysis: AnalysisResult
    ) -> bool:
        """
        檢查邏輯完整性
        
        簡單策略：
        - 如果是 COMPLEX 查詢，答案應該足夠長且包含多個段落
        - 如果有子問題，答案應該涵蓋所有子問題
        """
        answer = lawyer_response.answer
        
        # 如果是 COMPLEX 查詢
        if analysis.query_type == "COMPLEX":
            # 檢查答案長度（至少300字）
            if len(answer) < 300:
                return False
            
            # 檢查是否包含子問題關鍵詞
            if analysis.sub_questions:
                for sub_q in analysis.sub_questions:
                    # 提取關鍵詞（簡化版）
                    keywords = [word for word in sub_q if len(word) > 1]
                    # 至少50%的子問題關鍵詞出現在答案中
                    if len(keywords) > 0:
                        matched = sum(1 for kw in keywords if kw in answer)
                        if matched / len(keywords) < 0.5:
                            return False
        
        return True
    
    def _assess_quality(
        self,
        lawyer_response: LawyerResponse,
        citation_valid: Dict,
        logic_complete: bool
    ) -> float:
        """
        評估答案質量 (0-1)
        
        考慮因素：
        1. 律師代理的信心度
        2. 引用驗證結果
        3. 答案完整性
        4. 使用的引用數量
        """
        score = 0.0
        
        # 1. 基礎分數：律師信心度 (30%)
        score += lawyer_response.confidence * 0.3
        
        # 2. 引用驗證 (30%)
        citation_score = 0.0
        if citation_valid["exists"]:
            citation_score += 0.5
        if citation_valid["content_match"]:
            citation_score += 0.3
        if not citation_valid["conflicts"]:
            citation_score += 0.2
        score += citation_score * 0.3
        
        # 3. 答案完整性 (25%) - 新增
        answer_length = len(lawyer_response.answer)
        if answer_length > 100:  # 至少100字
            score += 0.15
        if "資料不足" not in lawyer_response.answer and "無法判定" not in lawyer_response.answer:
            score += 0.10  # ✅ 獎勵積極回答
        
        # 4. 邏輯完整性 (15%)
        if logic_complete:
            score += 0.15
        
        return min(1.0, max(0.0, score))
    
    def _make_decision(
        self,
        citation_valid: Dict,
        quality_score: float,
        confidence: float,
        errors: List[str],
        warnings: List[str]
    ):
        """
        做出決策
        
        Returns:
            (decision, feedback)
            decision: PASS/REJECT/WARN
        """
        # REJECT 條件
        if errors:
            feedback = "答案存在嚴重錯誤，無法通過審核：\n" + "\n".join(f"- {err}" for err in errors)
            return "REJECT", feedback
        
        if not citation_valid["exists"]:
            feedback = "引用的法律條文不存在，需要重新生成"
            return "REJECT", feedback
        
        if citation_valid["conflicts"]:
            feedback = "引用的條文之間存在邏輯衝突，需要重新檢查"
            return "REJECT", feedback
        
        # WARN 條件
        if quality_score < self.quality_threshold:
            feedback = f"答案質量評分 {quality_score:.2f} 低於閾值 {self.quality_threshold}，建議謹慎使用"
            return "WARN", feedback
        
        if confidence < self.confidence_threshold:
            feedback = f"系統信心度 {confidence:.2f} 較低，建議諮詢專業律師確認"
            return "WARN", feedback
        
        if warnings:
            feedback = "答案可用，但有以下提醒：\n" + "\n".join(f"- {warn}" for warn in warnings)
            return "WARN", feedback
        
        # PASS
        feedback = f"答案通過審核（質量評分：{quality_score:.2f}，信心度：{confidence:.2f}）"
        return "PASS", feedback


"""秘書代理：答案美化與格式化"""
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel
import re

from .receptionist import AnalysisResult
from .lawyer import LawyerResponse
from .supervisor import ReviewResult


class FinalResponse(BaseModel):
    """最終格式化的回應"""
    answer: str  # 美化後的答案
    suggestions: List[str]  # 後續建議
    metadata: Dict  # 元數據（信心度、質量分數等）


class SecretaryAgent:
    """
    秘書代理：負責答案美化與格式化
    
    職責：
    1. 格式化主答案（Markdown）
    2. 添加引用連結
    3. 生成後續建議
    4. 添加警告（如果有）
    """
    
    def format_response(
        self,
        lawyer_response: LawyerResponse,
        review: ReviewResult,
        analysis: AnalysisResult,
        citations: List[Dict]
    ) -> FinalResponse:
        """
        格式化最終回應
        """
        # 1. 美化主答案
        formatted_answer = self._beautify_answer(
            lawyer_response.answer,
            analysis.query_type
        )
        
        # 2. 添加引用連結
        formatted_answer = self._add_citation_links(
            formatted_answer,
            lawyer_response.used_citations,
            citations
        )
        
        # 3. 添加審核反饋（如果有警告）
        if review.decision == "WARN" and review.warnings:
            formatted_answer = self._add_warnings(formatted_answer, review.warnings)
        
        # 4. 生成後續建議
        suggestions = self._generate_suggestions(
            analysis,
            lawyer_response.uncertainties,
            review.decision
        )
        
        # 5. 組裝元數據
        metadata = {
            "query_type": analysis.query_type,
            "complexity": analysis.complexity,
            "confidence": lawyer_response.confidence,
            "quality_score": review.quality_score,
            "review_decision": review.decision,
            "topics": analysis.topics
        }
        
        return FinalResponse(
            answer=formatted_answer,
            suggestions=suggestions,
            metadata=metadata
        )
    
    def _beautify_answer(self, answer: str, query_type: str) -> str:
        """
        美化答案格式
        
        根據查詢類型應用不同的格式化策略：
        - INFO: 簡潔、直接
        - PROFESSIONAL: 結構化、分段
        - COMPLEX: 多層次、詳細分段
        """
        # 清理多餘空白
        answer = re.sub(r'\n\s*\n\s*\n+', '\n\n', answer)
        answer = answer.strip()
        
        # 如果答案已經有 Markdown 格式，保留
        if any(marker in answer for marker in ["##", "###", "**", "- ", "1. "]):
            return answer
        
        # 否則，根據類型格式化
        if query_type == "INFO":
            # 簡單格式：只添加結論標記
            return f"**回答：**\n\n{answer}"
        
        elif query_type == "PROFESSIONAL":
            # 專業格式：嘗試分段
            return self._format_professional(answer)
        
        elif query_type == "COMPLEX":
            # 複雜格式：多層次結構
            return self._format_complex(answer)
        
        return answer
    
    def _format_professional(self, answer: str) -> str:
        """專業格式化"""
        # 簡單策略：以句號分段，每2-3句一個段落
        sentences = [s.strip() + '。' for s in answer.split('。') if s.strip()]
        
        if len(sentences) <= 3:
            return f"**回答：**\n\n{answer}"
        
        # 分段
        formatted = "## 📋 法律分析\n\n"
        for i, sent in enumerate(sentences, 1):
            formatted += sent
            if i % 2 == 0 and i < len(sentences):
                formatted += "\n\n"
            else:
                formatted += " "
        
        return formatted.strip()
    
    def _format_complex(self, answer: str) -> str:
        """複雜問題格式化"""
        # 更精細的分段策略
        formatted = "## 📋 完整分析\n\n"
        
        # 檢查是否已經有編號或標題
        if re.search(r'[一二三四五六七八九十]、', answer):
            # 已有結構，保留
            formatted += answer
        else:
            # 嘗試自動分段
            paragraphs = [p.strip() for p in answer.split('\n') if p.strip()]
            for i, para in enumerate(paragraphs, 1):
                if len(paragraphs) > 1:
                    formatted += f"### {i}. 分析要點\n\n{para}\n\n"
                else:
                    formatted += f"{para}\n\n"
        
        return formatted.strip()
    
    def _add_citation_links(
        self,
        answer: str,
        used_citation_ids: List[str],
        all_citations: List[Dict]
    ) -> str:
        """
        添加引用連結
        
        在答案末尾添加「參考法條」區塊
        """
        if not used_citation_ids:
            return answer
        
        # 收集使用的引用詳情
        used_citations_details = []
        for cid in used_citation_ids:
            for c in all_citations:
                c_id = c.get("id") or f"{c.get('law_name', '')}_{c.get('article_no', '')}"
                if c_id == cid or cid in c_id:
                    used_citations_details.append(c)
                    break
        
        if not used_citations_details:
            return answer
        
        # 添加引用區塊
        answer += "\n\n---\n\n"
        answer += "### 📚 參考法條\n\n"
        
        for i, c in enumerate(used_citations_details[:5], 1):  # 最多5個
            law_name = c.get("law_name") or c.get("law_id") or c.get("title") or "未知法規"
            article_no = c.get("article_no", "")
            heading = c.get("heading", "")
            
            answer += f"{i}. **{law_name}"
            if article_no:
                answer += f" 第{article_no}條"
            if heading:
                answer += f"**（{heading}）"
            else:
                answer += "**"
            answer += "\n"
        
        return answer
    
    def _add_warnings(self, answer: str, warnings: List[str]) -> str:
        """添加警告訊息"""
        if not warnings:
            return answer
        
        answer += "\n\n---\n\n"
        answer += "### ⚠️  注意事項\n\n"
        
        for i, warning in enumerate(warnings, 1):
            answer += f"{i}. {warning}\n"
        
        return answer
    
    def _generate_suggestions(
        self,
        analysis: AnalysisResult,
        uncertainties: List[str],
        decision: str
    ) -> List[str]:
        """
        生成後續建議
        
        根據：
        1. 查詢複雜度
        2. 不確定性
        3. 審核決策
        """
        suggestions = []
        
        # 1. 根據審核決策
        if decision == "WARN" or decision == "REJECT":
            suggestions.append("建議諮詢專業勞動法律師以獲得更準確的法律意見")
        
        # 2. 根據不確定性
        if uncertainties:
            suggestions.append("針對不確定部分，建議聯繫勞動部或地方勞工局確認")
        
        # 3. 根據複雜度
        if analysis.complexity >= 7.0:
            suggestions.append("此問題涉及複雜情境，建議保留相關證據並諮詢法律專業人士")
        
        # 4. 根據主題（通用建議）
        if "資遣" in analysis.topics or "解僱" in analysis.topics:
            suggestions.append("如涉及勞資爭議，可向勞工局申請勞資調解")
        
        if "職災" in analysis.topics:
            suggestions.append("職業災害案件建議同時諮詢職業災害勞工保護協會")
        
        # 5. 通用建議
        suggestions.append("本回答僅供參考，實際情況可能因個案而異")
        
        # 去重並限制數量
        suggestions = list(dict.fromkeys(suggestions))  # 去重
        return suggestions[:4]  # 最多4個













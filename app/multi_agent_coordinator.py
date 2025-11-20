"""多代理協調器：統籌所有 Agent 協作"""
from __future__ import annotations

from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime
import json
from pydantic import BaseModel

from .agents import ReceptionistAgent, LawyerAgent, SupervisorAgent, SecretaryAgent
from .retrieval import hybrid_search
from .law_guides import LawGuideEngine
from .articles import find_article
import re


class MultiAgentRequest(BaseModel):
    """多代理請求"""
    query: str
    top_k: int = 10
    max_retries: int = 2


class MultiAgentResponse(BaseModel):
    """多代理回應"""
    answer: str
    suggestions: List[str]
    metadata: Dict
    process_log: List[Dict] = []  # 處理過程日誌


ROOT = Path(__file__).resolve().parents[1]


class MultiAgentCoordinator:
    """
    多代理協調器
    
    職責：
    1. 協調四個 Agent 的工作流程
    2. 處理錯誤與重試
    3. 記錄處理過程
    """
    
    def __init__(self):
        self.receptionist = ReceptionistAgent()
        self.lawyer = LawyerAgent()
        self.supervisor = SupervisorAgent()
        self.secretary = SecretaryAgent()
        try:
            self.law_guide_engine = LawGuideEngine()
        except Exception as exc:
            print(f"[Coordinator] Warning: failed to load law guides: {exc}")
            self.law_guide_engine = None
        self.failure_log_path = ROOT / "logs" / "multi_agent_failures.log"
        self.failure_log_path.parent.mkdir(exist_ok=True)
    
    def process(self, req: MultiAgentRequest) -> MultiAgentResponse:
        """
        處理用戶查詢（多代理協作流程）
        """
        process_log = []
        
        # Step 1: 接待員分析
        print(f"[Coordinator] Step 1: Receptionist analyzing query...")
        analysis = self.receptionist.analyze(req.query)
        process_log.append({
            "step": "receptionist",
            "result": {
                "query_type": analysis.query_type,
                "topics": analysis.topics,
                "complexity": analysis.complexity,
                "reasoning": analysis.reasoning
            }
        })
        print(f"[Coordinator] Analysis: {analysis.reasoning}")
        
        # Step 2: 執行檢索（使用接待員的策略）
        print(f"[Coordinator] Step 2: Retrieving citations...")
        strategy = analysis.strategy
        
        from .rules import resolve_topic
        topic = resolve_topic(req.query)
        
        citations = hybrid_search(
            query=req.query,
            top_k=min(strategy.get("top_k", req.top_k), req.top_k),
            use_rerank=strategy.get("use_rerank", False),
            preferred_laws=topic.preferred_laws if topic else None,
            blocked_laws=topic.blocked_laws if topic else None,
            prior_articles=topic.prior_articles if topic else None
        )
        
        # 轉換為 dict 格式
        citations_list = [
            {
                "id": c[1].get("id"),
                "law_name": c[1].get("law_id"),
                "law_id": c[1].get("law_id"),
                "title": c[1].get("title", ""),
                "article_no": c[1].get("article_no", "").strip(),
                "heading": c[1].get("heading", ""),
                "text": c[1].get("text", ""),
                "source_file": c[1].get("source_file", ""),
                "chapter": c[1].get("chapter", "")
            }
            for c in citations
        ]
        citations_list = self._inject_required_citations(
            analysis.topics,
            citations_list
        )
        
        process_log.append({
            "step": "retrieval",
            "result": {
                "count": len(citations_list),
                "top_3": [c["article_no"] for c in citations_list[:3] if c.get("article_no")]
            }
        })
        print(f"[Coordinator] Retrieved {len(citations_list)} citations")
        
        # Step 3: 律師生成答案（帶重試）
        retry_count = 0
        retry_feedback = None
        lawyer_response = None
        review = None
        extra_retry_granted = False
        max_retries = req.max_retries
        
        while retry_count <= req.max_retries:
            print(f"[Coordinator] Step 3: Lawyer generating answer (attempt {retry_count + 1})...")
            
            lawyer_response = self.lawyer.generate_answer(
                query=req.query,
                analysis=analysis,
                citations=citations_list,
                retry_feedback=retry_feedback
            )
            
            process_log.append({
                "step": f"lawyer_attempt_{retry_count + 1}",
                "result": {
                    "confidence": lawyer_response.confidence,
                    "used_citations": len(lawyer_response.used_citations),
                    "uncertainties": len(lawyer_response.uncertainties)
                }
            })
            print(f"[Coordinator] Lawyer confidence: {lawyer_response.confidence:.2f}")
            
            # Step 4: 審核員檢查
            print(f"[Coordinator] Step 4: Supervisor reviewing...")
            review = self.supervisor.review(
                lawyer_response=lawyer_response,
                citations=citations_list,
                analysis=analysis,
                query=req.query
            )
            
            process_log.append({
                "step": f"supervisor_attempt_{retry_count + 1}",
                "result": {
                    "decision": review.decision,
                    "quality_score": review.quality_score,
                    "errors": len(review.errors),
                    "warnings": len(review.warnings)
                }
            })
            print(f"[Coordinator] Review decision: {review.decision} (quality: {review.quality_score:.2f})")
            
            # 決策分支
            if review.decision == "PASS" or review.decision == "WARN":
                # 通過或警告：繼續
                break
            
            elif review.decision == "REJECT":
                # 拒絕：重試
                retry_count += 1
                if (
                    retry_count > max_retries
                    and not extra_retry_granted
                    and self._should_force_extra_retry(review)
                ):
                    max_retries += 1
                    extra_retry_granted = True
                    print("[Coordinator] Extra retry granted due to critical missing citations")

                if retry_count <= max_retries:
                    retry_feedback = review.feedback
                    print(f"[Coordinator] Retrying generation... ({retry_count}/{max_retries})")
                else:
                    # 超過重試次數，返回錯誤
                    print(f"[Coordinator] Max retries reached, returning error response")
                    self._log_failure(req.query, review, process_log)
                    return MultiAgentResponse(
                        answer="抱歉，系統經過多次嘗試後仍無法生成可靠的回答。建議您諮詢專業律師或聯繫勞動主管機關。",
                        suggestions=[
                            "諮詢專業勞動法律師",
                            "聯繫勞動部或地方勞工局",
                            "保留相關證據以備不時之需"
                        ],
                        metadata={
                            "error": "quality_check_failed",
                            "attempts": retry_count,
                            "query_type": analysis.query_type,
                            "complexity": analysis.complexity
                        },
                        process_log=process_log
                    )
        
        # Step 5: 秘書美化
        print(f"[Coordinator] Step 5: Secretary formatting response...")
        final_response = self.secretary.format_response(
            lawyer_response=lawyer_response,
            review=review,
            analysis=analysis,
            citations=citations_list
        )
        
        process_log.append({
            "step": "secretary",
            "result": {
                "suggestions_count": len(final_response.suggestions)
            }
        })
        print(f"[Coordinator] Process completed successfully")
        
        return MultiAgentResponse(
            answer=final_response.answer,
            suggestions=final_response.suggestions,
            metadata=final_response.metadata,
            process_log=process_log
        )

    @staticmethod
    def _normalize_law_key(name: Optional[str]) -> str:
        if not name:
            return ""
        cleaned = re.sub(r"\s+", "", name)
        return cleaned.lower()

    def _inject_required_citations(
        self,
        topics: List[str],
        citations: List[Dict]
    ) -> List[Dict]:
        """
        確保每個主題的核心條文至少出現在引用列表中。
        如果檢索結果沒有包含必備條文，就直接從法條資料庫補齊。
        """
        if not topics or not self.law_guide_engine:
            return citations

        seen = {
            (
                self._normalize_law_key(c.get("law_name") or c.get("law_id")),
                str(c.get("article_no", "")).strip()
            )
            for c in citations
        }

        for topic_id in topics:
            guide = self.law_guide_engine.guides.get(topic_id) if self.law_guide_engine else None
            if not guide:
                continue
            for entry in guide.get("core_articles", []):
                law_name = entry.get("law")
                if not law_name:
                    continue
                articles = entry.get("articles") or []
                for art in articles:
                    art_no = str(art).strip()
                    key = (self._normalize_law_key(law_name), art_no)
                    if key in seen or not art_no:
                        continue
                    article_data = find_article(law_name, art_no)
                    if not article_data:
                        continue
                    citations.append({
                        "id": f"{law_name}-{art_no}",
                        "law_name": law_name,
                        "law_id": law_name,
                        "title": law_name,
                        "article_no": art_no,
                        "heading": article_data.get("heading", ""),
                        "text": article_data.get("text", ""),
                        "source_file": article_data.get("law_file", ""),
                        "chapter": ""
                    })
                    seen.add(key)

        return citations

    @staticmethod
    def _should_force_extra_retry(review) -> bool:
        """
        針對缺少關鍵引用或引用不存在等情況，自動給一次額外重試。
        """
        keywords = ["缺少關鍵引用", "法律條文不存在"]
        corpus = (review.feedback or "") + " ".join(review.errors or [])
        return any(kw in corpus for kw in keywords)

    def _log_failure(self, query: str, review, process_log: List[Dict]) -> None:
        """
        將多次失敗的查詢記錄到 log，方便後續診斷。
        """
        try:
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "query": query,
                "decision": review.decision if review else None,
                "feedback": review.feedback if review else None,
                "errors": review.errors if review else [],
                "warnings": review.warnings if review else [],
                "process_log": process_log,
            }
            with self.failure_log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            print(f"[Coordinator] Failed to log failure: {exc}")







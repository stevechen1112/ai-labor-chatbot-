from __future__ import annotations

# 🔧 修復 Windows 編碼問題
import sys
import io
if sys.platform == 'win32' and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from starlette.staticfiles import StaticFiles
from pydantic import BaseModel

from .rag_utils import load_index, search as tfidf_search
from .vector_store import is_available as vector_available, search as vector_search, warmup as vector_warmup
from .retrieval import hybrid_search
from .query_rewrite import rewrite as rewrite_query
from .rules import resolve_topic
from .citations import decorate_citation
from .articles import find_article
from .database import get_db
from .query_classifier import classify_query, INFO, PROFESSIONAL
from .prompts import get_prompt
from .citation_validator import CitationValidator
# 🆕 Phase 2: Knowledge Graph & Query Enhancement
from .knowledge_graph import get_knowledge_graph, is_available as kg_available
from .query_enhancement import get_query_enhancer, is_available as qe_available
# 🆕 Phase 3: Multi-Agent System
from .multi_agent_coordinator import MultiAgentCoordinator, MultiAgentRequest, MultiAgentResponse
# 🆕 Phase 2.5: Intelligent Retrieval
from .intelligent_retrieval import get_intelligent_retriever, is_available as ir_available
import time
from datetime import datetime
import uuid


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
API_KEY_PATH = ROOT / "api key.txt"


def read_api_key() -> Optional[str]:
    """Read OpenAI API key from file or environment"""
    # Prefer environment variable if present
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key and env_key.strip():
        return env_key.strip()
    try:
        if not API_KEY_PATH.exists():
            return None
        content = API_KEY_PATH.read_text(encoding="utf-8")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        # Heuristic 1: find a line after a marker containing 'openai'
        for i, ln in enumerate(lines):
            if "openai" in ln.lower() and i + 1 < len(lines):
                cand = lines[i + 1]
                if cand.startswith(("sk-", "sk_projec", "sk-proj-")):
                    return cand
                # otherwise still return the next line as a candidate
                return cand
        # Heuristic 2: first line that looks like an OpenAI key
        for ln in lines:
            if ln.startswith(("sk-", "sk_projec", "sk-proj-")):
                return ln
        # Fallback: single token file
        if len(lines) == 1:
            return lines[0]
    except Exception:
        return None
    return None


app = FastAPI(title="Taiwan Labor RAG API", version="0.1.0")

# Initialize database & guards
db = get_db()
# 🔴 Phase 0: Initialize validator instance
validator = CitationValidator()

# 🆕 Phase 2: Initialize knowledge graph & query enhancer (if available)
try:
    if kg_available():
        kg = get_knowledge_graph()
        print(f"[Phase 2] Knowledge Graph loaded: {len(kg.entities)} entities, {kg.graph.number_of_edges()} relations")
    else:
        kg = None
        print("[Phase 2] Knowledge Graph not available")
except Exception as e:
    kg = None
    print(f"[Phase 2] Failed to load Knowledge Graph: {e}")

try:
    if qe_available():
        query_enhancer = get_query_enhancer()
        print("[Phase 2] Query Enhancer initialized")
    else:
        query_enhancer = None
        print("[Phase 2] Query Enhancer not available (OpenAI API key required)")
except Exception as e:
    query_enhancer = None
    print(f"[Phase 2] Failed to initialize Query Enhancer: {e}")

# 🆕 Phase 2.5: Initialize intelligent retriever (if available)
intelligent_retriever = None
try:
    api_key = read_api_key()
    if api_key and ir_available():
        intelligent_retriever = get_intelligent_retriever(api_key=api_key, model="gpt-5-mini")
        print("[Phase 2.5] Intelligent Retriever initialized")
    else:
        print("[Phase 2.5] Intelligent Retriever not available (OpenAI API key required)")
except Exception as e:
    print(f"[Phase 2.5] Failed to initialize Intelligent Retriever: {e}")

# 🆕 Phase 2.6: Initialize query planner (if available)
query_planner = None
try:
    api_key = read_api_key()
    if api_key:
        from .query_planner import QueryPlanner
        query_planner = QueryPlanner(api_key=api_key, model="gpt-5-mini")
        print("[Phase 2.6] Query Planner initialized")
    else:
        print("[Phase 2.6] Query Planner not available (OpenAI API key required)")
except Exception as e:
    print(f"[Phase 2.6] Failed to initialize Query Planner: {e}")

# In-memory metrics (for real-time tracking, periodically synced to DB)
METRICS = {
    "total_queries": 0,
    "total_latency": 0.0,
    "total_citations": 0,
    "start_time": datetime.now().isoformat()
}

# CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_openai_base_url() -> Optional[str]:
    url = os.environ.get("OPENAI_BASE_URL")
    if url and url.strip():
        return url.strip()
    return None


def read_openai_org_project() -> tuple[Optional[str], Optional[str]]:
    org = os.environ.get("OPENAI_ORG_ID") or os.environ.get("OPENAI_ORGANIZATION")
    proj = os.environ.get("OPENAI_PROJECT_ID") or os.environ.get("OPENAI_PROJECT")
    org = org.strip() if org else None
    proj = proj.strip() if proj else None
    return org, proj


def _run_with_timeout(func, timeout: float, *args, **kwargs):
    """Run blocking operations with a soft timeout."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        return future.result(timeout=timeout)


def _missing_required_laws(query_plan, retrieval_results: List[dict]) -> List[str]:
    if not query_plan:
        return []
    seen = {
        (item.get("law_name") or item.get("law_id"))
        for item in retrieval_results
        if item.get("law_name") or item.get("law_id")
    }
    missing = [
        law for law in getattr(query_plan, "required_laws", []) or []
        if law and law not in seen
    ]
    return missing


def _should_use_iterative(query_plan, retrieval_results: List[dict], top_k: int) -> bool:
    if not query_plan or not retrieval_results:
        return True
    difficulty = (getattr(query_plan, "estimated_difficulty", "") or "medium").lower()
    if difficulty == "complex":
        return True
    if len(retrieval_results) < max(top_k, 5):
        return True
    if _missing_required_laws(query_plan, retrieval_results):
        return True
    return False


def _prepend_forced_articles(query_plan, retrieval_results: List[dict]) -> List[dict]:
    if not query_plan:
        return retrieval_results
    forced_articles = getattr(query_plan, "_forced_articles", [])
    if not forced_articles:
        return retrieval_results

    remaining = list(retrieval_results)
    forced_entries: List[dict] = []

    def _make_entry(law_name: str, article_no: str) -> Optional[dict]:
        article = find_article(law_name, article_no)
        if not article:
            return None
        return {
            "law_name": law_name,
            "law_id": law_name,
            "article_no": article_no,
            "heading": article.get("heading"),
            "text": article.get("text"),
            "source_file": article.get("law_file", ""),
            "chapter": "",
            "forced_article": True,
            "source": "query_plan_forced",
        }

    for law_name, article_no in forced_articles:
        existing_idx = next(
            (idx for idx, item in enumerate(remaining)
             if item.get("law_name") == law_name and item.get("article_no") == article_no),
            None
        )
        if existing_idx is not None:
            entry = remaining.pop(existing_idx)
            entry["forced_article"] = True
            entry["source"] = entry.get("source") or "query_plan_forced"
        else:
            entry = _make_entry(law_name, article_no)
            if not entry:
                continue
        forced_entries.append(entry)

    return forced_entries + remaining


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None  # 🆕 支持對話記憶
    top_k: int = 5
    use_llm: bool = False
    use_vector: bool = True
    use_rerank: bool = False
    rerank_top_k: int = 20
    w_vec: float = 0.6
    w_lex: float = 0.4
    preferred_laws: Optional[List[str]] = None
    blocked_laws: Optional[List[str]] = None
    strict_article: bool = False
    use_intelligent_retrieval: bool = True  # 🆕 Phase 2.5: 啟用智能檢索（默認開啟）


class QueryResponse(BaseModel):
    answer: Optional[str]
    citations: List[dict]
    used_llm: bool
    normalized_query: Optional[str] = None
    validation: Optional[dict] = None
    # 🆕 Phase 2: Enhancement metadata
    used_hyde: Optional[bool] = None
    kg_scenario: Optional[str] = None
    kg_reasoning: Optional[str] = None
    # 🆕 Phase 2.5: Intelligent retrieval metadata
    used_intelligent_retrieval: Optional[bool] = None
    ir_iterations: Optional[int] = None
    ir_forced_articles: Optional[int] = None
    # 🆕 Phase 2.6: Query planner metadata
    query_plan_main_issue: Optional[str] = None
    query_plan_sub_issues: Optional[int] = None
    multipath_results_count: Optional[int] = None


class CitationErrorReport(BaseModel):
    citation_id: str
    error_reason: str
    session_id: Optional[str] = None
    law_name: Optional[str] = None
    article_no: Optional[str] = None


@app.get("/health")
def health():
    idx = load_index()
    return {"status": "ok", "num_docs": idx["meta"]["num_docs"]}


@app.get("/warmup")
def warmup():
    info = vector_warmup()
    return {"status": "ok", "vector": info}


@app.get("/article")
def get_article(law: str, no: str):
    """Direct lookup: /article?law=勞動基準法&no=32"""
    result = find_article(law, no)
    if not result:
        return JSONResponse({"found": False, "message": "找不到對應條文"}, status_code=404)
    return {"found": True, **result}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    try:
        start_time = time.time()
        
        # 🆕 對話記憶：讀取最近的對話歷史（最多 5 輪）
        conversation_history = []
        if req.session_id:
            try:
                messages = db.get_session_messages(req.session_id)
                # 取最近 5 輪對話（10 條訊息：5 個問題 + 5 個回答）
                recent_messages = messages[-10:] if len(messages) > 10 else messages
                for msg in recent_messages:
                    role = "user" if msg["role"] == "user" else "assistant"
                    conversation_history.append({
                        "role": role,
                        "content": msg["content"]
                    })
                if conversation_history:
                    print(f"[對話記憶] 讀取 {len(conversation_history)} 條歷史訊息")
            except Exception as e:
                print(f"[對話記憶] 讀取失敗: {e}")
        
        # 🔴 Phase 0: Get topic for whitelist enforcement
        topic = resolve_topic(req.query)

        # 🆕 Phase 2: Query Enhancement (HyDE for abstract queries)
        search_query = req.query
        used_hyde = False
        if query_enhancer and query_enhancer.should_use_hyde(req.query):
            try:
                hypothetical_doc = query_enhancer.generate_hypothetical_document(req.query)
                search_query = hypothetical_doc
                used_hyde = True
                print(f"[Phase 2] Using HyDE for abstract query")
            except Exception as e:
                print(f"[Phase 2] HyDE failed, using original query: {e}")
                search_query = req.query

        # Rewrite query
        rewritten_q = rewrite_query(search_query)
        
        # 🆕 Phase 2.6: Query Planner + Multi-Path Retrieval
        query_plan = None
        query_plan_main_issue = None
        query_plan_sub_issues_count = 0
        multipath_results_count = 0
        used_intelligent_retrieval = False
        ir_iterations = 0
        ir_forced_articles = 0
        ir_insufficient_warning = ""
        
        if req.use_intelligent_retrieval and query_planner:
            try:
                print(f"[Phase 2.6] 啟用智能查詢規劃 + 多路徑檢索模式")
                
                # 第一步：LLM 分析問題並規劃檢索策略
                query_plan = query_planner.plan_query(req.query)
                query_plan_main_issue = query_plan.main_issue
                query_plan_sub_issues_count = len(query_plan.sub_issues)
                print(f"[Phase 2.6] Forced articles: {getattr(query_plan, '_forced_articles', [])}")
                
                print(f"[Phase 2.6] 查詢計畫: {query_plan.main_issue}")
                print(f"[Phase 2.6] 子問題數: {query_plan_sub_issues_count}")
                
                # 第二步：多路徑並行檢索
                from .query_planner import multi_path_retrieval
                
                multipath_results = multi_path_retrieval(
                    query=req.query,
                    query_plan=query_plan,
                    hybrid_search_func=hybrid_search,
                    rewritten_query=rewritten_q,
                    top_k=req.top_k * 2,  # 每個路徑檢索較多結果
                    use_rerank=req.use_rerank
                )
                
                multipath_results_count = len(multipath_results)
                print(f"[Phase 2.6] 多路徑檢索結果: {multipath_results_count} 條")
                
                # 第三步（可選）：如果啟用 2.5 迭代檢索，進一步補強
                use_iterative = bool(intelligent_retriever) and _should_use_iterative(query_plan, multipath_results, req.top_k)
                if use_iterative:
                    try:
                        print(f"[Phase 2.6] Running Phase 2.5 iterative reinforcement")
                        
                        # Phase 2.5 pre-analysis
                        pre_analysis = _run_with_timeout(intelligent_retriever.pre_analyze, 8, req.query)
                        
                        # Iterative retrieval to fill gaps
                        enhanced_results = _run_with_timeout(
                            intelligent_retriever.iterative_retrieve,
                            15,
                            req.query,
                            pre_analysis,
                            multipath_results,
                        )
                        
                        ir_iterations = getattr(intelligent_retriever, "last_iterations", 0)
                        ir_forced_articles = getattr(intelligent_retriever, "last_forced_additions", 0)
                        
                        print(f"[Phase 2.6] 2.5 iterations: {ir_iterations} rounds, forced {ir_forced_articles} articles")
                        
                        validated_results = enhanced_results[:req.top_k * 2]
                        
                    except FuturesTimeoutError:
                        print(f"[Phase 2.6] 2.5 reinforcement timed out, fallback to multi-path results")
                        validated_results = multipath_results[:req.top_k * 2]
                    except Exception as e:
                        print(f"[Phase 2.6] 2.5 reinforcement failed, fallback to multi-path results: {e}")
                        validated_results = multipath_results[:req.top_k * 2]
                else:
                    validated_results = multipath_results[:req.top_k * 2]
                
                used_intelligent_retrieval = bool(use_iterative)
                print(f"[Phase 2.6] ✓ Intelligent retrieval finalized, total results: {len(validated_results)}")
                
            except Exception as e:
                print(f"[Phase 2.6] ✗ 智能檢索失敗，降級到 2.0: {e}")
                import traceback
                traceback.print_exc()
                
                # 降級到 2.0 模式
                results = hybrid_search(
                    rewritten_q,
                    top_k=req.top_k,
                    use_rerank=req.use_rerank,
                    preferred_laws=topic.preferred_laws if topic else None,
                    blocked_laws=topic.blocked_laws if topic else None,
                    prior_articles=topic.prior_articles if topic else None,
                )
                
                # 轉換為 dict 格式
                validated_results = [
                    {
                        "law_name": r[1].get("law_id"),
                        "law_id": r[1].get("law_id"),
                        "article_no": r[1].get("article_no", "").strip(),
                        "heading": r[1].get("heading"),
                        "text": r[1].get("text"),
                        "source_file": r[1].get("source_file", ""),
                        "chapter": r[1].get("chapter", "")
                    }
                    for r in results
                ]
        else:
            # 2.0 模式（原有邏輯）
            results = hybrid_search(
                rewritten_q,
                top_k=req.top_k,
                use_rerank=req.use_rerank,
                preferred_laws=topic.preferred_laws if topic else None,
                blocked_laws=topic.blocked_laws if topic else None,
                prior_articles=topic.prior_articles if topic else None,
            )
            validated_results = [
                {
                    "law_name": r[1].get("law_id"),
                    "law_id": r[1].get("law_id"),
                    "article_no": r[1].get("article_no", "").strip(),
                    "heading": r[1].get("heading"),
                    "text": r[1].get("text"),
                    "source_file": r[1].get("source_file", ""),
                    "chapter": r[1].get("chapter", "")
                }
                for r in results
            ]

        validated_results = validator.enforce_whitelist(
            req.query,
            topic.name if topic else None,
            validated_results
        )
        validated_results = _prepend_forced_articles(query_plan, validated_results)
        citations_for_llm = validated_results[:req.top_k]

        answer = None
        if req.use_llm:
            api_key = read_api_key()
            if not api_key:
                return JSONResponse(status_code=400, content={"error": "API key is not configured."})
            
            try:
                from openai import OpenAI
                org, proj = read_openai_org_project()
                client = OpenAI(api_key=api_key, base_url=read_openai_base_url(), organization=org, project=proj)

                # Assemble context for LLM
                context = "\n\n".join([
                    f"[來源: {c['law_name']} | {c['heading']}]\n{c['text']}" for c in citations_for_llm
                ])

                # Classify query and get prompt
                q_type = classify_query(req.query)
                system_prompt, user_message = get_prompt(q_type, req.query, context)
                
                # 🆕 構建對話式訊息序列
                messages = [{"role": "system", "content": system_prompt}]
                
                # 加入對話歷史
                if conversation_history:
                    messages.extend(conversation_history)
                    # 當前問題作為最新的 user 訊息
                    messages.append({"role": "user", "content": user_message})
                else:
                    # 沒有歷史，直接使用原始 prompt
                    messages.append({"role": "user", "content": user_message})
                
                resp = client.chat.completions.create(
                    model="gpt-5-mini",
                    messages=messages,
                    temperature=0.7,
                )
                answer = resp.choices[0].message.content
                
                # 🆕 Phase 2.5: 加入智能檢索的警告訊息
                if ir_insufficient_warning:
                    answer += ir_insufficient_warning

            except Exception as e:
                return JSONResponse(status_code=500, content={"error": f"LLM generation failed: {e}"})

        # 🔴 Phase 0: Layers 2-4 - Full Validation
        validation_report = validator.validate_all(req.query, citations_for_llm, topic.name if topic else None)
        
        # 🆕 對話記憶：先保存用戶問題（無論驗證是否通過）
        if req.session_id:
            try:
                db.add_message(req.session_id, "user", req.query)
                print(f"[對話記憶] 已保存用戶問題到 session {req.session_id}")
            except Exception as e:
                print(f"[對話記憶] 保存用戶問題失敗: {e}")
        
        # Handle validation actions
        if validation_report['action'] == 'BLOCK':
            # 保存系統的錯誤回應
            if req.session_id:
                try:
                    error_msg = "引用驗證失敗，系統無法提供可信回答。建議諮詢專業律師或聯繫勞動主管機關。"
                    db.add_message(req.session_id, "assistant", error_msg)
                except Exception as e:
                    print(f"[對話記憶] 保存錯誤回應失敗: {e}")
            return JSONResponse(
                status_code=400, 
                content={
                    "error": "引用驗證失敗，系統無法提供可信回答",
                    "details": validation_report['errors'],
                    "suggestion": "建議諮詢專業律師或聯繫勞動主管機關",
                    "status": "BLOCKED"
                }
            )
        
        if validation_report['action'] == 'WARN' and answer:
            answer += "\n\n⚠️ **引用提醒**：\n" + "\n".join(validation_report['warnings'])

        end_time = time.time()
        latency = (end_time - start_time) * 1000  # ms

        # Format final citations
        final_citations = [decorate_citation(c) for c in citations_for_llm]
        
        # 🆕 Phase 2: Get KG metadata if available
        kg_scenario_name = None
        kg_reasoning_text = None
        if kg:
            try:
                scenario = kg.match_scenario(req.query)
                if scenario:
                    kg_scenario_name = scenario.get("name")
                    kg_reasoning_text = kg.get_scenario_reasoning(req.query)
            except Exception:
                pass

        # 🆕 對話記憶：保存系統回答（用戶問題已在上面保存）
        if req.session_id and answer:
            try:
                db.add_message(req.session_id, "assistant", answer)
                print(f"[對話記憶] 已保存系統回答到 session {req.session_id}")
            except Exception as e:
                print(f"[對話記憶] 保存系統回答失敗: {e}")

        return QueryResponse(
            answer=answer,
            citations=final_citations,
            used_llm=req.use_llm,
            normalized_query=(rewritten_q if rewritten_q != req.query else None),
            validation=validation_report,
            used_hyde=used_hyde,
            kg_scenario=kg_scenario_name,
            kg_reasoning=kg_reasoning_text,
            used_intelligent_retrieval=used_intelligent_retrieval,
            ir_iterations=ir_iterations,
            ir_forced_articles=ir_forced_articles,
            query_plan_main_issue=query_plan_main_issue,
            query_plan_sub_issues=query_plan_sub_issues_count,
            multipath_results_count=multipath_results_count
        )
    except Exception as e:
        print(f"[ERROR] Query failed: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": f"Query processing failed: {str(e)}"}
        )


@app.post("/api/citation/report-error")
def report_citation_error(req: CitationErrorReport):
    """接收前端回報的引用錯誤"""
    reason = req.error_reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="error_reason is required")
    db.add_citation_error_report(
        citation_id=req.citation_id,
        session_id=req.session_id,
        law_name=req.law_name,
        article_no=req.article_no,
        error_reason=reason,
        severity="CRITICAL",
        metadata={"received_at": datetime.now().isoformat()},
    )
    return {"status": "recorded", "message": "感謝您的回報，我們會儘快處理"}


@app.get("/api/citation/error-reports")
def get_citation_error_reports(limit: int = 50, status: Optional[str] = None):
    """查詢引用錯誤回報（管理用）"""
    reports = db.get_citation_error_reports(limit=limit, status=status)
    return {
        "total": len(reports),
        "reports": reports
    }


# 🆕 Phase 3: Multi-Agent Query Endpoint
@app.post("/query/multi-agent", response_model=MultiAgentResponse)
def query_multi_agent(req: MultiAgentRequest):
    """
    多代理查詢端點（Phase 3）
    
    使用四個 Agent 協作處理複雜查詢：
    1. 接待員：分析查詢
    2. 律師：生成答案
    3. 審核員：質量控制
    4. 秘書：美化輸出
    """
    coordinator = MultiAgentCoordinator()
    return coordinator.process(req)


# Static files for simple UI
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root_page():
    index_html = STATIC_DIR / "index.html"
    if index_html.exists():
        return FileResponse(str(index_html))
    return JSONResponse({"message": "RAG API is running. Place UI in /static."})


# ===== Session Management (MVP Placeholder) =====

class SessionCreate(BaseModel):
    pass

class FeedbackSubmit(BaseModel):
    session_id: Optional[str] = None
    feedback: str
    timestamp: Optional[str] = None


@app.post("/session/new")
def create_session(data: SessionCreate = None):
    """Create a new session (persisted to SQLite)"""
    session_id = str(uuid.uuid4())
    db.create_session(session_id)
    session = db.get_session(session_id)
    return {"session_id": session_id, "created_at": session["created_at"]}


@app.get("/session/{session_id}")
def get_session(session_id: str):
    """Get session history (persisted in SQLite)"""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.get_session_messages(session_id)
    return {
        "session_id": session_id, 
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
        "messages": messages
    }


@app.post("/feedback")
def submit_feedback(data: FeedbackSubmit):
    """Submit user feedback (persisted to SQLite)"""
    db.add_feedback(
        session_id=data.session_id,
        comment=data.feedback
    )
    return {"status": "ok", "message": "感謝您的回饋"}


@app.get("/metrics")
def get_metrics():
    """Get system metrics (persisted in SQLite)"""
    avg_latency = METRICS["total_latency"] / METRICS["total_queries"] if METRICS["total_queries"] > 0 else 0
    avg_citations = METRICS["total_citations"] / METRICS["total_queries"] if METRICS["total_queries"] > 0 else 0
    
    # Get counts from database
    with db.get_conn() as conn:
        total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        total_feedbacks = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        total_messages = conn.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
    
    return {
        "total_queries": METRICS["total_queries"],  # Real-time counter
        "total_queries_db": total_messages,  # Persisted count
        "average_latency_seconds": round(avg_latency, 3),
        "average_citations": round(avg_citations, 2),
        "start_time": METRICS["start_time"],
        "uptime_seconds": (datetime.now() - datetime.fromisoformat(METRICS["start_time"])).total_seconds(),
        "total_feedbacks": total_feedbacks,
        "total_sessions": total_sessions
    }

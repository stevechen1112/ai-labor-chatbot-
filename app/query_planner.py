"""
查詢規劃模組 - Phase 2.6 核心功能

讓 LLM 分析問題並規劃檢索策略，從根本上解決「檢索方向錯誤」問題。

核心理念：
- 不再依賴固定的 24 個 topic 規則
- 讓 LLM 直接理解問題並指導檢索
- 多路徑並行檢索，提高召回率

作者：AI Assistant
版本：2.6.0
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
from typing import List, Dict, Optional
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

class SubIssue(BaseModel):
    """子問題"""
    issue: str
    importance: str  # "high" | "medium" | "low"
    suggested_articles: List[str]  # LLM 建議可能相關的法條（如："勞動基準法第16條"）
    keywords: List[str]  # 該子問題的關鍵檢索詞


class QueryPlan(BaseModel):
    """查詢計畫"""
    main_issue: str  # 核心問題（如：資遣程序、工資扣除、職災責任）
    sub_issues: List[SubIssue]  # 子問題列表
    required_laws: List[str]  # 必須查詢的法律
    suggested_keywords: List[str]  # 建議的檢索關鍵字
    estimated_difficulty: str  # "simple" | "medium" | "complex"
    reasoning: str  # 推理過程

# ============================================================
# Canonical Issue Harmonization
# ============================================================

CANONICAL_ISSUES = [
    {
        "label": "資遣流程",
        "keywords": ["資遣", "流程"],
        "required_laws": ["勞動基準法", "就業服務法"],
        "forced_articles": [("勞動基準法", "11"), ("勞動基準法", "16"), ("勞動基準法", "17"), ("就業服務法", "33")],
    },
    {
        "label": "資遣費計算與預告期工資",
        "keywords": ["資遣", "預告"],
        "required_laws": ["勞動基準法"],
        "forced_articles": [("勞動基準法", "16"), ("勞動基準法", "17")],
    },
    {
        "label": "懷孕歧視與不利待遇",
        "keywords": ["懷孕", "歧視"],
        "required_laws": ["性別平等工作法", "勞動基準法"],
        "forced_articles": [("性別平等工作法", "11"), ("勞動基準法", "51"), ("勞動基準法", "7")],
        "force_complex": True,
    },
    {
        "label": "勞工曠職與雇主終止契約",
        "keywords": ["曠職", "終止"],
        "required_laws": ["勞動基準法"],
        "forced_articles": [("勞動基準法", "12")],
    },
    {
        "label": "加班費與國定假日工資計算",
        "keywords": ["加班", "假日"],
        "required_laws": ["勞動基準法"],
        "forced_articles": [("勞動基準法", "24"), ("勞動基準法", "39")],
    },
]



def _ensure_article_suggestion(query_plan: QueryPlan, law_name: str, article_no: str) -> None:
    """確保查詢計畫中至少有一個子議題建議特定條文。"""
    target = f"{law_name}第{article_no}條"
    for sub_issue in query_plan.sub_issues:
        if target in sub_issue.suggested_articles:
            return
    query_plan.sub_issues.append(
        SubIssue(
            issue=f"{law_name}第{article_no}條補強",
            importance="high",
            suggested_articles=[target],
            keywords=[law_name, article_no],
        )
    )


def _harmonize_query_plan(query_plan: QueryPlan, original_query: str) -> QueryPlan:
    """統一 main_issue 命名並補齊必要法條/子議題。"""
    user_text = (original_query or "").lower()
    plan_text = " ".join([
        query_plan.main_issue or "",
        " ".join(si.issue for si in query_plan.sub_issues),
        original_query or "",
    ]).lower()

    best_choice = None
    best_score = 0
    for config in CANONICAL_ISSUES:
        if all(keyword in user_text for keyword in config["keywords"]):
            score = 2
        elif all(keyword in plan_text for keyword in config["keywords"]):
            score = 1
        else:
            continue
        if score > best_score:
            best_score = score
            best_choice = config

    if best_choice:
        query_plan.main_issue = best_choice["label"]
        existing_laws = set(query_plan.required_laws or [])
        for law in best_choice.get("required_laws", []):
            if law not in existing_laws:
                query_plan.required_laws.append(law)
                existing_laws.add(law)
        for law_name, article_no in best_choice.get("forced_articles", []):
            _ensure_article_suggestion(query_plan, law_name, article_no)
        if best_choice.get("force_complex"):
            query_plan.estimated_difficulty = "complex"
        setattr(query_plan, "_forced_articles", best_choice.get("forced_articles", []))
    else:
        setattr(query_plan, "_forced_articles", [])
    return query_plan



# ============================================================
# Query Planner Class
# ============================================================

class QueryPlanner:
    """
    查詢規劃器（Phase 2.6 核心）
    
    使用 LLM 分析用戶問題，規劃檢索策略：
    1. 識別核心問題與子問題
    2. 建議相關法律與法條
    3. 提供檢索關鍵字
    """
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        """
        初始化查詢規劃器
        
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
        
        print(f"[QueryPlanner] Initialized with model: {self.model}")
    
    def plan_query(self, query: str) -> QueryPlan:
        """
        分析問題並規劃檢索策略
        
        Args:
            query: 用戶問題
            
        Returns:
            QueryPlan: 查詢計畫
        """
        prompt = f"""你是台灣勞動法律專家和檢索系統規劃師。

用戶問題：{query}

請**仔細分析**這個問題並規劃檢索策略。

**任務**：
1. **核心問題是什麼？**（用一句話精確概括，例如："資遣流程與費用計算"、"懷孕歧視與調職降薪"）
2. **可以拆解為哪些子問題？**
   - 每個子問題的重要性：high（核心問題）/ medium（相關問題）/ low（次要參考）
   - 如果你知道具體法條，請明確列出（例如："勞動基準法第16條"）
   - 為每個子問題提供 2-3 個檢索關鍵字
3. **需要查詢哪些法律？**（法律全名）
4. **建議使用哪些關鍵字進行全局檢索？**
5. **估計問題難度**：simple（單一法條可回答）/ medium（需要 2-3 條法規）/ complex（跨法規、多面向）

**重要提醒**：
- 請仔細識別問題的核心類型（例如：「資遣」vs「加班」vs「職災」vs「性別歧視」）
- 如果問題涉及多個面向，請全部列出（例如：資遣 = 預告期 + 資遣費 + 通報義務）
- 如果問題提到「工資」，請判斷是「工資計算」還是「工資扣除」還是「資遣費」
- 如果你知道具體的法條號碼，務必列出！這能大幅提高檢索準確性
- **特別注意細則性法規**：如果問題涉及「請假」，務必考慮「勞工請假規則」；如果涉及「性別歧視」或「懷孕」，務必考慮「性別平等工作法」的關鍵條文（如第11條禁止性別歧視）

**回答格式（JSON）**：
{{
    "main_issue": "資遣流程與費用計算",
    "sub_issues": [
        {{
            "issue": "資遣預告期規定",
            "importance": "high",
            "suggested_articles": ["勞動基準法第16條"],
            "keywords": ["資遣", "預告期", "通知"]
        }},
        {{
            "issue": "資遣費計算方式",
            "importance": "high",
            "suggested_articles": ["勞動基準法第17條"],
            "keywords": ["資遣費", "計算", "年資"]
        }},
        {{
            "issue": "主管機關通報義務",
            "importance": "medium",
            "suggested_articles": ["就業服務法第33條"],
            "keywords": ["通報", "主管機關", "就業服務"]
        }}
    ],
    "required_laws": ["勞動基準法", "就業服務法"],
    "suggested_keywords": ["資遣", "預告期", "資遣費", "通報", "年資"],
    "estimated_difficulty": "medium",
    "reasoning": "問題涉及完整的資遣流程，需要涵蓋程序（預告、通報）與權利（資遣費）兩個面向，屬於中等難度的多面向問題"
}}

**開始分析**：
"""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "你是台灣勞動法律專家和檢索系統規劃師。你的任務是精確識別用戶問題的法律本質，並規劃高效的檢索策略。"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            query_plan = QueryPlan(**result)
            query_plan = _harmonize_query_plan(query_plan, query)
            
            print(f"[QueryPlanner] 核心問題: {query_plan.main_issue}")
            print(f"[QueryPlanner] 子問題數量: {len(query_plan.sub_issues)}")
            print(f"[QueryPlanner] 涉及法律: {', '.join(query_plan.required_laws)}")
            
            return query_plan
            
        except Exception as e:
            print(f"[QueryPlanner] 規劃失敗: {e}")
            # 降級：返回簡化的查詢計畫
            return self._fallback_plan(query)
    
    def _fallback_plan(self, query: str) -> QueryPlan:
        """
        降級方案：當 LLM 規劃失敗時，返回基礎查詢計畫
        
        Args:
            query: 用戶問題
            
        Returns:
            QueryPlan: 簡化的查詢計畫
        """
        print("[QueryPlanner] 使用降級查詢計畫")
        
        return QueryPlan(
            main_issue="勞動法律諮詢",
            sub_issues=[
                SubIssue(
                    issue="法律規定查詢",
                    importance="high",
                    suggested_articles=[],
                    keywords=[query[:20]]  # 使用問題前 20 字作為關鍵字
                )
            ],
            required_laws=["勞動基準法"],
            suggested_keywords=[query[:30]],
            estimated_difficulty="medium",
            reasoning="LLM 規劃失敗，使用基礎查詢策略"
        )


# ============================================================
# Multi-Path Retrieval Functions
# ============================================================

def multi_path_retrieval(
    query: str,
    query_plan: QueryPlan,
    hybrid_search_func,
    rewritten_query: str,
    top_k: int = 10,
    use_rerank: bool = False
) -> List[Dict]:
    """
    多路徑並行檢索
    
    同時使用多種檢索策略，然後智能融合結果：
    1. 基於全局關鍵字的混合檢索
    2. 基於子問題的語義檢索
    3. 基於建議法條的精確檢索（如果 LLM 提供）
    
    Args:
        query: 原始用戶問題
        query_plan: 查詢計畫
        hybrid_search_func: 混合檢索函數
        rewritten_query: 重寫後的查詢
        top_k: 每個路徑返回的結果數量
        use_rerank: 是否使用重排序
        
    Returns:
        List[Dict]: 融合後的檢索結果
    """
    print(f"[MultiPath] 開始多路徑檢索 (top_k={top_k})")
    
    all_results = []
    seen_ids = set()
    
    # 路徑 1：基於全局關鍵字的混合檢索
    try:
        print(f"[MultiPath] 路徑1: 全局關鍵字檢索")
        
        # 使用 LLM 建議的關鍵字構建檢索查詢
        global_query = " ".join(query_plan.suggested_keywords[:5])  # 最多 5 個關鍵字
        
        path1_results = hybrid_search_func(
            global_query,
            top_k=top_k,
            use_rerank=use_rerank,
            preferred_laws=query_plan.required_laws,
            blocked_laws=None,
            prior_articles=None
        )
        
        for score, metadata in path1_results:
            result_id = f"{metadata.get('law_id', '')}_{metadata.get('article_no', '')}"
            if result_id not in seen_ids:
                seen_ids.add(result_id)
                all_results.append({
                    "law_name": metadata.get("law_id"),
                    "law_id": metadata.get("law_id"),
                    "article_no": metadata.get("article_no", "").strip(),
                    "heading": metadata.get("heading", ""),
                    "text": metadata.get("text", ""),
                    "source_file": metadata.get("source_file", ""),
                    "chapter": metadata.get("chapter", ""),
                    "score": score,
                    "source": "path1_global_keywords"
                })
        
        print(f"[MultiPath]   ✓ 路徑1 檢索到 {len(path1_results)} 條結果")
        
    except Exception as e:
        print(f"[MultiPath]   ✗ 路徑1 失敗: {e}")
    
    # 路徑 2：基於子問題的語義檢索
    try:
        print(f"[MultiPath] 路徑2: 子問題語義檢索")
        
        for sub_issue in query_plan.sub_issues:
            # 為每個高重要性子問題執行檢索
            if sub_issue.importance in ["high", "medium"]:
                sub_query = " ".join(sub_issue.keywords)
                
                path2_results = hybrid_search_func(
                    sub_query,
                    top_k=max(3, top_k // 2),  # 每個子問題檢索較少結果
                    use_rerank=use_rerank,
                    preferred_laws=query_plan.required_laws,
                    blocked_laws=None,
                    prior_articles=None
                )
                
                for score, metadata in path2_results:
                    result_id = f"{metadata.get('law_id', '')}_{metadata.get('article_no', '')}"
                    if result_id not in seen_ids:
                        seen_ids.add(result_id)
                        all_results.append({
                            "law_name": metadata.get("law_id"),
                            "law_id": metadata.get("law_id"),
                            "article_no": metadata.get("article_no", "").strip(),
                            "heading": metadata.get("heading", ""),
                            "text": metadata.get("text", ""),
                            "source_file": metadata.get("source_file", ""),
                            "chapter": metadata.get("chapter", ""),
                            "score": score,
                            "source": f"path2_sub_issue_{sub_issue.importance}"
                        })
        
        print(f"[MultiPath]   ✓ 路徑2 完成，累計結果: {len(all_results)} 條")
        
    except Exception as e:
        print(f"[MultiPath]   ✗ 路徑2 失敗: {e}")
    
    # 路徑 3：基於 LLM 建議法條的精確檢索 + Phase 2.6.1 自動補充關鍵法條
    try:
        print(f"[MultiPath] 路徑3: 建議法條精確檢索")
        
        from .articles import find_article
        
        forced_count = 0
        
        # Phase 2.6.1: 識別問題類型，自動補充關鍵法條
        main_issue_lower = query_plan.main_issue.lower()
        is_pregnancy_discrimination = "懷孕" in main_issue_lower or "歧視" in main_issue_lower
        is_leave = "請假" in main_issue_lower or "請假" in query.lower()
        
        # 收集 LLM 已建議的法條
        llm_suggested_set = set()
        
        for sub_issue in query_plan.sub_issues:
            for suggested_article in sub_issue.suggested_articles:
                # 解析法條字串（例如："勞動基準法第16條"）
                law_name, article_no = _parse_article_string(suggested_article)
                
                if law_name and article_no:
                    llm_suggested_set.add((law_name, article_no))
                    result_id = f"{law_name}_{article_no}"
                    
                    if result_id not in seen_ids:
                        article_data = find_article(law_name, article_no)
                        
                        if article_data:
                            seen_ids.add(result_id)
                            all_results.append({
                                "law_name": law_name,
                                "law_id": law_name,
                                "article_no": article_no,
                                "heading": article_data.get("heading", f"第 {article_no} 條"),
                                "text": article_data.get("text", ""),
                                "source_file": article_data.get("law_file", ""),
                                "chapter": "",
                                "score": 1.0,  # 高分數（LLM 直接建議）
                                "source": "path3_llm_suggested"
                            })
                            forced_count += 1
                            print(f"[MultiPath]   ✓ 強制檢索: {law_name} 第 {article_no} 條")
        
        # Phase 2.6.1: 自動補充關鍵法條（如果 LLM 沒有建議）
        # 1. 懷孕歧視問題：自動補充性平法第11條
        # 注意：正確法律名稱是「性別平等工作法」（不是「性別工作平等法」）
        if is_pregnancy_discrimination:
            # 檢查多種可能的法律名稱
            gender_equality_law_names = ["性別平等工作法", "性別工作平等法"]
            found_gender_law = False
            
            for law_name in gender_equality_law_names:
                result_id = f"{law_name}_11"
                
                # 檢查是否已在 LLM 建議中
                if (law_name, "11") in llm_suggested_set:
                    print(f"[MultiPath]   ℹ️ 性平法第11條已在 LLM 建議中，跳過自動補充")
                    found_gender_law = True
                    break
                
                # 檢查是否已在檢索結果中
                if result_id in seen_ids:
                    print(f"[MultiPath]   ℹ️ 性平法第11條已在檢索結果中，跳過自動補充")
                    found_gender_law = True
                    break
                
                # 嘗試查找
                article_data = find_article(law_name, "11")
                if article_data:
                    seen_ids.add(result_id)
                    all_results.append({
                        "law_name": law_name,
                        "law_id": law_name,
                        "article_no": "11",
                        "heading": article_data.get("heading", "第 11 條"),
                        "text": article_data.get("text", ""),
                        "source_file": article_data.get("law_file", ""),
                        "chapter": "",
                        "score": 1.2,  # 稍高分數（自動補充）
                        "source": "path3_auto_supplemented"
                    })
                    forced_count += 1
                    print(f"[MultiPath]   ✓ 自動補充: {law_name} 第 11 條（懷孕歧視關鍵條文）")
                    found_gender_law = True
                    break
                else:
                    print(f"[MultiPath]   ⚠️ find_article 找不到: {law_name} 第 11 條")
            
            if not found_gender_law:
                print(f"[MultiPath]   ⚠️ 無法自動補充性平法第11條（所有嘗試都失敗）")
        
        # 2. 請假問題：自動補充勞工請假規則第2條
        if is_leave and ("勞工請假規則", "2") not in llm_suggested_set:
            result_id = "勞工請假規則_2"
            if result_id not in seen_ids:
                article_data = find_article("勞工請假規則", "2")
                if article_data:
                    seen_ids.add(result_id)
                    all_results.append({
                        "law_name": "勞工請假規則",
                        "law_id": "勞工請假規則",
                        "article_no": "2",
                        "heading": article_data.get("heading", "第 2 條"),
                        "text": article_data.get("text", ""),
                        "source_file": article_data.get("law_file", ""),
                        "chapter": "",
                        "score": 1.2,  # 稍高分數（自動補充）
                        "source": "path3_auto_supplemented"
                    })
                    forced_count += 1
                    print(f"[MultiPath]   ✓ 自動補充: 勞工請假規則 第 2 條（請假規定關鍵條文）")
        
        print(f"[MultiPath]   ✓ 路徑3 檢索到 {forced_count} 條法條（含自動補充）")
        
    except Exception as e:
        print(f"[MultiPath]   ✗ 路徑3 失敗: {e}")
    
    # 路徑 4：使用原始重寫查詢的檢索（確保不遺漏原有邏輯）
    try:
        print(f"[MultiPath] 路徑4: 原始重寫查詢檢索")
        
        path4_results = hybrid_search_func(
            rewritten_query,
            top_k=top_k,
            use_rerank=use_rerank,
            preferred_laws=query_plan.required_laws,
            blocked_laws=None,
            prior_articles=None
        )
        
        for score, metadata in path4_results:
            result_id = f"{metadata.get('law_id', '')}_{metadata.get('article_no', '')}"
            if result_id not in seen_ids:
                seen_ids.add(result_id)
                all_results.append({
                    "law_name": metadata.get("law_id"),
                    "law_id": metadata.get("law_id"),
                    "article_no": metadata.get("article_no", "").strip(),
                    "heading": metadata.get("heading", ""),
                    "text": metadata.get("text", ""),
                    "source_file": metadata.get("source_file", ""),
                    "chapter": metadata.get("chapter", ""),
                    "score": score,
                    "source": "path4_rewritten_query"
                })
        
        print(f"[MultiPath]   ✓ 路徑4 完成，總結果: {len(all_results)} 條")
        
    except Exception as e:
        print(f"[MultiPath]   ✗ 路徑4 失敗: {e}")
    
    # 智能融合與排序
    final_results = _merge_and_rank_results(all_results, query_plan)
    
    print(f"[MultiPath] ✓ 多路徑檢索完成，最終結果: {len(final_results)} 條")
    
    return final_results


def _parse_article_string(article_str: str) -> tuple[Optional[str], Optional[str]]:
    """
    解析法條字串（例如："勞動基準法第16條" → ("勞動基準法", "16")）
    
    Args:
        article_str: 法條字串
        
    Returns:
        (law_name, article_no): 法律名稱與條號
    """
    import re
    
    # 正則匹配：法律名稱 + "第" + 數字 + "條"
    match = re.match(r"(.+?)第\s*(\d+(?:-\d+)?)\s*條", article_str)
    
    if match:
        law_name = match.group(1).strip()
        article_no = match.group(2).strip()
        return law_name, article_no
    
    return None, None


def _merge_and_rank_results(results: List[Dict], query_plan: QueryPlan) -> List[Dict]:
    """
    融合並排序多路徑檢索結果（Phase 2.6.1 優化版）
    
    排序策略：
    1. LLM 直接建議的法條（path3）優先級最高
    2. 高重要性子問題檢索到的結果次之
    3. 對 LLM 建議的關鍵法條額外加權（如性平法第11條）
    4. 對不相關法條降權（減少交叉汙染）
    5. 其他結果按原始分數排序
    
    Args:
        results: 所有檢索結果
        query_plan: 查詢計畫
        
    Returns:
        List[Dict]: 排序後的結果
    """
    # 收集所有 LLM 建議的法條（用於額外加權）
    llm_suggested_articles = set()
    for sub_issue in query_plan.sub_issues:
        for suggested_article in sub_issue.suggested_articles:
            law_name, article_no = _parse_article_string(suggested_article)
            if law_name and article_no:
                llm_suggested_articles.add((law_name, article_no.strip()))
    
    # 識別核心法律（用於過濾不相關法條）
    core_laws = set(query_plan.required_laws)
    
    # 識別問題類型（用於過濾不相關法條）
    main_issue_lower = query_plan.main_issue.lower()
    is_severance = "資遣" in main_issue_lower
    is_termination = "終止" in main_issue_lower or "解僱" in main_issue_lower
    is_overtime = "加班" in main_issue_lower
    is_pregnancy = "懷孕" in main_issue_lower or "歧視" in main_issue_lower
    
    # 為每個結果計算優先級分數
    for result in results:
        base_score = result.get("score", 0.0)
        source = result.get("source", "")
        law_name = result.get("law_name", "")
        article_no = result.get("article_no", "").strip()
        
        # 基礎優先級加權
        if "path3_llm_suggested" in source:
            priority = 10.0  # LLM 直接建議，最高優先級
        elif "path3_auto_supplemented" in source:
            priority = 9.0  # Phase 2.6.1: 自動補充的關鍵法條，次高優先級
        elif "path2_sub_issue_high" in source:
            priority = 5.0  # 高重要性子問題
        elif "path2_sub_issue_medium" in source:
            priority = 3.0  # 中重要性子問題
        elif "path1_global_keywords" in source:
            priority = 2.0  # 全局關鍵字
        elif "path4_rewritten_query" in source:
            priority = 1.0  # 原始查詢
        else:
            priority = 1.0
        
        # Phase 2.6.1 優化：對 LLM 建議的關鍵法條額外加權
        if (law_name, article_no) in llm_suggested_articles:
            priority *= 1.5  # 額外加權 50%
            # 特別加強性平法第11條（懷孕歧視關鍵條文）
            # 注意：支援兩種可能的法律名稱
            if (law_name in ["性別平等工作法", "性別工作平等法"]) and article_no == "11":
                priority *= 1.3  # 再額外加權 30%
        
        # Phase 2.6.1 優化：對不相關法條降權（減少交叉汙染）
        # 如果問題是「資遣」，降權「雇主終止契約」相關條文（第12條）
        if is_severance and law_name == "勞動基準法" and article_no == "12":
            priority *= 0.3  # 大幅降權
        # 如果問題是「雇主終止契約」，降權「資遣」相關條文（第11條）
        elif is_termination and law_name == "勞動基準法" and article_no == "11":
            priority *= 0.3  # 大幅降權
        # 如果問題是「加班」，降權「資遣」相關條文（第16、17條）
        elif is_overtime and law_name == "勞動基準法" and article_no in ["16", "17"]:
            priority *= 0.3  # 大幅降權
        # 如果問題不是「加班」，降權「加班費」相關條文（第24條）
        elif not is_overtime and law_name == "勞動基準法" and article_no == "24":
            priority *= 0.5  # 適度降權
        
        # 對非核心法律的結果適度降權（除非是 LLM 明確建議的）
        if result.get("forced_article"):
            priority *= 20
        elif law_name not in core_laws and "path3_llm_suggested" not in source:
            priority *= 0.7  # 適度降權
        
        result["final_score"] = base_score * priority
    
    # 按最終分數排序
    sorted_results = sorted(results, key=lambda x: x.get("final_score", 0.0), reverse=True)
    
    return sorted_results


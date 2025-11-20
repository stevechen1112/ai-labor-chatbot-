"""接待員代理：查詢分析與路由"""
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel
import re


class AnalysisResult(BaseModel):
    """接待員分析結果"""
    query_type: str  # INFO/PROFESSIONAL/COMPLEX
    topics: List[str]  # 識別的主題標籤
    complexity: float  # 0-10
    strategy: Dict  # 檢索策略
    sub_questions: List[str] = []  # 子問題（如果是COMPLEX）
    reasoning: str = ""  # 分析推理


class ReceptionistAgent:
    """
    接待員代理：負責理解用戶查詢並規劃處理策略
    
    職責：
    1. 查詢分類（INFO/PROFESSIONAL/COMPLEX）
    2. 主題識別
    3. 複雜度評估
    4. 檢索策略規劃
    """
    
    def __init__(self):
        # 複雜度閾值
        self.complexity_thresholds = {
            "simple": 3.0,
            "moderate": 6.0,
            "complex": 8.0
        }
        
        # 關鍵詞模式（用於快速分類）
        self.info_patterns = [
            r"是什麼", r"如何", r"怎麼", r"多少", r"幾天", r"幾個月",
            r"可以嗎", r"合法嗎", r"違法嗎"
        ]
        
        self.professional_patterns = [
            r"依據", r"法律", r"條文", r"規定", r"計算", r"賠償",
            r"訴訟", r"仲裁", r"權利", r"義務"
        ]
        
        self.complex_patterns = [
            r"[，、]", r"如果.*那麼", r"既.*又", r"不僅.*而且",
            r"除了.*還", r"同時", r"並且"
        ]
    
    def analyze(self, query: str) -> AnalysisResult:
        """分析查詢並生成處理策略"""
        # 1. 基礎分類
        query_type = self.classify_query(query)
        
        # 2. 主題識別（使用增強的 law_guides）
        topics = self._identify_topics_enhanced(query)
        
        # 3. 複雜度評估
        complexity = self.assess_complexity(query)
        
        # 4. 生成檢索策略
        strategy = self.plan_retrieval_strategy(query_type, complexity)
        
        # 5. 子問題分解（如果是COMPLEX）
        sub_questions = []
        if query_type == "COMPLEX":
            sub_questions = self.decompose_query(query)
        
        # 6. 生成推理說明
        reasoning = self.generate_reasoning(query_type, topics, complexity)
        
        return AnalysisResult(
            query_type=query_type,
            topics=topics,
            complexity=complexity,
            strategy=strategy,
            sub_questions=sub_questions,
            reasoning=reasoning
        )
    
    def _identify_topics_enhanced(self, query: str) -> List[str]:
        """
        增強的主題識別（使用 law_guides.yaml + 舊 rules.py）
        
        策略：
        1. 優先使用 law_guides.yaml 的關鍵詞匹配（涵蓋30+主題）
        2. 退回 rules.py 的 resolve_topic（5個主題的規則）
        3. 如果兩者都識別到，合併結果
        """
        topics = []
        
        # 方法1：使用 law_guides.yaml（更全面，30+主題）
        try:
            from ..law_guides import LawGuideEngine
            guide_engine = LawGuideEngine()
            
            # 嘗試匹配所有可能的主題（可能有多個）
            query_lower = query.lower()
            for topic_id, guide in guide_engine.guides.items():
                keywords = guide.get("keywords", [])
                if any(kw and kw.lower() in query_lower for kw in keywords):
                    topics.append(topic_id)
                    # 找到第一個主題後就返回（避免過度匹配）
                    break
        except Exception as e:
            print(f"[Receptionist] law_guides matching failed: {e}")
            import traceback
            traceback.print_exc()
        
        # 方法2：退回 rules.py（舊方法，5個主題）
        if not topics:
            try:
                from ..rules import resolve_topic
                topic = resolve_topic(query)
                if topic:
                    topics.append(topic.name)
            except Exception as e:
                print(f"[Receptionist] rules.py matching failed: {e}")
        
        return topics
    
    def classify_query(self, query: str) -> str:
        """
        分類查詢類型
        
        Returns:
            - INFO: 一般資訊查詢（簡單問答）
            - PROFESSIONAL: 專業法律諮詢
            - COMPLEX: 複雜多面向問題
        """
        query_lower = query.lower()
        
        # 檢查複雜模式
        complex_score = sum(1 for pattern in self.complex_patterns if re.search(pattern, query))
        
        # 查詢長度也是複雜度指標
        if len(query) > 50 or complex_score >= 2:
            return "COMPLEX"
        
        # 檢查專業模式
        professional_score = sum(1 for pattern in self.professional_patterns if re.search(pattern, query_lower))
        
        if professional_score >= 1:
            return "PROFESSIONAL"
        
        # 預設為 INFO
        return "INFO"
    
    def assess_complexity(self, query: str) -> float:
        """
        評估查詢複雜度 (0-10)
        
        考慮因素：
        - 查詢長度
        - 複雜句式
        - 多重條件
        - 法律術語密度
        """
        score = 0.0
        
        # 1. 長度因素 (0-3分)
        length = len(query)
        if length < 20:
            score += 1.0
        elif length < 50:
            score += 2.0
        else:
            score += 3.0
        
        # 2. 複雜句式 (0-3分)
        complex_patterns_found = sum(1 for pattern in self.complex_patterns if re.search(pattern, query))
        score += min(complex_patterns_found * 1.5, 3.0)
        
        # 3. 問號數量（多個問題） (0-2分)
        question_marks = query.count('？') + query.count('?')
        score += min(question_marks * 0.5, 2.0)
        
        # 4. 法律術語密度 (0-2分)
        legal_terms = [
            "法規", "條文", "依據", "賠償", "訴訟", "仲裁",
            "契約", "解僱", "資遣", "職災", "補償"
        ]
        terms_found = sum(1 for term in legal_terms if term in query)
        score += min(terms_found * 0.5, 2.0)
        
        return min(score, 10.0)
    
    def plan_retrieval_strategy(self, query_type: str, complexity: float) -> Dict:
        """
        規劃檢索策略
        
        根據查詢類型和複雜度，決定：
        - 是否使用 HyDE
        - 是否使用查詢分解
        - top_k 數量
        - 是否使用 Reranker
        """
        strategy = {
            "use_hyde": False,
            "use_decomposition": False,
            "top_k": 5,
            "use_rerank": False
        }
        
        # INFO: 簡單快速
        if query_type == "INFO":
            strategy["top_k"] = 5
            strategy["use_rerank"] = False
        
        # PROFESSIONAL: 精確但不過度複雜
        elif query_type == "PROFESSIONAL":
            strategy["top_k"] = 8
            strategy["use_rerank"] = False  # 避免 Reranker 降低準確度
        
        # COMPLEX: 全力以赴
        elif query_type == "COMPLEX":
            strategy["top_k"] = 10
            strategy["use_rerank"] = False  # 同上
            strategy["use_decomposition"] = True
        
        # 根據複雜度微調
        if complexity >= self.complexity_thresholds["complex"]:
            strategy["top_k"] = max(strategy["top_k"], 10)
        
        return strategy
    
    def decompose_query(self, query: str) -> List[str]:
        """
        分解複雜查詢為子問題
        
        規則：
        - 以標點符號分隔
        - 保留完整語義
        - 最多3個子問題
        """
        # 簡單的分解策略：以頓號、逗號分隔
        separators = ['，', '、', '；', '，且', '，並']
        
        sub_questions = [query]  # 預設返回原查詢
        
        for sep in separators:
            if sep in query:
                parts = query.split(sep)
                # 過濾太短的部分
                sub_questions = [p.strip() for p in parts if len(p.strip()) > 5]
                break
        
        # 限制數量
        return sub_questions[:3]
    
    def generate_reasoning(self, query_type: str, topics: List[str], complexity: float) -> str:
        """生成分析推理說明"""
        reasoning_parts = []
        
        # 查詢類型
        type_desc = {
            "INFO": "一般資訊查詢",
            "PROFESSIONAL": "專業法律諮詢",
            "COMPLEX": "複雜多面向問題"
        }
        reasoning_parts.append(f"查詢類型：{type_desc.get(query_type, query_type)}")
        
        # 主題
        if topics:
            reasoning_parts.append(f"識別主題：{', '.join(topics)}")
        
        # 複雜度
        if complexity < 3:
            complexity_desc = "低（簡單問題）"
        elif complexity < 6:
            complexity_desc = "中（標準問題）"
        else:
            complexity_desc = "高（複雜問題）"
        reasoning_parts.append(f"複雜度：{complexity:.1f}/10 ({complexity_desc})")
        
        return " | ".join(reasoning_parts)







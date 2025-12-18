"""
Knowledge Graph Module - 知識圖譜模組

用途：
- 載入並查詢法律條文知識圖譜
- 提供條文關聯查詢
- 匹配預定義情境
- 強化檢索結果

基於 NetworkX 實現圖遍歷和查詢
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
KG_PATH = ROOT / "data" / "knowledge_graph.json"


class KnowledgeGraph:
    """
    知識圖譜類
    
    功能：
    1. 載入條文實體與關聯
    2. 圖遍歷查找相關條文
    3. 匹配預定義情境
    4. 返回必需條文清單
    """
    
    def __init__(self, kg_path: Path = KG_PATH):
        """初始化知識圖譜"""
        self.kg_path = kg_path
        self.data: Dict = {}
        self.graph: nx.DiGraph = nx.DiGraph()
        self.entities: Dict = {}
        self.scenarios: Dict = {}
        
        if self.kg_path.exists():
            self._load()
        else:
            print(f"[KG] Warning: Knowledge graph not found at {kg_path}")
    
    def _load(self) -> None:
        """載入知識圖譜數據"""
        with open(self.kg_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        self.entities = self.data.get("entities", {})
        self.scenarios = self.data.get("scenarios", {})
        
        # 建立 NetworkX 圖
        self._build_graph()
        
        metadata = self.data.get("metadata", {})
        print(f"[KG] Loaded: {metadata.get('entity_count', 0)} entities, "
              f"{metadata.get('relation_count', 0)} relations, "
              f"{metadata.get('scenario_count', 0)} scenarios")
    
    def _build_graph(self) -> None:
        """建立 NetworkX 有向圖"""
        # 添加節點
        for entity_id, entity_data in self.entities.items():
            self.graph.add_node(entity_id, **entity_data)
        
        # 添加邊
        relations = self.data.get("relations", [])
        for rel in relations:
            self.graph.add_edge(
                rel["from"],
                rel["to"],
                type=rel["type"],
                description=rel.get("description", "")
            )
    
    def find_related_articles(
        self,
        article_id: str,
        max_depth: int = 2,
        relation_types: Optional[List[str]] = None
    ) -> List[Tuple[str, int, Dict]]:
        """
        找到相關條文（透過圖遍歷）
        
        Args:
            article_id: 條文ID（如「勞動基準法第22條」）
            max_depth: 最大遍歷深度
            relation_types: 限制關係類型（如 ["參照", "補充說明"]）
        
        Returns:
            List of (article_id, depth, article_data)
        """
        if article_id not in self.graph:
            return []
        
        related = []
        visited: Set[str] = set()
        queue: List[Tuple[str, int]] = [(article_id, 0)]
        
        while queue:
            node, depth = queue.pop(0)
            
            if node in visited or depth > max_depth:
                continue
            
            visited.add(node)
            
            # 添加到結果（排除起始節點）
            if node != article_id:
                node_data = self.graph.nodes.get(node, {})
                related.append((node, depth, node_data))
            
            # 遍歷鄰居
            if depth < max_depth:
                for neighbor in self.graph.neighbors(node):
                    if neighbor not in visited:
                        # 檢查關係類型
                        edge_data = self.graph.get_edge_data(node, neighbor, {})
                        rel_type = edge_data.get("type", "")
                        
                        if relation_types is None or rel_type in relation_types:
                            queue.append((neighbor, depth + 1))
        
        return related
    
    def match_scenario(self, query: str) -> Optional[Dict]:
        """
        匹配預定義情境
        
        Args:
            query: 查詢文本
        
        Returns:
            情境字典，如果沒有匹配則返回 None
        """
        for scenario_id, scenario in self.scenarios.items():
            scenario_name = scenario.get("name", "")
            # 簡單關鍵詞匹配
            if any(kw in query for kw in scenario_name):
                return scenario
        
        return None
    
    def get_required_articles(self, query: str) -> List[str]:
        """
        取得查詢必需的條文清單
        
        Args:
            query: 查詢文本
        
        Returns:
            條文ID列表（如 ["勞動基準法第22條", ...]）
        """
        scenario = self.match_scenario(query)
        if scenario:
            return scenario.get("required_articles", [])
        return []
    
    def get_article_info(self, article_id: str) -> Optional[Dict]:
        """
        獲取條文詳細信息
        
        Args:
            article_id: 條文ID
        
        Returns:
            條文數據字典
        """
        return self.entities.get(article_id)
    
    def search_by_keyword(
        self,
        keyword: str,
        limit: int = 10
    ) -> List[Tuple[str, Dict]]:
        """
        透過關鍵詞搜索條文
        
        Args:
            keyword: 關鍵詞
            limit: 返回數量上限
        
        Returns:
            List of (article_id, article_data)
        """
        results = []
        
        for entity_id, entity_data in self.entities.items():
            # 在標題、關鍵詞、適用主題中搜索
            title = entity_data.get("title", "")
            keywords = entity_data.get("keywords", [])
            topics = entity_data.get("topics", [])
            
            if (keyword in title or
                any(keyword in kw for kw in keywords) or
                any(keyword in topic for topic in topics)):
                results.append((entity_id, entity_data))
            
            if len(results) >= limit:
                break
        
        return results
    
    def get_scenario_reasoning(self, query: str) -> Optional[str]:
        """
        獲取情境的推理說明
        
        Args:
            query: 查詢文本
        
        Returns:
            推理說明文本
        """
        scenario = self.match_scenario(query)
        if scenario:
            return scenario.get("reasoning", "")
        return None
    
    def get_common_errors(self, query: str) -> List[str]:
        """
        獲取常見錯誤提示
        
        Args:
            query: 查詢文本
        
        Returns:
            常見錯誤列表
        """
        scenario = self.match_scenario(query)
        if scenario:
            return scenario.get("common_errors", [])
        return []
    
    def enhance_citations(
        self,
        citations: List[Dict],
        query: str
    ) -> List[Dict]:
        """
        基於知識圖譜增強引用
        
        Args:
            citations: 原始引用列表
            query: 查詢文本
        
        Returns:
            增強後的引用列表
        """
        # 檢查是否匹配預定義情境
        required_articles = self.get_required_articles(query)
        
        if not required_articles:
            return citations
        
        # 檢查必需條文是否已在引用中
        cited_ids = set()
        for cite in citations:
            law_name = cite.get("law_name", "")
            article_no = cite.get("article_no", "")
            if law_name and article_no:
                article_id = f"{law_name}第{article_no}條"
                cited_ids.add(article_id)
        
        # 添加缺失的必需條文
        enhanced = list(citations)
        for req_art in required_articles:
            if req_art not in cited_ids:
                article_info = self.get_article_info(req_art)
                if article_info:
                    # 構建引用格式
                    enhanced.append({
                        "law_name": article_info.get("law", ""),
                        "article_no": article_info.get("article", ""),
                        "heading": article_info.get("title", ""),
                        "text": "",  # 需要從其他地方獲取完整文本
                        "source": "knowledge_graph",
                        "kg_enforced": True
                    })
        
        return enhanced


# 全局實例（單例模式）
_KG_INSTANCE: Optional[KnowledgeGraph] = None


def get_knowledge_graph() -> KnowledgeGraph:
    """獲取知識圖譜實例（單例）"""
    global _KG_INSTANCE
    if _KG_INSTANCE is None:
        _KG_INSTANCE = KnowledgeGraph()
    return _KG_INSTANCE


def is_available() -> bool:
    """檢查知識圖譜是否可用"""
    return KG_PATH.exists()













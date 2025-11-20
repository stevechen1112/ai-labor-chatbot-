"""
Reranker Module - 二次排序模組

用途：
- 對混合檢索的初步結果進行精細化重排序
- 使用 Cross-Encoder 模型進行 query-passage 相關性打分
- 提升 Top-K 結果的精確度

模型：BAAI/bge-reranker-v2-m3
- 多語言支持（中文、英文等）
- 基於 Cross-Encoder 架構
- 輸入：(query, passage) 對
- 輸出：相關性分數（0-1）
"""

from typing import List, Dict, Tuple, Optional
from pathlib import Path
import time

try:
    from FlagEmbedding import FlagReranker
    RERANKER_AVAILABLE = True
except ImportError:
    RERANKER_AVAILABLE = False
    FlagReranker = None

ROOT = Path(__file__).resolve().parents[1]

# 全局實例緩存（避免重複載入模型）
_RERANKER_INSTANCE: Optional['Reranker'] = None


class Reranker:
    """
    Reranker 類別：使用 Cross-Encoder 進行二次排序
    
    使用方式：
        reranker = Reranker()
        ranked = reranker.rerank(
            query="加班費如何計算？",
            candidates=[{"text": "...", "metadata": {...}}, ...],
            top_k=5
        )
    """
    
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool = True,
        device: Optional[str] = None
    ):
        """
        初始化 Reranker
        
        Args:
            model_name: Reranker 模型名稱
            use_fp16: 是否使用 FP16 加速（需 GPU）
            device: 指定設備（'cpu', 'cuda', 'cuda:0' 等）
        """
        if not RERANKER_AVAILABLE:
            raise RuntimeError(
                "FlagEmbedding 未安裝。請執行：pip install FlagEmbedding"
            )
        
        self.model_name = model_name
        self.use_fp16 = use_fp16
        self.device = device
        
        # 載入模型
        print(f"[Reranker] 載入模型：{model_name}")
        start_time = time.time()
        
        try:
            self.model = FlagReranker(
                model_name,
                use_fp16=use_fp16,
                device=device
            )
            load_time = time.time() - start_time
            print(f"[Reranker] 模型載入完成，耗時 {load_time:.2f} 秒")
        except Exception as e:
            print(f"[Reranker] 模型載入失敗：{e}")
            raise
    
    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        top_k: int = 5,
        text_key: str = "text",
        batch_size: int = 32
    ) -> List[Dict]:
        """
        對候選結果進行重排序
        
        Args:
            query: 查詢文本
            candidates: 候選結果列表
                格式：[{"text": "...", "score": 0.8, ...}, ...]
            top_k: 返回前 K 個結果
            text_key: 候選字典中文本的鍵名（預設 "text"）
            batch_size: 批次大小（影響記憶體使用）
        
        Returns:
            重排序後的候選列表（前 top_k 個）
        """
        if not candidates:
            return []
        
        # 構建 (query, passage) 對
        pairs = []
        for candidate in candidates:
            text = candidate.get(text_key, "")
            if not text:
                # 若無文本，嘗試其他可能的鍵
                text = candidate.get("content", "") or candidate.get("snippet", "") or ""
            pairs.append([query, text])
        
        # 批次計算相關性分數
        try:
            start_time = time.time()
            scores = self.model.compute_score(
                pairs,
                normalize=True,
                batch_size=batch_size
            )
            inference_time = time.time() - start_time
            
            # 確保 scores 是列表
            if not isinstance(scores, list):
                scores = scores.tolist() if hasattr(scores, 'tolist') else [scores]
            
            # 將分數加入候選字典
            for i, candidate in enumerate(candidates):
                candidate['rerank_score'] = float(scores[i])
            
            # 排序並返回 Top-K
            ranked = sorted(
                candidates,
                key=lambda x: x.get('rerank_score', 0),
                reverse=True
            )
            
            avg_time_per_pair = inference_time / len(pairs) * 1000  # ms
            print(f"[Reranker] 重排序完成：{len(pairs)} 個候選，耗時 {inference_time:.3f}s ({avg_time_per_pair:.2f}ms/pair)")
            
            return ranked[:top_k]
            
        except Exception as e:
            print(f"[Reranker] 重排序失敗：{e}")
            # 降級處理：返回原始候選
            return candidates[:top_k]
    
    def compute_scores(
        self,
        query: str,
        passages: List[str],
        batch_size: int = 32
    ) -> List[float]:
        """
        計算查詢與多個段落的相關性分數
        
        Args:
            query: 查詢文本
            passages: 段落列表
            batch_size: 批次大小
        
        Returns:
            相關性分數列表（0-1）
        """
        if not passages:
            return []
        
        pairs = [[query, p] for p in passages]
        
        try:
            scores = self.model.compute_score(
                pairs,
                normalize=True,
                batch_size=batch_size
            )
            
            if not isinstance(scores, list):
                scores = scores.tolist() if hasattr(scores, 'tolist') else [scores]
            
            return [float(s) for s in scores]
        
        except Exception as e:
            print(f"[Reranker] 計算分數失敗：{e}")
            return [0.0] * len(passages)


def get_reranker(model_name: str = "BAAI/bge-reranker-v2-m3") -> Reranker:
    """
    獲取全局 Reranker 實例（單例模式）
    
    Args:
        model_name: 模型名稱
    
    Returns:
        Reranker 實例
    """
    global _RERANKER_INSTANCE
    
    if _RERANKER_INSTANCE is None:
        _RERANKER_INSTANCE = Reranker(model_name=model_name)
    
    return _RERANKER_INSTANCE


def is_available() -> bool:
    """檢查 Reranker 是否可用"""
    return RERANKER_AVAILABLE


"""
簡單的問題分類器
借鑒 UniHR 的分類邏輯，但保持簡潔
"""

# 問題類型定義
INFO = "INFO"               # 資訊查詢類
PROFESSIONAL = "PROFESSIONAL"  # 專業諮詢類

# 資訊查詢關鍵詞
INFO_KEYWORDS = [
    "什麼是", "如何計算", "怎麼算", "規定", "幾天", "多少", 
    "什麼", "哪些", "介紹", "說明", "解釋", "定義",
    "是什麼", "是指", "內容", "範圍"
]

# 專業諮詢指標
PROFESSIONAL_KEYWORDS = [
    "可以嗎", "合法嗎", "是否可以", "是否合法", 
    "怎麼辦", "如何處理", "建議", "風險", 
    "我該", "我應該", "可能", "需要注意",
    "違法", "爭議", "糾紛", "訴訟",
    "拒絕", "合理", "正當", "可以拒絕"
]


def classify_query(query: str) -> str:
    """
    對用戶問題進行簡單分類
    
    Args:
        query: 用戶問題
        
    Returns:
        query_type: INFO 或 PROFESSIONAL
    """
    query_lower = query.lower().strip()
    
    # 計算專業諮詢評分
    professional_score = 0
    
    # 包含專業諮詢關鍵詞
    for keyword in PROFESSIONAL_KEYWORDS:
        if keyword in query_lower:
            professional_score += 1
    
    # 問題較長且複雜（> 30 字且包含逗號）
    if len(query_lower) > 30 and ("，" in query_lower or "、" in query_lower):
        professional_score += 1
    
    # 包含多個問號（表示複雜情境）
    if query_lower.count("？") > 1 or query_lower.count("?") > 1:
        professional_score += 1
    
    # 判斷分類
    if professional_score >= 2:
        return PROFESSIONAL
    
    # 明確包含資訊查詢關鍵詞
    for keyword in INFO_KEYWORDS:
        if keyword in query_lower:
            return INFO
    
    # 預設為資訊查詢
    return INFO


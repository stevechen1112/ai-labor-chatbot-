"""
SQLite 資料庫 Schema 與初始化

用途：
- 替換 in-memory 儲存
- 持久化會話、回饋、指標歷史

Schema 設計原則：
- 簡單、高效、易擴展
- 支援時間序列查詢
- 保留 30 日資料（可配置）
"""
import sqlite3
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import json
from contextlib import contextmanager

# 資料庫路徑
DB_PATH = Path(__file__).parent.parent / "data" / "app.db"

# Schema 定義
SCHEMA = """
-- 會話表（對話歷史）
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,  -- 未來擴展：用戶 ID
    metadata TEXT  -- JSON: 用戶 IP、User-Agent 等
);

-- 訊息表（會話中的每條查詢與回答）
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    query TEXT,  -- 原始查詢（role=user 時）
    normalized_query TEXT,  -- 重寫後的查詢
    citations_count INTEGER DEFAULT 0,  -- 引用數量
    used_llm BOOLEAN DEFAULT 0,  -- 是否使用 LLM
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

-- 引用表（每條回答的引用詳情）
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    law_id TEXT NOT NULL,
    title TEXT,
    article_no TEXT,
    heading TEXT,
    text_preview TEXT,  -- 引用文本前 200 字
    source_url TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- 回饋表（用戶反饋）
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message_id INTEGER,  -- 可選：針對特定訊息的回饋
    rating INTEGER,  -- 1-5 星評分
    feedback_type TEXT,  -- 'helpful', 'incorrect', 'incomplete', 'other'
    comment TEXT,  -- 用戶文字評論
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
);

-- 引用錯誤回報
CREATE TABLE IF NOT EXISTS citation_error_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    citation_id TEXT,
    session_id TEXT,
    law_name TEXT,
    article_no TEXT,
    error_reason TEXT NOT NULL,
    severity TEXT DEFAULT 'CRITICAL',
    status TEXT DEFAULT 'PENDING',
    metadata TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 指標歷史表（系統指標時間序列）
CREATE TABLE IF NOT EXISTS metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_queries INTEGER NOT NULL,
    total_sessions INTEGER NOT NULL,
    total_feedback INTEGER NOT NULL,
    avg_latency_ms REAL,
    avg_citations REAL,
    queries_last_hour INTEGER,
    queries_last_day INTEGER,
    uptime_seconds INTEGER,
    metadata TEXT  -- JSON: 其他動態指標
);

-- 查詢日誌表（用於分析與調試）
CREATE TABLE IF NOT EXISTS query_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    query TEXT NOT NULL,
    normalized_query TEXT,
    topic TEXT,  -- 主題（overtime, annual_leave 等）
    citations_count INTEGER,
    latency_ms INTEGER,
    used_llm BOOLEAN,
    error TEXT,  -- 錯誤訊息（若有）
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 索引（優化查詢性能）
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_citations_message_id ON citations(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_session_id ON feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_query_logs_created_at ON query_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_query_logs_topic ON query_logs(topic);
CREATE INDEX IF NOT EXISTS idx_citation_error_reports_created_at ON citation_error_reports(created_at);
"""


class Database:
    """SQLite 資料庫管理類"""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化資料庫（建立表與索引）"""
        with self.get_conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
    
    @contextmanager
    def get_conn(self):
        """Context manager 取得資料庫連線"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # 允許以字典形式訪問列
        try:
            yield conn
        finally:
            conn.close()
    
    def cleanup_old_data(self, days: int = 30):
        """清除超過指定天數的舊資料"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_conn() as conn:
            # 刪除舊會話（級聯刪除關聯的 messages, citations, feedback）
            conn.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
            # 刪除舊指標歷史
            conn.execute("DELETE FROM metrics_history WHERE timestamp < ?", (cutoff,))
            # 刪除舊查詢日誌
            conn.execute("DELETE FROM query_logs WHERE created_at < ?", (cutoff,))
            conn.commit()
    
    # === 會話管理 ===
    
    def create_session(self, session_id: str, user_id: Optional[str] = None, 
                      metadata: Optional[Dict] = None) -> str:
        """建立新會話"""
        with self.get_conn() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, user_id, metadata) VALUES (?, ?, ?)",
                (session_id, user_id, json.dumps(metadata) if metadata else None)
            )
            conn.commit()
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """取得會話資訊"""
        with self.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", 
                (session_id,)
            ).fetchone()
            if row:
                return dict(row)
        return None
    
    def add_message(self, session_id: str, role: str, content: str, 
                   query: Optional[str] = None, normalized_query: Optional[str] = None,
                   citations_count: int = 0, used_llm: bool = False) -> int:
        """新增訊息至會話"""
        with self.get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO messages 
                   (session_id, role, content, query, normalized_query, citations_count, used_llm)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, role, content, query, normalized_query, citations_count, used_llm)
            )
            # 更新會話 updated_at
            conn.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,)
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_session_messages(self, session_id: str) -> List[Dict]:
        """取得會話的所有訊息"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at",
                (session_id,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    def add_citations(self, message_id: int, citations: List[Dict]):
        """新增引用至訊息"""
        with self.get_conn() as conn:
            for cite in citations:
                conn.execute(
                    """INSERT INTO citations 
                       (message_id, law_id, title, article_no, heading, text_preview, source_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (message_id, cite.get("law_id"), cite.get("title"), 
                     cite.get("article_no"), cite.get("heading"), 
                     cite.get("text", "")[:200], cite.get("source_url"))
                )
            conn.commit()
    
    # === 回饋管理 ===
    
    def add_feedback(self, session_id: str, rating: Optional[int] = None,
                    feedback_type: Optional[str] = None, comment: Optional[str] = None,
                    message_id: Optional[int] = None):
        """新增用戶回饋"""
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO feedback 
                   (session_id, message_id, rating, feedback_type, comment)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, message_id, rating, feedback_type, comment)
            )
            conn.commit()
    
    def get_recent_feedback(self, limit: int = 100) -> List[Dict]:
        """取得最近的回饋"""
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # === 引用錯誤回報 ===

    def add_citation_error_report(
        self,
        citation_id: str,
        error_reason: str,
        session_id: Optional[str] = None,
        law_name: Optional[str] = None,
        article_no: Optional[str] = None,
        severity: str = "CRITICAL",
        metadata: Optional[Dict] = None,
    ):
        """紀錄引用錯誤回報"""
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO citation_error_reports
                    (citation_id, session_id, law_name, article_no, error_reason, severity, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (citation_id, session_id, law_name, article_no, error_reason, severity, metadata_json),
            )
            conn.commit()
    
    def get_citation_error_reports(
        self,
        limit: int = 50,
        status: Optional[str] = None
    ) -> List[Dict]:
        """查詢引用錯誤回報"""
        with self.get_conn() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM citation_error_reports
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM citation_error_reports
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,)
                ).fetchall()
            return [dict(row) for row in rows]
    
    # === 指標管理 ===
    
    def add_metrics_snapshot(self, metrics: Dict):
        """新增指標快照"""
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO metrics_history 
                   (total_queries, total_sessions, total_feedback, 
                    avg_latency_ms, avg_citations, queries_last_hour, 
                    queries_last_day, uptime_seconds, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (metrics.get("total_queries"), metrics.get("total_sessions"),
                 metrics.get("total_feedback"), metrics.get("avg_latency_ms"),
                 metrics.get("avg_citations"), metrics.get("queries_last_hour"),
                 metrics.get("queries_last_day"), metrics.get("uptime_seconds"),
                 json.dumps(metrics.get("metadata", {})))
            )
            conn.commit()
    
    def get_metrics_history(self, hours: int = 24) -> List[Dict]:
        """取得指標歷史（時間序列）"""
        cutoff = datetime.now() - timedelta(hours=hours)
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM metrics_history WHERE timestamp >= ? ORDER BY timestamp",
                (cutoff,)
            ).fetchall()
            return [dict(row) for row in rows]
    
    # === 查詢日誌 ===
    
    def log_query(self, query: str, session_id: Optional[str] = None,
                 normalized_query: Optional[str] = None, topic: Optional[str] = None,
                 citations_count: int = 0, latency_ms: int = 0,
                 used_llm: bool = False, error: Optional[str] = None):
        """記錄查詢日誌"""
        with self.get_conn() as conn:
            conn.execute(
                """INSERT INTO query_logs 
                   (session_id, query, normalized_query, topic, citations_count,
                    latency_ms, used_llm, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, query, normalized_query, topic, citations_count,
                 latency_ms, used_llm, error)
            )
            conn.commit()
    
    def get_query_stats(self, days: int = 7) -> Dict:
        """取得查詢統計（主題分布、平均延遲等）"""
        cutoff = datetime.now() - timedelta(days=days)
        with self.get_conn() as conn:
            # 主題分布
            topics = conn.execute(
                """SELECT topic, COUNT(*) as count 
                   FROM query_logs 
                   WHERE created_at >= ? AND topic IS NOT NULL
                   GROUP BY topic 
                   ORDER BY count DESC""",
                (cutoff,)
            ).fetchall()
            
            # 平均延遲
            avg_latency = conn.execute(
                "SELECT AVG(latency_ms) FROM query_logs WHERE created_at >= ?",
                (cutoff,)
            ).fetchone()[0] or 0
            
            # 總查詢數
            total = conn.execute(
                "SELECT COUNT(*) FROM query_logs WHERE created_at >= ?",
                (cutoff,)
            ).fetchone()[0]
            
            return {
                "topics": [{"topic": t[0], "count": t[1]} for t in topics],
                "avg_latency_ms": avg_latency,
                "total_queries": total,
                "period_days": days
            }


# 全域資料庫實例
_db_instance: Optional[Database] = None


def get_db() -> Database:
    """取得全域資料庫實例（單例模式）"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance










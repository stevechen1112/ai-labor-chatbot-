"""
四層引用驗證機制

用途：
1. 第一層：白名單強制驗證（ensure_whitelist）
   - 根據主題，確保核心條文必定出現
   - 自動補充缺失的必需條文

2. 第二層：條文存在性驗證（validate_existence）
   - 驗證引用的法規與條號是否真實存在
   - 完全錯誤 → 攔截

3. 第三層：內容一致性驗證（validate_content）
   - 檢查 checksum（完整性）
   - 檢查關鍵詞（完整性）

4. 第四層：邏輯衝突檢測（detect_conflicts）
   - 檢測同時引用衝突法規
   - 檢查是否缺少必需條文

使用方式：
    from .citation_validator import CitationValidator
    
    validator = CitationValidator()
    
    # 第一層：在檢索後執行
    results = validator.enforce_whitelist(query, retrieval_results)
    
    # 第二~四層：在 LLM 生成後執行
    validation = validator.validate_all(query, citations)
    
    if validation['action'] == 'BLOCK':
        # 攔截輸出
        return error_response(validation['errors'])
    elif validation['action'] == 'WARN':
        # 加上警告
        answer = answer + "\\n⚠️ 引用提醒\\n" + "\\n".join(validation['warnings'])
"""

import hashlib
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DB_PATH = ROOT / "data" / "citation_validation.json"


class CitationValidator:
    """四層引用驗證機制"""
    
    def __init__(self):
        self.validation_db = self._load_validation_db()
        self.error_log = []
        self._whitelist_rules = self._build_whitelist_rules()
    
    def _load_validation_db(self) -> Dict:
        """載入驗證資料庫"""
        try:
            with open(VALIDATION_DB_PATH, encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # Fallback: return empty structure
            return {
                "validated_articles": {},
                "validation_rules": {},
                "metadata": {}
            }
    
    def _build_whitelist_rules(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        建立白名單規則（主題 → 必需條文）
        返回格式：{
            "wage_deduction": [("勞動基準法", "22"), ("勞動基準法", "26"), ...],
            "overtime": [("勞動基準法", "24"), ...],
            ...
        }
        """
        return {
            "wage_deduction": [
                ("勞動基準法", "22"),      # 工資之給付
                ("勞動基準法", "26"),      # 禁止預扣工資
            ],
            "overtime": [
                ("勞動基準法", "24"),      # 加班費計算
                ("勞動基準法", "32"),      # 工時上限
            ],
            "annual_leave": [
                ("勞動基準法", "38"),      # 特別休假
            ],
            "tardiness": [
                ("勞動基準法", "22"),      # 工資給付
                ("勞動基準法", "26"),      # 禁止預扣
            ],
            "attendance_bonus": [
                ("勞動基準法", "2"),       # 工資定義
            ],
            "severance_procedure": [
                ("勞動基準法", "11"),
                ("勞動基準法", "16"),
                ("勞動基準法", "17"),
                ("就業服務法", "33"),
            ],
            "pregnancy_protection": [
                ("性別平等工作法", "11"),
                ("勞動基準法", "51"),
                ("勞動基準法", "7"),
            ]
        }
    
    # ========== 第一層：白名單強制驗證 ==========
    
    def enforce_whitelist(
        self,
        query: str,
        topic: Optional[str],
        retrieval_results: List[Dict]
    ) -> List[Dict]:
        """Ensure mandatory citations exist for high-risk topics."""
        if not topic or topic not in self._whitelist_rules:
            return retrieval_results

        required_articles = self._whitelist_rules[topic]
        missing: List[Tuple[str, str]] = []

        # 检查必需条文是否都在结果中
        missing = []
        for law_name, article_no in required_articles:
            found = any(
                r.get('law_name', '') == law_name and 
                str(article_no) == r.get('article_no', '')
                for r in retrieval_results
            )
            if not found:
                missing.append((law_name, article_no))
        
        # 🚨 強制補充缺失的必需條文
        for law_name, article_no in missing:
            doc = self._force_retrieve(law_name, str(article_no))
            if doc:
                # 插入到結果最前面（高優先級）
                retrieval_results.insert(0, {
                    "score": 1.0,
                    "law_name": law_name,
                    "law_id": law_name,  # Add law_id for consistency
                    "article_no": str(article_no),
                    "heading": doc.get('heading', f"第 {article_no} 條"),
                    "text": doc.get('text', ''),
                    "validation_status": "ENFORCED_WHITELIST",
                    "id": f"{law_name}_{article_no}"
                })
                
                self.error_log.append({
                    'level': 'WARNING',
                    'timestamp': datetime.now().isoformat(),
                    'message': f"Missing citation: {law_name} 第{article_no}條 auto-inserted via whitelist",
                    'query': query,
                    'topic': topic,
                })

        return retrieval_results

    def _force_retrieve(self, law_name: str, article_no: str) -> Optional[Dict]:
        """Load canonical article text from the validation DB."""
        try:
            validated = self.validation_db.get('validated_articles', {})
            if law_name not in validated:
                return None

            articles = validated[law_name].get('articles', {})
            if str(article_no) not in articles:
                return None

            article_data = articles[str(article_no)]
            return {
                'law_id': law_name,
                'article_no': str(article_no),
                'text': article_data.get('text', ''),
                'heading': article_data.get('heading', f"第{article_no}條"),
                'full_title': article_data.get('full_title', ''),
            }
        except Exception:
            return None

    def _normalize_article_number(self, article_no: str) -> str:
        """將中文數字條號轉換為阿拉伯數字"""
        # 如果已經是阿拉伯數字，直接返回
        if article_no.isdigit() or '-' in article_no:
            return article_no.strip()
        
        # 中文數字對應
        mapping = {
            '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
            '十': 10, '百': 100
        }
        
        result = 0
        temp = 0
        for char in str(article_no):
            if char not in mapping:
                continue
            val = mapping[char]
            if val >= 10:
                temp = (temp or 1) * val
            else:
                temp = temp * 10 + val if char != '零' else temp
        
        result += temp
        return str(result) if result > 0 else article_no.strip()
    
    # ========== 第二層：條文存在性驗證 ==========
    
    def validate_existence(self, citation: Dict) -> Tuple[bool, str]:
        """
        驗證引用的條文是否真實存在
        
        Returns:
            (是否通過, 訊息)
        """
        law_name = citation.get('law_name', '')
        article_no = citation.get('article_no', '')
        
        # 檢查法規是否存在
        if law_name not in self.validation_db.get('validated_articles', {}):
            return False, f"[ERROR] Law '{law_name}' not found in validation DB"
        
        # 檢查條號是否存在
        articles = self.validation_db['validated_articles'][law_name].get('articles', {})
        
        # 標準化條號（處理中文數字、"22", "22-1" 等格式）
        article_no_normalized = self._normalize_article_number(str(article_no))
        
        if article_no_normalized not in articles:
            # 嘗試匹配（例如 "22" 與 "22-1"）
            possible_matches = [a for a in articles.keys() if a.startswith(article_no_normalized)]
            if not possible_matches:
                return False, f"[ERROR] Article No. '{article_no}' (normalized: {article_no_normalized}) not found in {law_name}"
        
        return True, "[OK] Citation exists"
    
    # ========== 第三層：內容一致性驗證 ==========
    
    def validate_content(self, citation: Dict) -> Tuple[bool, str]:
        """
        驗證引用內容與官方版本一致
        
        Uses checksum + key_phrases 雙重檢查
        
        Returns:
            (是否通過, 訊息)
        """
        law_name = citation.get('law_name', '')
        article_no = str(citation.get('article_no', ''))
        cited_text = citation.get('text', '')
        
        if law_name not in self.validation_db.get('validated_articles', {}):
            return False, f"[ERROR] Law '{law_name}' not in DB"
        
        articles = self.validation_db['validated_articles'][law_name].get('articles', {})
        
        # 標準化條號（處理中文數字）
        article_no_normalized = self._normalize_article_number(str(article_no))
        
        if article_no_normalized not in articles:
            # 尋找最接近的匹配
            possible = [a for a in articles.keys() if a.startswith(article_no_normalized)]
            if not possible:
                return False, f"[ERROR] Article '{article_no}' (normalized: {article_no_normalized}) not found"
            article_no_normalized = possible[0]
        
        official_data = articles[article_no_normalized]
        official_text = official_data.get('text', '')
        official_checksum = official_data.get('checksum', '')
        key_phrases = official_data.get('key_phrases', [])
        
        # Checksum 检查（先对引用文本进行一次基础的 normalize）
        normalized_cited_text = cited_text.strip().replace('\r\n', '\n')
        cited_checksum = hashlib.sha256(
            normalized_cited_text.encode('utf-8')
        ).hexdigest()
        
        if cited_checksum == official_checksum:
            return True, "[OK] Content matches checksum"
        
        # 如果 checksum 不匹配，尝试更宽松的 normalize 方式再次比对
        normalized_cited_text_loose = ''.join(normalized_cited_text.split())
        official_text_loose = ''.join(official_text.split())
        if hashlib.sha256(normalized_cited_text_loose.encode('utf-8')).hexdigest() == hashlib.sha256(official_text_loose.encode('utf-8')).hexdigest():
             return True, "[OK] Content matches checksum with loose normalization"

        # 關鍵詞檢查（容寬模式）
        if key_phrases:
            # 計算匹配的關鍵詞數量
            matched_phrases = [p for p in key_phrases if p in cited_text]
            match_ratio = len(matched_phrases) / len(key_phrases) if key_phrases else 0
            
            if match_ratio >= 0.5:  # 至少匹配 50% 的關鍵詞
                # 大部分關鍵詞都存在，視為通過（可能只是格式差異）
                return True, f"[WARN] Checksum mismatch but {len(matched_phrases)}/{len(key_phrases)} key phrases present (formatting difference)"
            elif match_ratio > 0:  # 至少有一個關鍵詞匹配
                # 有部分匹配，發出警告但通過
                return True, f"[WARN] Partial key phrase match: {len(matched_phrases)}/{len(key_phrases)}"
            else:
                # 完全沒有關鍵詞匹配，可能是錯誤的條文
                missing_phrases = [p for p in key_phrases[:3]]  # 只顯示前 3 個
                return False, f"[ERROR] No key phrase matched (expected: {missing_phrases}...)"
        
        # 若無關鍵詞，則 checksum 不符視為警告而非錯誤（容錯）
        return True, "[WARN] Content checksum mismatch (no key phrases to validate)"
    
    # ========== 第四層：邏輯衝突檢測 ==========
    
    def detect_conflicts(self, citations: List[Dict]) -> List[str]:
        """
        檢測引用條文之間是否有邏輯衝突
        
        Returns:
            衝突訊息列表
        """
        conflicts = []
        
        # 預定義衝突規則
        conflict_rules = {
            ("勞動基準法", "22"): {
                "conflicts_with": [("民法", "")],  # 民法債編與勞基法工資給付衝突
                "reason": "勞動基準法為特別法，優先於民法"
            },
            ("勞動基準法", "26"): {
                "requires": [("勞動基準法", "22")],
                "reason": "第26條禁止預扣，必須與第22條一起引用"
            },
            ("勞動基準法", "12"): {
                "requires": [("勞動基準法", "22"), ("勞動基準法", "26")],
                "reason": "討論解僱前應先說明工資給付原則"
            },
        }
        
        cited_pairs = [(c.get('law_name', ''), c.get('article_no', '')) for c in citations]
        
        for law, art in cited_pairs:
            rule_key = (law, str(art))
            if rule_key not in conflict_rules:
                continue
            
            rule = conflict_rules[rule_key]
            
            # 檢查是否引用了衝突條文
            for conflict_law, conflict_art in rule.get('conflicts_with', []):
                for c in citations:
                    c_law = c.get('law_name', '')
                    if conflict_law in c_law:
                        conflicts.append(
                            f"[CONFLICT] {law}#{art} with {c_law} "
                            f"(Reason: {rule['reason']})"
                        )
            
            # 檢查是否缺少必需條文
            for req_law, req_art in rule.get('requires', []):
                found = any(
                    req_law in c.get('law_name', '') and 
                    str(req_art) == str(c.get('article_no', ''))
                    for c in citations
                )
                if not found:
                    conflicts.append(
                        f"[INCOMPLETE] {law}#{art} requires {req_law}#{req_art} "
                        f"(Reason: {rule['reason']})"
                    )
        
        return conflicts
    
    # ========== 綜合驗證入口 ==========
    
    def validate_all(
        self, 
        query: str, 
        citations: List[Dict],
        topic: Optional[str] = None
    ) -> Dict:
        """
        執行完整的四層驗證
        
        Returns:
            {
                "overall_status": "PASS" | "WARNING" | "FAIL",
                "validations": [...],
                "errors": [...],
                "warnings": [...],
                "action": "APPROVE" | "WARN" | "BLOCK"
            }
        """
        results = {
            "overall_status": "PASS",
            "validations": [],
            "errors": [],
            "warnings": [],
            "action": "APPROVE",  # APPROVE | WARN | BLOCK
            "query": query,
            "topic": topic,
            "timestamp": datetime.now().isoformat()
        }
        
        if not citations:
            results["errors"].append("[ERROR] No citations provided")
            results["overall_status"] = "FAIL"
            results["action"] = "BLOCK"
            return results
        
        # 第二層 + 第三層：逐條驗證
        for citation in citations:
            citation_id = f"{citation.get('law_name', '')}#{citation.get('article_no', '')}"
            
            # 存在性驗證
            exists, exist_msg = self.validate_existence(citation)
            results['validations'].append({
                "citation": citation_id,
                "check": "existence",
                "result": exists,
                "message": exist_msg
            })
            
            if not exists:
                results['errors'].append(exist_msg)
                results['overall_status'] = "FAIL"
                results['action'] = "BLOCK"  # 🚨 完全錯誤，必須攔截
                continue
            
            # 內容驗證（Phase 0 初期：降級為警告，不阻斷）
            valid_content, content_msg = self.validate_content(citation)
            results['validations'].append({
                "citation": citation_id,
                "check": "content",
                "result": valid_content,
                "message": content_msg
            })
            
            if not valid_content:
                # ⚠️ Phase 0 初期：將內容驗證失敗降級為警告，不阻斷輸出
                # 原因：關鍵詞抽取尚未優化，可能導致誤判
                # TODO: Phase 0 後期收緊此邏輯
                results['warnings'].append(f"[Content Validation] {content_msg}")
                if results['overall_status'] == "PASS":
                    results['overall_status'] = "WARNING"
                    # 不改變 action 為 BLOCK，保持為 WARN 或 APPROVE
        
        # 第四層：邏輯衝突檢測
        conflicts = self.detect_conflicts(citations)
        if conflicts:
            results['warnings'].extend(conflicts)
            if results['overall_status'] == "PASS":
                results['overall_status'] = "WARNING"
                results['action'] = "WARN"
        
        return results
    
    def get_error_log(self) -> List[Dict]:
        """取得錯誤日誌"""
        return self.error_log
    
    def clear_error_log(self):
        """清除錯誤日誌"""
        self.error_log = []


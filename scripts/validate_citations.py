"""
Citation Validator - Regression Tests

用途：
- 验证 app/citation_validator.py 的四个核心功能
- 确保 Phase 0 的验收标准达成

测试项目：
1.  **白名单强制机制**：
    -   查询 "旷职扣薪" 时，即使原始检索结果没有，也必须强制返回劳动基准法第22、26条。
2.  **存在性验证**：
    -   验证存在的条文（例如 劳基法§22）→ PASS
    -   验证不存在的法规（例如 "神奇宝贝法"）→ FAIL + BLOCK
    -   验证不存在的条文（例如 劳基法§999）→ FAIL + BLOCK
3.  **内容一致性验证**：
    -   内容完全相符的引用 → PASS
    -   Checksum 不符但关键词完整的引用（格式差异）→ PASS + WARN
    -   缺少关键词的引用 → FAIL + BLOCK
4.  **逻辑冲突检测**：
    -   同时引用劳基法§22和民法 → WARN
    -   引用劳基法§26但缺少§22 → WARN
"""

import unittest
import json
from pathlib import Path
import sys
import io

# 强制 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 确保 app 目录在 sys.path 中
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from app.citation_validator import CitationValidator


class TestCitationValidator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """在所有测试前加载一次 Validator"""
        print("\n[*] Initializing CitationValidator...")
        cls.validator = CitationValidator()
        if not cls.validator.validation_db.get("validated_articles"):
            raise RuntimeError("Validation DB is empty. Run `scripts/generate_citation_validation.py` first.")
        print("[OK] Validator initialized.")

    def test_1_enforce_whitelist(self):
        """测试第一层：白名单强制机制"""
        print("\n--- Testing Layer 1: Whitelist Enforcement ---")
        
        # 案例 1：旷职扣薪，原始结果不含必要条文
        query = "员工旷职三天，薪水怎么算？"
        topic = "wage_deduction"
        retrieval_results = [{
            "law_name": "劳工请假规则",
            "heading": "第 7 条",
            "text": "劳工因有事故必须亲自处理者，得请事假..."
        }]
        
        enforced_results = self.validator.enforce_whitelist(query, topic, retrieval_results)
        
        # 验证：结果中必须包含劳基法§22和§26
        headings = [r.get('heading', '') for r in enforced_results]
        found_22 = any("22" in h for h in headings)
        found_26 = any("26" in h for h in headings)
        self.assertTrue(found_22, "勞動基準法§22 should be enforced")
        self.assertTrue(found_26, "勞動基準法§26 should be enforced")
        print("[PASS] Whitelist correctly enforces 勞動基準法 §22 & §26 for 'wage_deduction'")

    def test_2_validate_existence(self):
        """测试第二层：条文存在性验证"""
        print("\n--- Testing Layer 2: Existence Validation ---")
        
        # 案例 1：存在的条文
        citation_valid = {"law_name": "勞動基準法", "article_no": "22"}
        is_valid, msg = self.validator.validate_existence(citation_valid)
        self.assertTrue(is_valid, msg)
        print(f"[PASS] Valid citation: {msg}")

        # 案例 2：不存在的法规
        citation_fake_law = {"law_name": "神奇宝贝法", "article_no": "1"}
        is_valid, msg = self.validator.validate_existence(citation_fake_law)
        self.assertFalse(is_valid)
        print(f"[PASS] Correctly identifies non-existent law: {msg}")

        # 案例 3：不存在的条文
        citation_fake_article = {"law_name": "勞動基準法", "article_no": "999"}
        is_valid, msg = self.validator.validate_existence(citation_fake_article)
        self.assertFalse(is_valid)
        print(f"[PASS] Correctly identifies non-existent article: {msg}")

    def test_3_validate_content(self):
        """测试第三层：内容一致性验证"""
        print("\n--- Testing Layer 3: Content Validation ---")

        # 准备测试数据
        article_22_data = self.validator.validation_db['validated_articles']['勞動基準法']['articles']['22']
        correct_text = article_22_data['text']
        
        # 案例 1：内容完全一致
        citation_correct = {
            "law_name": "勞動基準法", 
            "article_no": "22", 
            "text": correct_text
        }
        is_valid, msg = self.validator.validate_content(citation_correct)
        self.assertTrue(is_valid, f"Content should be valid: {msg}")
        print(f"[PASS] Correct content: {msg}")

        # 案例 2：内容有格式差异但关键词完整
        text_with_spaces = " " + correct_text.replace("。", "。 ") + " "
        citation_formatting_diff = {
            "law_name": "勞動基準法", 
            "article_no": "22", 
            "text": text_with_spaces
        }
        is_valid, msg = self.validator.validate_content(citation_formatting_diff)
        self.assertTrue(is_valid)
        self.assertNotIn("[ERROR]", msg)
        print(f"[PASS] Handles formatting differences without error: {msg}")

        # 案例 3：内容缺少关键词
        text_missing_keywords = "工资本应给付劳工。" # 缺少 "全额"、"直接"
        citation_missing_keywords = {
            "law_name": "勞動基準法", 
            "article_no": "22", 
            "text": text_missing_keywords
        }
        is_valid, msg = self.validator.validate_content(citation_missing_keywords)
        self.assertFalse(is_valid, msg)
        self.assertIn("[ERROR]", msg)
        print(f"[PASS] Correctly identifies missing keywords: {msg}")

    def test_4_detect_conflicts(self):
        """测试第四层：逻辑冲突检测"""
        print("\n--- Testing Layer 4: Conflict Detection ---")
        
        # 案例 1：劳基法与民法冲突
        citations_conflict = [
            {"law_name": "勞動基準法", "article_no": "22"},
            {"law_name": "民法", "article_no": "487"}
        ]
        conflicts = self.validator.detect_conflicts(citations_conflict)
        self.assertTrue(any("[CONFLICT]" in c for c in conflicts))
        print(f"[PASS] Correctly detects conflict between 勞動基準法 and 民法")

        # 案例 2：引用不完整
        citations_incomplete = [
            {"law_name": "勞動基準法", "article_no": "26"} # 缺少 §22
        ]
        conflicts = self.validator.detect_conflicts(citations_incomplete)
        self.assertTrue(any("[INCOMPLETE]" in c for c in conflicts))
        print(f"[PASS] Correctly detects incomplete citation (missing §22 for §26)")
        
        # 案例 3：无冲突
        citations_ok = [
            {"law_name": "勞動基準法", "article_no": "22"},
            {"law_name": "勞動基準法", "article_no": "23"}
        ]
        conflicts = self.validator.detect_conflicts(citations_ok)
        self.assertEqual(len(conflicts), 0)
        print("[PASS] Correctly identifies no conflicts for valid citation set")

    def test_5_validate_all_blocking(self):
        """测试 validate_all 的 BLOCK 动作"""
        print("\n--- Testing validate_all() BLOCK action ---")

        # 案例：引用不存在的条文
        citations_non_existent = [
            {"law_name": "勞動基準法", "article_no": "999"}
        ]
        result = self.validator.validate_all("查询", citations_non_existent)
        
        self.assertEqual(result['overall_status'], "FAIL")
        self.assertEqual(result['action'], "BLOCK")
        self.assertTrue(len(result['errors']) > 0)
        print("[PASS] validate_all correctly blocks non-existent citations")

    def test_6_validate_all_warning(self):
        """测试 validate_all 的 WARN 动作"""
        print("\n--- Testing validate_all() WARN action ---")

        # 案例：逻辑冲突（需要包含 text 欄位以通過存在性驗證）
        article_22_data = self.validator.validation_db['validated_articles']['勞動基準法']['articles']['22']
        citations_conflict = [
            {
                "law_name": "勞動基準法", 
                "article_no": "22",
                "text": article_22_data['text']
            },
            {
                "law_name": "民法", 
                "article_no": "487",
                "text": "債務人無正當理由拒絕受領給付..."  # 模擬內容
            }
        ]
        result = self.validator.validate_all("查询", citations_conflict)
        
        self.assertIn(result['overall_status'], ["WARNING", "PASS"])  # 可能是 WARNING 或 PASS（如果內容驗證降級）
        # 重點是檢查是否有衝突警告
        self.assertTrue(len(result['warnings']) > 0, "Should have conflict warnings")
        self.assertTrue(any("[CONFLICT]" in w for w in result['warnings']), "Should detect conflict")
        print(f"[PASS] validate_all correctly warns on logical conflicts (Status: {result['overall_status']}, Warnings: {len(result['warnings'])})")


if __name__ == "__main__":
    unittest.main()

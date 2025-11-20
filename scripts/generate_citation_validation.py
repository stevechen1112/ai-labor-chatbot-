"""
生成引用驗證資料庫

用途：
- 掃描 data/laws/ 下所有法規檔案
- 逐條抽取條文（第 N 條、第 N 項）
- 計算 checksum（用於內容一致性驗證）
- 抽取關鍵詞（用於 fuzzy matching）
- 建立關聯（條文參照）
- 輸出 JSON 結構化資料：data/citation_validation.json

輸出格式：
{
    "validated_articles": {
        "勞動基準法": {
            "version": "2024-07-31",
            "last_verified": "2025-01-13",
            "articles": {
                "22": {
                    "heading": "第 22 條",
                    "full_title": "工資之給付",
                    "exists": true,
                    "checksum": "sha256_hash",
                    "key_phrases": ["全額直接給付", "法定通用貨幣"],
                    "related_articles": ["23", "26"]
                },
                ...
            }
        },
        ...
    },
    "validation_rules": {
        "must_match_checksum": true,
        "allow_version_tolerance_days": 30,
        "require_key_phrase_validation": true
    }
}
"""

import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional

ROOT = Path(__file__).resolve().parents[1]
LAWS_DIR = ROOT / "data" / "laws"
OUTPUT_PATH = ROOT / "data" / "citation_validation.json"


def normalize_text(text: str) -> str:
    """正規化文本：移除多餘空白、統一符號"""
    # 移除leading/trailing空白
    text = text.strip()
    # 移除多個連續空白
    text = re.sub(r'\s+', ' ', text)
    # 統一全形句號為半形
    text = text.replace('。', '。')
    return text


def calculate_checksum(text: str) -> str:
    """計算文本 SHA256 checksum"""
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def extract_articles(law_name: str, content: str) -> Dict[str, Dict]:
    """
    從法規內容逐條抽取條文
    返回格式：{
        "22": {
            "heading": "第 22 條",
            "full_title": "工資之給付",
            "text": "條文內容...",
            "items": {
                "1": "第 1 項內容...",
                "2": "第 2 項內容..."
            }
        },
        ...
    }
    """
    articles = {}
    
    # 正規表達式：匹配「第 N 條」或「第N條」
    # 模式：第[\s]*(數字或中文數字)[\s]*條
    article_pattern = r'第\s*([0-9０-９、–—-]+|[一二三四五六七八九十百千萬零]+(?:[之\.\-][一二三四五六七八九十百千萬零]+)*)\s*條'
    
    # 尋找所有條文標題位置
    matches = list(re.finditer(article_pattern, content))
    
    for idx, match in enumerate(matches):
        art_no_raw = match.group(1)
        # 統一轉換為阿拉伯數字
        art_no = _normalize_article_number(art_no_raw)
        heading = f"第 {art_no} 條"
        
        # 提取條文起始位置
        start = match.end()
        
        # 提取條文終止位置（下一條或檔案末尾）
        if idx + 1 < len(matches):
            end = matches[idx + 1].start()
        else:
            end = len(content)
        
        article_content = content[start:end].strip()
        
        # 將第一行（通常是標題）分離
        lines = article_content.split('\n')
        full_title = ""
        items_content = ""
        
        if lines:
            first_line = lines[0].strip()
            # 判斷第一行是否為條文標題（不含「第」字且短於 50 字）
            if not first_line.startswith('第') and len(first_line) < 50 and first_line and first_line[0].isupper():
                full_title = first_line
                items_content = '\n'.join(lines[1:]).strip()
            else:
                items_content = article_content
        
        # 解析項次
        items = _parse_items(items_content)
        
        articles[str(art_no)] = {
            "heading": heading,
            "full_title": full_title or f"第 {art_no} 條",
            "text": items_content,
            "items": items,
        }
    
    return articles


def _normalize_article_number(raw: str) -> str:
    """將各種形式的條號轉換為數字"""
    # 移除空白
    raw = raw.replace(' ', '').replace('　', '')
    
    # 處理「之」分支（如「22之1」） → 返回主號-分支
    if '之' in raw:
        parts = raw.split('之')
        main = _chinese_to_arabic(parts[0])
        sub = _chinese_to_arabic(parts[1])
        return f"{main}-{sub}"
    
    # 處理連字符格式（如「38-1」） → 檢查是否為編號格式
    if '–' in raw or '—' in raw or '-' in raw:
        parts = re.split(r'[–—-]', raw)
        # 如果第二部分是單個數字（且不是範圍結束），視為編號
        if len(parts) == 2:
            try:
                main = _chinese_to_arabic(parts[0])
                sub = _chinese_to_arabic(parts[1])
                # 如果兩個都是有效數字，檢查是否為編號格式
                # 編號格式：第二個數字通常較小（<10）
                # 範圍格式：第二個數字通常較大且接近第一個
                if sub < 10 or sub < main:
                    return f"{main}-{sub}"
                else:
                    # 範圍格式，只返回起始號
                    return str(main)
            except:
                # 轉換失敗，只返回第一部分
                return str(_chinese_to_arabic(parts[0]))
    
    return str(_chinese_to_arabic(raw))


def _chinese_to_arabic(chinese: str) -> int:
    """將中文數字轉換為阿拉伯數字"""
    try:
        # 快速路徑：已經是數字
        return int(chinese)
    except ValueError:
        pass
    
    # 中文數字對應
    mapping = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '百': 100, '千': 1000, '萬': 10000
    }
    
    result = 0
    temp = 0
    for char in chinese:
        if char not in mapping:
            continue
        val = mapping[char]
        if val >= 10:
            temp = (temp or 1) * val
            if val == 10000:
                result += temp
                temp = 0
        else:
            temp = temp * 10 + val if char != '零' else temp
    
    result += temp
    return result or 1


def _parse_items(content: str) -> Dict[str, str]:
    """解析項次內容"""
    items = {}
    
    # 匹配「第 N 項」或「第N項」
    item_pattern = r'第\s*([一二三四五六七八九十百千萬零0-9]+)\s*項'
    
    matches = list(re.finditer(item_pattern, content))
    
    if not matches:
        # 沒有項次標記，視整個內容為第 1 項
        items["1"] = content
        return items
    
    for idx, match in enumerate(matches):
        item_no = match.group(1)
        item_no = str(_chinese_to_arabic(item_no))
        
        start = match.end()
        if idx + 1 < len(matches):
            end = matches[idx + 1].start()
        else:
            end = len(content)
        
        items[item_no] = content[start:end].strip()
    
    return items


def extract_key_phrases(article_text: str, article_no: str) -> List[str]:
    """從條文抽取關鍵詞（用於 fuzzy matching）"""
    phrases = set()
    
    # 截取前 200 字
    text = article_text[:200]
    
    # 抽取常見詞彙（簡單啟發式）
    keywords = {
        # 工資相關
        '全額直接給付': ['全額', '直接給付', '給付'],
        '法定通用貨幣': ['法定通用貨幣'],
        '不得預扣': ['預扣', '違約金', '賠償'],
        
        # 工時相關
        '延長工時': ['延長工時', '加班'],
        '四小時': ['4小時', '四小時'],
        
        # 休假相關
        '特別休假': ['特別休假', '特休', '年資'],
        
        # 其他
        '曠工': ['曠工', '曠職', '無正當理由'],
    }
    
    for phrase, terms in keywords.items():
        for term in terms:
            if term in text:
                phrases.add(term)
                break
    
    # 若沒有找到任何關鍵詞，用第一句話作為後備
    if not phrases:
        first_sentence = re.split(r'[。！？]', text)[0].strip()
        if first_sentence and len(first_sentence) > 5:
            phrases.add(first_sentence[:30])  # 最多 30 字
    
    return list(phrases)


def find_related_articles(law_name: str, article_no: str, content: str, all_articles: Dict[str, Dict]) -> List[str]:
    """尋找與該條文相關的其他條文"""
    related = []
    
    # 尋找內容中的「第 N 條」參照
    ref_pattern = r'第\s*([0-9]+(?:[之\-][0-9]+)?)\s*條'
    matches = re.findall(ref_pattern, content)
    
    for match in matches:
        ref_no = str(_normalize_article_number(match))
        if ref_no in all_articles and ref_no != article_no:
            related.append(ref_no)
    
    return list(set(related))[:5]  # 最多 5 個


def process_law_file(file_path: Path) -> Tuple[str, Dict]:
    """處理單個法規檔案"""
    law_name = file_path.stem  # 檔名不含副檔名
    
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"❌ 無法讀取 {law_name}: {e}")
        return law_name, {}
    
    articles = extract_articles(law_name, content)
    
    # 補充 checksum、關鍵詞、關聯
    for art_no, article in articles.items():
        article["checksum"] = calculate_checksum(article["text"])
        article["key_phrases"] = extract_key_phrases(article["text"], art_no)
        article["related_articles"] = find_related_articles(law_name, art_no, article["text"], articles)
        article["exists"] = True
        
        # 移除暫時欄位
        article.pop("items", None)
    
    return law_name, articles


def generate_validation_db():
    """主函數：生成引用驗證資料庫"""
    import sys
    import io
    # 強制 UTF-8 輸出
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("[*] Scanning law files...")
    
    if not LAWS_DIR.exists():
        print(f"[ERROR] Directory not found: {LAWS_DIR}")
        return
    
    law_files = sorted(LAWS_DIR.glob("*.md"))
    print(f"[OK] Found {len(law_files)} law files")
    
    validated_articles = {}
    total_articles = 0
    
    for idx, law_file in enumerate(law_files, 1):
        law_name, articles = process_law_file(law_file)
        validated_articles[law_name] = {
            "version": datetime.now().strftime("%Y-%m-%d"),
            "last_verified": datetime.now().strftime("%Y-%m-%d"),
            "articles": articles
        }
        
        total_articles += len(articles)
        print(f"  [{idx:2d}/{len(law_files)}] OK - {law_name}: {len(articles)} articles")
    
    # 建立輸出結構
    output = {
        "validated_articles": validated_articles,
        "validation_rules": {
            "must_match_checksum": True,
            "allow_version_tolerance_days": 30,
            "require_key_phrase_validation": True
        },
        "metadata": {
            "total_laws": len(law_files),
            "total_articles": total_articles,
            "generated_at": datetime.now().isoformat(),
            "version": "1.0"
        }
    }
    
    # 寫入檔案
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n[COMPLETE]")
    print(f"[OUTPUT] {OUTPUT_PATH}")
    print(f"[STATS] {len(law_files)} laws, {total_articles} articles")
    print(f"[SIZE] {OUTPUT_PATH.stat().st_size / (1024*1024):.2f} MB")


if __name__ == "__main__":
    generate_validation_db()


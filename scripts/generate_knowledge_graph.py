"""
自動生成知識圖譜

從以下數據源建立：
1. citation_validation.json - 條文內容與關聯
2. law_guides.yaml - 主題與核心條文
3. 法律專家定義的預定義情境
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

import json
import yaml
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[1]

def load_citation_validation():
    """載入引用驗證資料庫"""
    path = ROOT / "data" / "citation_validation.json"
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_law_guides():
    """載入主題映射"""
    path = ROOT / "data" / "law_guides.yaml"
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def normalize_article_id(law_name: str, article_no: str) -> str:
    """標準化條文ID"""
    return f"{law_name}第{article_no}條"

def extract_entities(validation_db: Dict, law_guides: Dict) -> Dict:
    """提取實體（條文）"""
    entities = {}
    
    # 從 validation_db 提取
    validated_articles = validation_db.get("validated_articles", {})
    for law_name, law_data in validated_articles.items():
        articles = law_data.get("articles", {})
        for article_no, article_data in articles.items():
            entity_id = normalize_article_id(law_name, article_no)
            
            # 提取關鍵詞
            keywords = article_data.get("key_phrases", [])[:5]  # 最多5個
            
            # 從主題映射中找適用主題
            applies_to = []
            for topic_id, topic in law_guides.get("topics", {}).items():
                core_articles = topic.get("core_articles", [])
                for ca in core_articles:
                    if ca.get("law") == law_name and str(article_no) in [str(a) for a in ca.get("articles", [])]:
                        applies_to.append(topic.get("name"))
            
            entities[entity_id] = {
                "type": "條文",
                "law": law_name,
                "article": article_no,
                "title": article_data.get("heading", ""),
                "topics": applies_to,
                "keywords": keywords,
                "applies_to": applies_to
            }
    
    print(f"✅ 提取 {len(entities)} 個條文實體")
    return entities

def extract_relations(validation_db: Dict, entities: Dict) -> List[Dict]:
    """提取關聯"""
    relations = []
    relation_set = set()  # 避免重複
    
    validated_articles = validation_db.get("validated_articles", {})
    
    # 1. 從 related_articles 提取參照關係
    for law_name, law_data in validated_articles.items():
        articles = law_data.get("articles", {})
        for article_no, article_data in articles.items():
            from_id = normalize_article_id(law_name, article_no)
            
            related = article_data.get("related_articles", [])
            for rel_article in related:
                to_id = normalize_article_id(law_name, rel_article)
                
                if to_id in entities and from_id != to_id:
                    rel_key = (from_id, to_id, "參照")
                    if rel_key not in relation_set:
                        relation_set.add(rel_key)
                        relations.append({
                            "from": from_id,
                            "to": to_id,
                            "type": "參照",
                            "description": f"{from_id}參照{to_id}"
                        })
    
    # 2. 同一法規的相鄰條文關聯（章節關係）
    for law_name, law_data in validated_articles.items():
        articles = law_data.get("articles", {})
        article_numbers = sorted(
            articles.keys(),
            key=lambda x: (int(x.split('-')[0]) if '-' in x else int(x)) if x.isdigit() or '-' in x else 999999
        )
        
        for i, article_no in enumerate(article_numbers):
            if i > 0:  # 與前一條建立「順序關係」
                from_id = normalize_article_id(law_name, article_numbers[i-1])
                to_id = normalize_article_id(law_name, article_no)
                rel_key = (from_id, to_id, "順序相鄰")
                if rel_key not in relation_set and from_id in entities and to_id in entities:
                    relation_set.add(rel_key)
                    relations.append({
                        "from": from_id,
                        "to": to_id,
                        "type": "順序相鄰",
                        "description": f"{from_id}與{to_id}為相鄰條文"
                    })
    
    # 添加邏輯關聯（基於專家知識）
    expert_relations = [
        {
            "from": "勞動基準法第22條",
            "to": "勞動基準法第26條",
            "type": "補充說明",
            "description": "第22條規定全額給付原則，第26條禁止預扣，形成雙重保障"
        },
        {
            "from": "勞動基準法第12條",
            "to": "勞動基準法第22條",
            "type": "相關但不互斥",
            "description": "曠職嚴重可依第12條解僱，但解僱前的工資仍應依第22條全額給付"
        },
        {
            "from": "勞動基準法第24條",
            "to": "勞動基準法第32條",
            "type": "配套適用",
            "description": "第24條規定加班費，第32條規定延長工時上限，兩者配套適用"
        },
        {
            "from": "勞動基準法第38條",
            "to": "勞動基準法施行細則第24條",
            "type": "細則補充",
            "description": "施行細則第24條補充第38條特休的具體計算方式"
        },
        {
            "from": "性別工作平等法第15條",
            "to": "性別工作平等法第16條",
            "type": "連續適用",
            "description": "產假（第15條）與育嬰留職停薪（第16條）可連續使用"
        },
        {
            "from": "勞動基準法第59條",
            "to": "勞工職業災害保險及保護法第18條",
            "type": "優先適用",
            "description": "職災補償優先適用勞職保法，雇主責任補充適用勞基法第59條"
        }
    ]
    
    for rel in expert_relations:
        if rel["from"] in entities and rel["to"] in entities:
            relations.append(rel)
    
    print(f"✅ 提取 {len(relations)} 個關聯")
    return relations

def create_scenarios(law_guides: Dict) -> Dict:
    """建立預定義情境"""
    scenarios = {}
    
    # 基於主題映射建立情境
    scenario_mapping = {
        "wage_deduction": {
            "name": "曠職扣薪",
            "description": "勞工曠職時，雇主如何合法扣除工資",
            "required_articles": [
                "勞動基準法第22條",
                "勞動基準法第26條",
                "勞動基準法第12條"
            ],
            "reasoning": "曠職日可扣薪（未提供勞務），但不得擴大扣除其他出勤日工資（第22/26條）。嚴重曠職可依第12條解僱。",
            "common_errors": [
                "誤以為可扣除全勤獎金（需看獎金性質）",
                "擴大扣除其他日工資（違反第26條）",
                "未依法定程序直接扣款"
            ]
        },
        "overtime": {
            "name": "加班費計算",
            "description": "延長工作時間的工資如何計算",
            "required_articles": [
                "勞動基準法第24條",
                "勞動基準法第32條",
                "勞動基準法第32-1條"
            ],
            "reasoning": "第24條明定加班費率（平日1.34倍、休息日前2小時1.34倍後1.67倍），第32條規範延長工時上限。",
            "common_errors": [
                "休息日加班費計算錯誤",
                "未依法給予補休或加班費選擇權",
                "超過法定延長工時上限"
            ]
        },
        "annual_leave": {
            "name": "特休天數",
            "description": "勞工依年資享有的特別休假天數",
            "required_articles": [
                "勞動基準法第38條",
                "勞動基準法施行細則第24條",
                "勞動基準法施行細則第24-1條"
            ],
            "reasoning": "第38條明定各年資特休天數，施行細則第24/24-1條規範特休排定與未休工資計算。",
            "common_errors": [
                "年資計算錯誤",
                "未休特休未依法給付工資",
                "限制勞工特休使用"
            ]
        },
        "tardiness": {
            "name": "遲到扣款",
            "description": "勞工遲到時的工資扣除規範",
            "required_articles": [
                "勞動基準法第22條",
                "勞動基準法第26條"
            ],
            "reasoning": "遲到可扣除該時段工資（不提供勞務不給薪），但不得擴大扣除或作為懲罰性扣款（第26條）。",
            "common_errors": [
                "懲罰性扣款（如遲到1分鐘扣1小時）",
                "扣除全勤獎金未符合法定規範"
            ]
        },
        "maternity_leave": {
            "name": "產假規定",
            "description": "女工分娩前後的假期與工資",
            "required_articles": [
                "性別工作平等法第15條",
                "勞動基準法第50條"
            ],
            "reasoning": "性平法第15條規範產假8週（可彈性分配），工資照給。勞基法第50條為基礎規範。",
            "common_errors": [
                "產假期間未給付工資",
                "強制要求一次請完8週",
                "產檢假未依法給予"
            ]
        },
        "parental_leave": {
            "name": "育嬰留職停薪",
            "description": "育嬰留職停薪的申請資格與津貼",
            "required_articles": [
                "性別工作平等法第16條",
                "性別工作平等法第17條",
                "就業保險法第19-1條"
            ],
            "reasoning": "性平法第16/17條規範育嬰假申請，就保法第19-1條規範育嬰津貼（投保薪資60%）。",
            "common_errors": [
                "拒絕勞工育嬰留停申請",
                "育嬰期間要求離職",
                "復職後未給予原職或相當職位"
            ]
        },
        "severance_pay": {
            "name": "資遣費計算",
            "description": "資遣費的計算方式與給付",
            "required_articles": [
                "勞動基準法第11條",
                "勞動基準法第17條",
                "勞工退休金條例第12條"
            ],
            "reasoning": "第11條明定資遣事由，第17條與退條第12條分別規範舊制與新制資遣費計算。",
            "common_errors": [
                "資遣事由不符法定",
                "資遣費計算錯誤",
                "未依法預告或給付預告期工資"
            ]
        },
        "occupational_injury": {
            "name": "職業災害補償",
            "description": "職災勞工的醫療與補償",
            "required_articles": [
                "勞工職業災害保險及保護法第18條",
                "勞工職業災害保險及保護法第63條",
                "勞動基準法第59條"
            ],
            "reasoning": "勞職保法第18/63條規範職災保險給付，勞基法第59條規範雇主補償責任。",
            "common_errors": [
                "職災期間未給付原領工資",
                "職災勞工無法勝任原工作未安置適當工作",
                "未依法給付補償"
            ]
        },
        "salary_delay": {
            "name": "延遲發薪",
            "description": "工資延遲給付的法律責任",
            "required_articles": [
                "勞動基準法第21條",
                "勞動基準法第79條"
            ],
            "reasoning": "第21條規範工資定期給付，第79條明定違法罰則（2-100萬元罰鍰）。",
            "common_errors": [
                "以各種理由拖延發薪",
                "未依約定日期給付",
                "強制延後發薪日"
            ]
        },
        "probation_period": {
            "name": "試用期規範",
            "description": "試用期間的勞動權益",
            "required_articles": [
                "勞動基準法第11條",
                "勞動基準法第15條"
            ],
            "reasoning": "試用期間仍受勞基法保障，終止契約需適用第11/15條，不得任意解僱。",
            "common_errors": [
                "試用期薪資低於基本工資",
                "試用期間任意解僱",
                "試用期未提供勞健保"
            ]
        }
    }
    
    for topic_id, scenario_template in scenario_mapping.items():
        if topic_id in law_guides.get("topics", {}):
            scenarios[topic_id] = scenario_template
    
    print(f"✅ 建立 {len(scenarios)} 個預定義情境")
    return scenarios

def generate_knowledge_graph():
    """主函數：生成知識圖譜"""
    print("🚀 開始生成知識圖譜...")
    print("=" * 60)
    
    # 載入數據
    print("\n[步驟 1] 載入數據源...")
    validation_db = load_citation_validation()
    law_guides = load_law_guides()
    print(f"  - 載入 {len(validation_db)} 部法規")
    print(f"  - 載入 {len(law_guides.get('topics', {}))} 個主題")
    
    # 提取實體
    print("\n[步驟 2] 提取條文實體...")
    entities = extract_entities(validation_db, law_guides)
    
    # 提取關聯
    print("\n[步驟 3] 提取條文關聯...")
    relations = extract_relations(validation_db, entities)
    
    # 建立情境
    print("\n[步驟 4] 建立預定義情境...")
    scenarios = create_scenarios(law_guides)
    
    # 組裝知識圖譜
    kg = {
        "metadata": {
            "version": "1.0.0",
            "created_at": "2025-11-14",
            "description": "台灣勞動法規知識圖譜",
            "entity_count": len(entities),
            "relation_count": len(relations),
            "scenario_count": len(scenarios)
        },
        "entities": entities,
        "relations": relations,
        "scenarios": scenarios
    }
    
    # 儲存
    output_path = ROOT / "data" / "knowledge_graph.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(kg, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"✅ 知識圖譜生成完成！")
    print(f"   路徑：{output_path}")
    print(f"   實體數：{len(entities)}")
    print(f"   關聯數：{len(relations)}")
    print(f"   情境數：{len(scenarios)}")
    print("=" * 60)

if __name__ == "__main__":
    generate_knowledge_graph()


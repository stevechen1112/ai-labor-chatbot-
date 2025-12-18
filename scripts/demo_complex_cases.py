
import json
import urllib.request
import time
import sys

def http_post_json(url: str, data: dict, timeout=120):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return 500, {"error": str(e)}

def run_demo():
    base_url = "http://127.0.0.1:8000/query/multi-agent"
    
    scenarios = [
        {
            "name": "職場性騷擾與雇主報復性調職 (Sexual Harassment & Retaliation)",
            "query": "我在公司遭受主管言語與肢體性騷擾，向公司人資申訴後，公司不僅沒有立即啟動調查，還以『破壞團隊氣氛』為由將我調職到偏遠倉庫。請問公司這樣的處理方式合法嗎？我可以依據什麼法條終止契約並要求資遣費？公司未盡性騷擾防治義務，我能否請求損害賠償？"
        },
        {
            "name": "變形工時濫用與國定假日挪移 (Abuse of Flexible Working Hours)",
            "query": "公司實施四週變形工時，但未經工會或勞資會議同意。排班表上經常連續工作 10 天才休 1 天，且將國定假日直接挪移到平日而不給加班費，也沒經過我同意。最近我因為拒絕配合這種排班被記大過。請問公司的排班合法嗎？我可以拒絕挪移國定假日嗎？被記大過是否構成違法處分？"
        },
        {
            "name": "高薪主管責任制與離職違約金 (Manager Responsibility System & Penalty)",
            "query": "我擔任科技公司的高階主管，月薪 15 萬，合約中約定為『責任制』，無加班費，且若未滿三年離職需支付 50 萬違約金。我工作一年後因為身體不堪負荷想離職，公司說我是責任制人員不適用勞基法工時規定，並要求我賠償違約金。請問高階主管就一定適用責任制嗎？離職違約金條款有效嗎？"
        }
    ]

    print("="*60)
    print("🚀 啟動 UniHR 風格複雜案例演示 (Demo Complex Cases)")
    print("="*60)

    for i, scenario in enumerate(scenarios):
        print(f"\n[案例 {i+1}] {scenario['name']}")
        print(f"❓ 問題：{scenario['query']}")
        print("-" * 30)
        
        start_time = time.time()
        status, resp = http_post_json(base_url, {"query": scenario["query"]})
        elapsed = time.time() - start_time
        
        if status == 200:
            print(f"✅ 回覆生成成功 (耗時: {elapsed:.2f}s)")
            print("📝 系統回覆內容：")
            print("-" * 20)
            print(resp.get("answer", ""))
            print("-" * 20)
            
            # 顯示引用與建議
            metadata = resp.get("metadata", {})
            print(f"🏷️  識別主題: {', '.join(metadata.get('topics', []))}")
            print(f"💡 後續建議:")
            for sug in resp.get("suggestions", []):
                print(f"  - {sug}")
        else:
            print(f"❌ 請求失敗 (Status: {status})")
            print(f"錯誤訊息: {resp.get('error')}")
        
        print("\n" + "="*60)

if __name__ == "__main__":
    run_demo()

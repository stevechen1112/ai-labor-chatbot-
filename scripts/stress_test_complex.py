
import json
import urllib.request
import time

def http_post_json(url: str, data: dict, timeout=120):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return 500, {"error": str(e)}

def run_stress_test():
    base_url = "http://127.0.0.1:8000/query/multi-agent"
    
    scenarios = [
        {
            "name": "職災醫療期間遇公司倒閉 (Occupational Accident + Liquidation)",
            "query": "我是一名在職勞工，上個月在工廠發生職業災害，目前還在醫療期間。但公司昨天突然宣佈因為經營不善要聲請破產並解散，老闆說要資遣所有人。請問在職災醫療期間，公司可以資遣我嗎？如果公司真的倒閉了，我的職災補償和資遣費該向誰領？有沒有優先受償權？"
        },
        {
            "name": "假承攬真僱傭之權利主張 (Disguised Contract + Overtime)",
            "query": "我被一家外送平台聘為『承攬人員』，但公司要求我每天固定 9 點打卡、穿制服、聽從主管指揮，且不能拒絕派單。我每天工作 12 小時，沒有加班費，也沒有特休。最近我因為過勞住院，公司說我是承攬，不適用勞基法。請問我該如何主張我的權利？我可以要求補發過去兩年的加班費和特休工資嗎？"
        },
        {
            "name": "跨公司調動與新舊制退休金銜接 (Transferred Seniority + Retirement)",
            "query": "我在 A 公司工作了 10 年（從 1995 年開始），2005 年勞退新制施行時我選擇了新制。2010 年公司將我調動到關係企業 B 公司，當時說年資會銜接。現在 2025 年我要退休了，請問我的退休金該怎麼計算？A 公司的舊制年資（10年）還算數嗎？B 公司需要支付我舊制的退休金嗎？還是全部由新制個人帳戶支付？"
        },
        {
            "name": "大量解僱與留職停薪混合情境 (Mass Layoff + Furlough)",
            "query": "公司宣布因訂單驟減要在兩個月內大量解僱 120 人，並對尚未被資遣的員工要求改成留職停薪六個月。公司未與工會協商，也未提報主管機關審查。請問這樣的程序是否合法？被迫留職停薪的員工能否拒絕並主張資遣？解僱通知、資遣費與失業給付要怎麼計算？"
        },
        {
            "name": "資遣與競業禁止衝突 (Severance vs. Non-compete)",
            "query": "我任職的科技公司以業務緊縮為由資遣我，並要求我在離職後兩年內不得到同業工作，否則要賠償違約金 200 萬元。公司未提供任何競業補償，也未說明競業範圍。請問這樣的競業條款有效嗎？我能否拒絕簽署並仍然領取資遣費？"
        }
    ]

    print("="*50)
    print("🚀 開始執行高難度複雜場景壓力測試 (Multi-Agent)")
    print("="*50)

    for i, scenario in enumerate(scenarios):
        print(f"\n[測試案例 {i+1}] {scenario['name']}")
        print(f"問題：{scenario['query'][:100]}...")
        
        start_time = time.time()
        status, resp = http_post_json(base_url, {"query": scenario["query"]})
        elapsed = time.time() - start_time
        
        if status == 200:
            print(f"✅ 測試成功 (耗時: {elapsed:.2f}s)")
            print("-" * 30)
            print("【AI 律師回答摘要】")
            answer = resp.get("answer", "")
            print(answer[:500] + "..." if len(answer) > 500 else answer)
            print("-" * 30)
            print("【引用法規】")
            metadata = resp.get("metadata", {})
            topics = metadata.get("topics", [])
            print(f"識別主題: {', '.join(topics)}")
            
            # 檢查是否有 process_log
            log = resp.get("process_log", [])
            if log:
                print("【處理過程日誌】")
                for entry in log:
                    step = entry.get("step")
                    result = entry.get("result", {})
                    if step == "receptionist":
                        print(f"  - 接待員分析: {result.get('reasoning')}")
                    elif "supervisor" in step:
                        print(f"  - 審核員決策: {result.get('decision')} (品質分數: {result.get('quality_score')})")
            
            print(f"\n【後續建議】")
            for sug in resp.get("suggestions", []):
                print(f"  * {sug}")
        else:
            print(f"❌ 測試失敗 (Status: {status})")
            print(f"錯誤訊息: {resp.get('error')}")
        
        print("\n" + "="*50)

if __name__ == "__main__":
    run_stress_test()

# 台灣勞資 AI Chatbot（MVP）

**專案目標**：提供雇主／資方在繁體中文環境下的對話式 AI 勞資顧問，協助快速理解台灣勞資法令並得到實務建議。

## 🎯 核心特色

- **零錯引保證**：多層檢索約束 + Citation Guard，回歸測試 68/79 通過（86.1%）、錯引率 0%
- **法規引用產品化**：段落對齊法條、雙索引（向量 + TF-IDF）、主題規則路由、白名單模式
- **自然對話風格**：採用 UniHR 成功模式，溫暖專業語調、段落式回答、零結構化標題
- **簡潔 UI**：純對話介面，無引用卡片干擾，法規引用自然嵌入回答內文
- **可追溯性**：每條引用附帶法規版本、修正日期、來源網址、checksum
- **營運監控**：SQLite 持久化、系統指標端點（請求量、延遲、引用數）、回饋機制

## 📊 當前狀態（2025/10/19）

- ✅ **M8+ 完成**：UniHR 風格對話優化 + UI 簡化 🎉
- 🤖 **對話體驗升級**：
  - 採用 UniHR 成功模式（system/user message 分離）
  - 溫暖專業語調，零 `**標題**` 結構化干擾
  - 問題分類（INFO/PROFESSIONAL）與動態 prompt
  - 法規引用自然嵌入內文：`（勞動基準法.md｜第24條）`
- 💾 **持久化儲存**：SQLite（6 表 + 9 索引），會話/回饋/指標全數持久化
- 📈 **回歸測試**：**68/79（86.1%）**、零錯引（測試規模從 27 題擴充至 79 題）
- 🗂️ **資料規模**：82 部法規、4,621 段落、HuggingFace E5-base 向量化
- ⚖️ **民法優化**：動態降權機制（-0.5 分），混淆矩陣驗證無民法誤引
- 🎨 **使用者介面**：http://127.0.0.1:8000/ （簡潔對話式，無引用卡片）

## 📁 目錄結構

```
ai-labor-chatbot/
├── app/                        # FastAPI 後端應用
│   ├── main.py                 # 主程式（API 端點、會話管理、指標追蹤）
│   ├── database.py             # SQLite 資料庫管理（持久化儲存）
│   ├── retrieval.py            # 混合檢索（向量+TF-IDF、白名單、Rerank）
│   ├── rules.py                # 主題規則路由（5 大主題）
│   ├── query_rewrite.py        # 查詢重寫（10+ 同義詞規則）
│   ├── query_classifier.py     # 問題分類（INFO/PROFESSIONAL）
│   ├── prompts.py              # UniHR 風格提示詞（system/user 分離）
│   ├── citations.py            # 引用裝飾與格式化
│   └── ...
├── scripts/                    # 工具腳本
│   ├── build_index.py          # 段落切分與 TF-IDF 索引
│   ├── build_vectors.py        # 向量索引建置（Chroma）
│   ├── regression_tests.py     # 回歸測試與報表
│   └── ...
├── data/
│   ├── laws/                   # 82 部勞動法規 Markdown
│   ├── index/                  # 索引檔案
│   │   ├── index.json          # TF-IDF 索引
│   │   ├── metadata.json       # 法規元數據
│   │   ├── chroma/             # 向量資料庫（Chroma 持久化）
│   │   ├── regression_report.json    # 回歸測試報告
│   │   └── regression_failures.json  # 失敗案例清單
│   ├── tests/
│   │   └── queries.json        # 固定問句集（79 題）
│   └── app.db                  # SQLite 資料庫（會話、回饋、指標）
├── static/                     # 前端靜態檔案
│   ├── index.html              # 聊天 UI（簡潔對話式）
│   └── ui.js                   # 前端邏輯（已移除引用卡片顯示）
├── 台灣勞資AIChatbot開發規劃.md   # 完整開發規劃（14 章節 + 里程碑）
├── README.md                   # 本檔案
├── requirements.txt            # Python 依賴
└── api key.txt                 # OpenAI API 金鑰（不提交版控）
```

快速開始（不需安裝任何套件）
1) 建索引
   - `python scripts/build_index.py`
   - 會讀取 `data/laws/*.md`，切分（優先依「第…條」）、斷詞（ASCII + CJK 單/雙字）、輸出 TF 與 DF 至 `data/index/index.json`

2) 檢索測試
   - `python scripts/search.py "加班費 計算"` 或 `python scripts/search.py "特休 工資" -k 10`
   - 以 TF‑IDF 餘弦相似度回傳前幾名段落，顯示檔名、章節標題與預覽

後續規劃（將逐步實作）
- FastAPI 後端：`/query`（檢索與可選 LLM 生成）、`/health` 已提供
- 網頁介面（`/` 與 `/static`）：輸入查詢、顯示答案與引用法條 已提供
- 讀取 `api key.txt` 以串接 OpenAI API（僅在伺服器端讀取，不寫入代碼）已實作

向量索引（選用）
1) 安裝依賴（已在 requirements.txt）：`pip install -r requirements.txt`
2) 先執行文字索引（用於分段與備用 TF‑IDF）：`python scripts/build_index.py`
3) 於根目錄放入 `api key.txt`（OpenAI 金鑰）
4) 產生向量索引（Chroma 持久化在 `data/index/chroma/`）：`python scripts/build_vectors.py`

啟動 API 與網頁介面
1) 安裝依賴：`pip install -r requirements.txt`
2) 確認已建索引：`python scripts/build_index.py`
3) 於根目錄放入 `api key.txt`（若要使用 LLM 生成）
4) 啟動服務：`python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
5) 瀏覽器開啟 `http://127.0.0.1:8000/` 使用介面；或使用 curl 測試：
   - `curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"query\":\"加班費如何計算\",\"top_k\":5,\"use_llm\":true}"`

查詢選項
- `use_vector`：預設為 true，若 `data/index/chroma/` 存在且已建立向量集合，則使用向量檢索；否則自動退回 TF‑IDF。
- `use_llm`：是否以 LLM 依據檢索段落生成答案；若未提供金鑰，會退回僅顯示引用段落。

OpenAI 連線設定
- 以環境變數覆蓋金鑰（優先）：`$env:OPENAI_API_KEY = '<你的 OpenAI key>'`
- 若使用自訂代理/相容端點（如企業代理）：`$env:OPENAI_BASE_URL = 'https://你的端點/v1'`
- 向量建置時亦可指定：`python scripts/build_vectors.py --backend openai --model text-embedding-3-small --rebuild --api-key <key> --base-url https://你的端點/v1`

向量品質檢核（建議每次重建後執行）
1) 先確保：`python scripts/build_index.py`（建立/更新段落）
2) 若已建向量索引：`python scripts/build_vectors.py --model text-embedding-3-small`
3) 執行評估（預設抽樣 200 篇，計算 Recall@K）：
   - `python scripts/eval_vectors.py --samples 200 --top_k 10`
   - 產生報表：`data/index/eval_report.json`，包含向量與 TF‑IDF 的 recall@1/3/5/10，比較結果與失敗案例，便於檢視查準率問題。

切換嵌入模型
- 建置向量索引時可指定：`python scripts/build_vectors.py --model text-embedding-3-large --rebuild`
- 重新評估：`python scripts/eval_vectors.py`

條文直查 API（新增）
- 直接查詢指定法規第 N 條：`GET /article?law=勞動基準法&no=32`
- 回傳：檔名、命中標題與條文全文段落；支援阿拉伯數字與中文數字（例如 32 或 三十二）

混合檢索（向量+TF‑IDF）
- `/query` 在向量庫可用時預設採用混合檢索，綜合兩種分數後回傳更穩定的前 K 段；若無向量庫則退回 TF‑IDF。
- 可選 Rerank：在請求體加入 `"use_rerank": true`，會用 CrossEncoder（預設 `BAAI/bge-reranker-base`）對候選做重排。

側車 Metadata 產生
- 產生每個檔案的標題與簡易 `law_id`：`python scripts/generate_metadata.py`
- 輸出位置：`data/index/metadata.json`（不修改原始 Markdown）

注意
- 檔名為 UTF‑8，若終端顯示亂碼為主機字碼頁問題，不影響索引與檢索。
- `data/index/` 為工具輸出，必要時可加入版控忽略。

查詢選項補充
- `use_rerank`：在查詢請求中加上此布林值可啟用交叉編碼器重排（預設模型 `BAAI/bge-reranker-base`）。

## 🎨 對話體驗特色

**UniHR 風格自然對話**
- 採用業界成功案例（UniHR）的 prompt 架構
- System prompt 與 user message 分離，避免結構化干擾
- 溫暖專業語調：「了解您的顧慮」、「我能理解這對您來說很重要」
- 零 `**標題**` 干擾，純段落式自然流暢回答
- 法規引用自然嵌入內文：`（勞動基準法.md｜第24條）`

**智能問題分類**
- INFO 類：直接資訊查詢（如「加班費如何計算？」）→ 簡潔專業（200-400字）
- PROFESSIONAL 類：複雜諮詢場景（如「員工遲到早退可以扣薪嗎？」）→ 完整建議（300-650字）
- 動態 prompt 調整，確保回答長度與風格適配問題類型

**簡潔 UI 設計**
- 純對話介面，無引用卡片、metadata 干擾
- 回答內容直接顯示，法規引用自然融入
- 對話流體驗，專注於用戶與 AI 的互動

## 🧪 測試與品質保證

**回歸測試**
```bash
# 執行完整回歸測試（需先啟動服務）
python scripts/regression_tests.py --out data/index/regression_report.json --fail-out data/index/regression_failures.json

# 當前結果：68/79 通過（86.1%）、零錯引
```

**健康檢查**
```bash
python scripts/health_check.py  # 檢查 /health 與 /article 端點
curl http://127.0.0.1:8000/metrics  # 查看系統指標
```

**向量品質評估**
```bash
python scripts/eval_vectors.py --samples 200 --top_k 10
# 產生報表：data/index/eval_report.json
```

## 🚀 下一步（M9 規劃中）

按優先順序：

1. **回答品質提升**：針對試用期、年終獎金等實務案例優化（目標 90% 通過率）
2. **對話體驗優化**：
   - 優化 query_classifier 準確率（目前 INFO/PROFESSIONAL 分類）
   - 針對不同主題微調 prompt（加班、特休、工資扣除等）
   - 加入對話歷史記憶（多輪對話）
3. **監控儀表板前端**：視覺化 /metrics（圖表、趨勢、請求日誌）
4. **登入系統占位**：Email OTP / OAuth 最小實作
5. **週期性報表**：自動產生品質報告（通過率、常見問題、錯誤類型）

詳細規劃請參考：[台灣勞資AIChatbot開發規劃.md](./台灣勞資AIChatbot開發規劃.md)

## 📝 最近更新（2025/10/19）

**M8+ UniHR 風格對話優化**
- ✅ 採用 UniHR 成功模式（system/user message 分離）
- ✅ 實作問題分類器（INFO/PROFESSIONAL）
- ✅ 創建 UniHR 風格提示詞（`app/prompts.py`）
- ✅ 移除所有自動添加的引用清單（後端 `app/main.py`）
- ✅ 簡化前端 UI，移除引用卡片與 metadata（`static/ui.js`）
- ✅ 驗證：回答自然流暢，零 `**標題**` 干擾，法規引用嵌入內文

**技術亮點**
- OpenAI `gpt-4o-mini` 模型，`temperature=0.7`
- Prompt 使用 `【格式絕對優先指令】` 標記強調格式要求
- User message 格式：`用戶問題 + 相關法規資訊 + 指引`
- 回答長度：INFO 200-400字，PROFESSIONAL 300-650字

## 📄 授權

本專案僅供學習研究使用。

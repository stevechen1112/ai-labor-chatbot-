# 🚀 AI Labor Chatbot 部署到 Linode 指南

## 📋 部署資訊

- **目標伺服器**: `172.233.77.254` (Linode)
- **SSH 登入**: `ssh root@172.233.77.254`
- **專案倉庫**: https://github.com/stevechen1112/ai-labor-chatbot-.git
- **部署端口**: 8000
- **域名**: (可選) 設定反向代理

---

## 🔧 步驟 1：連接到 Linode 伺服器

```bash
# 使用您提供的 SSH 命令
ssh root@172.233.77.254

# 或使用域名方式
ssh -t joyshot@lish-jp-osa.linode.com ubuntu-jp-osa
```

---

## 🛠️ 步驟 2：安裝系統依賴

```bash
# 更新系統
sudo apt update && sudo apt upgrade -y

# 安裝 Python 3.10+ 和必要工具
sudo apt install python3 python3-pip python3-venv git build-essential -y

# 安裝開發工具
sudo apt install curl wget unzip -y

# 檢查安裝
python3 --version
git --version
```

---

## 📥 步驟 3：下載專案

```bash
# 從 GitHub 複製專案
git clone https://github.com/stevechen1112/ai-labor-chatbot-.git
cd ai-labor-chatbot-

# 檢查檔案
ls -la
```

---

## 🔐 步驟 4：設定 API 金鑰

```bash
# 建立 API 金鑰檔案
nano "api key.txt"

# 貼上您的 OpenAI API Key：
openai
sk-proj-你的-openai-api-key-here

# 設定權限
chmod 600 "api key.txt"

# 驗證檔案存在
ls -la "api key.txt"
```

---

## 🐍 步驟 5：設定 Python 環境

```bash
# 建立虛擬環境
python3 -m venv venv
source venv/bin/activate

# 升級 pip
pip install --upgrade pip

# 安裝專案依賴
pip install -r requirements.txt

# 檢查安裝
python -c "import fastapi, chromadb, sentence_transformers; print('✅ 依賴安裝成功')"
```

---

## 🗂️ 步驟 6：初始化知識庫

```bash
# 建立知識庫索引 (需要一些時間)
python scripts/build_index.py

# 檢查索引是否建立成功
ls -la data/index/
ls -la data/index/chroma/
```

---

## 🚀 步驟 7：啟動服務

### 選項 A：直接執行（測試用）
```bash
# 在前景執行，便於觀察日誌
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 選項 B：背景執行（生產用）⭐⭐⭐⭐⭐
```bash
# 使用 nohup 在背景執行
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# 或使用 screen
sudo apt install screen -y
screen -S ai-labor
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# 按 Ctrl+A+D 離開 screen
```

### 選項 C：使用 Gunicorn（企業級）
```bash
# 安裝 Gunicorn
pip install gunicorn

# 啟動多進程服務
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --daemon
```

---

## 🛡️ 步驟 8：設定防火牆

```bash
# 檢查防火牆狀態
sudo ufw status

# 允許 SSH (22) 和 HTTP (8000)
sudo ufw allow 22
sudo ufw allow 8000

# 啟用防火牆
sudo ufw enable

# 確認規則
sudo ufw status
```

---

## 🌐 步驟 9：設定反向代理 (可選但推薦)

```bash
# 安裝 Nginx
sudo apt install nginx -y

# 建立配置
sudo nano /etc/nginx/sites-available/ai-labor-chatbot

# 貼上以下內容：
server {
    listen 80;
    server_name 172.233.77.254;  # 或您的域名

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支援（如果需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # 靜態檔案快取
    location /static/ {
        proxy_pass http://127.0.0.1:8000/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}

# 啟用網站
sudo ln -s /etc/nginx/sites-available/ai-labor-chatbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 🧪 步驟 10：測試部署

### 從本地測試
```bash
# 在您的本地電腦上測試
curl http://172.233.77.254:8000/health
curl http://172.233.77.254/health  # 如果設定了 Nginx
```

### 測試 API
```bash
# 測試健康檢查
curl http://172.233.77.254:8000/health

# 測試聊天功能
curl -X POST http://172.233.77.254:8000/query/multi-agent \
  -H "Content-Type: application/json" \
  -d '{"query": "試用期可以隨時解僱嗎？", "top_k": 5}'
```

### 測試 Web 介面
開啟瀏覽器訪問：
- `http://172.233.77.254:8000` (直接)
- `http://172.233.77.254` (如果設定了 Nginx)

---

## 📊 監控與維護

### 檢查服務狀態
```bash
# 檢查進程
ps aux | grep uvicorn

# 檢查端口
netstat -tlnp | grep 8000

# 查看日誌
tail -f nohup.out
```

### 重啟服務
```bash
# 停止舊服務
pkill -f uvicorn

# 重新啟動
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
```

### 更新程式碼
```bash
# 進入專案目錄
cd ai-labor-chatbot-

# 拉取最新程式碼
git pull origin master

# 重啟服務
pkill -f uvicorn
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
```

---

## 🔒 安全設定

### 1. 更改預設 SSH 端口
```bash
# 編輯 SSH 配置
sudo nano /etc/ssh/sshd_config

# 將 Port 22 改為其他端口，例如：
Port 2222

# 重啟 SSH
sudo systemctl restart ssh

# 更新防火牆
sudo ufw allow 2222
sudo ufw delete allow 22
```

### 2. 設定 SSH 金鑰登入
```bash
# 在本地產生 SSH 金鑰
ssh-keygen -t rsa -b 4096

# 複製公鑰到伺服器
ssh-copy-id root@172.233.77.254

# 停用密碼登入
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no

# 重啟 SSH
sudo systemctl restart ssh
```

---

## 🌟 部署完成後

### 您的 API 端點
```
基礎 URL: http://172.233.77.254:8000
健康檢查: GET /health
聊天 API: POST /query/multi-agent
會話管理: POST /session/new, GET /session/{id}
API 文檔: GET /docs
```

### 整合範例
```javascript
// 外部網站可以這樣呼叫您的 API
fetch('http://172.233.77.254:8000/query/multi-agent', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        query: "加班費怎麼計算？",
        top_k: 10
    })
})
.then(response => response.json())
.then(data => {
    console.log('AI 回答:', data.answer);
    console.log('信心度:', data.metadata.confidence);
});
```

---

## 📞 疑難排解

### 服務無法啟動
```bash
# 檢查錯誤日誌
python -c "import app.main; print('模組載入成功')"

# 檢查依賴
python -c "import fastapi, chromadb; print('依賴正常')"
```

### API 無法存取
```bash
# 檢查防火牆
sudo ufw status

# 檢查服務是否運行
ps aux | grep uvicorn

# 檢查端口
netstat -tlnp | grep 8000
```

### 記憶體不足
```bash
# 檢查記憶體使用
free -h

# 如果需要，增加交換空間
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 💰 成本估算

### Linode 費用
- **Nanode 1GB**: $5/月
- **Linode 2GB**: $10/月
- **Linode 4GB**: $20/月 (推薦)

### OpenAI API 費用
- 每月預估: $10-50 (視使用量)

### 總成本
- **最低**: $15/月
- **推薦**: $30/月

---

## 🎯 下一步

1. **測試所有功能**
2. **設定域名** (可選)
3. **申請 SSL 憑證** (推薦)
4. **設定監控告警**
5. **備份策略**

---

**恭喜！您的 AI Labor Chatbot 現在已經部署到雲端，可以被全世界存取了！** 🚀

有任何部署問題歡迎詢問！

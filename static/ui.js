(() => {
  const messagesContainer = document.getElementById('messages');
  const queryInput = document.getElementById('query');
  const sendBtn = document.getElementById('send');
  const newSessionBtn = document.getElementById('new-session');
  const feedbackBtn = document.getElementById('feedback');

  const topK = document.getElementById('top_k');
  const useLLM = document.getElementById('use_llm');
  const useRerank = document.getElementById('use_rerank');
  const wVec = document.getElementById('w_vec');
  const wLex = document.getElementById('w_lex');

  let sessionId = null;
  let messages = [];

  function init() {
    clearMessages();
    sendBtn.addEventListener('click', handleSend);
    queryInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
    queryInput.addEventListener('input', () => {
      queryInput.style.height = 'auto';
      queryInput.style.height = Math.min(queryInput.scrollHeight, 120) + 'px';
    });

    newSessionBtn.addEventListener('click', handleNewSession);
    feedbackBtn.addEventListener('click', handleFeedback);
  }

  async function handleSend() {
    const query = queryInput.value.trim();
    if (!query) return;
    await ensureSession();

    addMessage('user', query);
    queryInput.value = '';
    queryInput.style.height = 'auto';

    const loadingId = addMessage('bot', '', true);
    setButtonState(true);

    try {
      const resp = await fetch('/query/multi-agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          session_id: sessionId,  // 🆕 傳送 session_id 以支持對話記憶
          top_k: Number(topK.value),
          use_llm: useLLM.checked,
          use_rerank: useRerank.checked,
          w_vec: Number(wVec.value),
          w_lex: Number(wLex.value),
        })
      });

      const payload = await resp.json().catch(() => null);

      if (!resp.ok) {
        const detail = payload?.detail || payload || {};
        if (resp.status === 409 && detail.validation) {
          removeMessage(loadingId);
          addBotResponse({
            answer: detail.message || '引用驗證未通過，請補充情境或條號後再試一次。',
            citations: [],
            validation: detail.validation
          });
        } else {
          throw new Error(detail.message || `HTTP ${resp.status}`);
        }
        return;
      }

      if (!payload) throw new Error('無法解析伺服器回應');

      removeMessage(loadingId);
      addBotResponse(payload);
    } catch (err) {
      removeMessage(loadingId);
      addMessage('bot', `⚠️ 查詢失敗：${err.message}`);
    } finally {
      setButtonState(false);
    }
  }

  function addMessage(role, content, isLoading = false) {
    if (messages.length === 0 && messagesContainer.querySelector('.empty-state')) {
      messagesContainer.innerHTML = '';
    }

    const msgId = `msg-${Date.now()}-${Math.random()}`;
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    msgDiv.id = msgId;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? '用戶' : 'AI';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';

    if (isLoading) {
      contentDiv.innerHTML = '<div class="loading"><div class="loading-dot"></div><div class="loading-dot"></div><div class="loading-dot"></div></div>';
    } else {
      contentDiv.textContent = content;
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    messages.push({ id: msgId, role, content });
    return msgId;
  }

  function addBotResponse(data) {
    const msgId = `msg-${Date.now()}-${Math.random()}`;
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    msgDiv.id = msgId;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = 'AI';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'content';

    const answerBlock = document.createElement('div');
    answerBlock.className = 'bot-answer';
    answerBlock.innerHTML = formatAnswer(data.answer || '（本次查詢沒有可引用的答案）');
    contentDiv.appendChild(answerBlock);

    if (data.validation) {
      contentDiv.appendChild(createValidationBanner(data.validation));
    }

    if (Array.isArray(data.citations) && data.citations.length) {
      contentDiv.appendChild(renderCitations(data.citations));
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    messagesContainer.appendChild(msgDiv);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    messages.push({ id: msgId, role: 'bot', data });
  }

  function renderCitations(citations) {
    const wrapper = document.createElement('div');
    wrapper.className = 'citations';

    const header = document.createElement('div');
    header.className = 'citations-header';
    header.textContent = `引用來源 (${citations.length})`;
    wrapper.appendChild(header);

    citations.forEach((cite) => {
      const citeDiv = document.createElement('div');
      citeDiv.className = 'citation-item';

      const citeTitle = cite.citation || `${cite.title || cite.source_file || '未知來源'}｜${cite.heading || ''}`;
      const headerRow = document.createElement('div');
      headerRow.className = 'citation-header';

      const titleEl = document.createElement('strong');
      titleEl.textContent = citeTitle;
      headerRow.appendChild(titleEl);

      if (cite.validation_status) {
        const badge = document.createElement('span');
        badge.className = `validation-badge ${cite.validation_status}`;
        badge.textContent = cite.validation_status;
        headerRow.appendChild(badge);
      }

      citeDiv.appendChild(headerRow);

      const snippet = document.createElement('div');
      snippet.className = 'citation-meta';
      const text = cite.text || '';
      snippet.textContent = text ? `${text.substring(0, 160)}${text.length > 160 ? '…' : ''}` : '（無段落預覽）';
      citeDiv.appendChild(snippet);

      const actions = document.createElement('div');
      actions.className = 'citation-actions';

      const copyBtn = document.createElement('button');
      copyBtn.textContent = '複製引用';
      copyBtn.addEventListener('click', (evt) => copyCitation(citeTitle, evt.target));
      actions.appendChild(copyBtn);

      const reportBtn = document.createElement('button');
      reportBtn.className = 'report';
      reportBtn.textContent = '回報引用錯誤';
      reportBtn.addEventListener('click', () => promptCitationReport(cite));
      actions.appendChild(reportBtn);

      citeDiv.appendChild(actions);
      wrapper.appendChild(citeDiv);
    });

    return wrapper;
  }

  function createValidationBanner(validation) {
    const banner = document.createElement('div');
    const action = (validation.action || 'APPROVE').toLowerCase();
    banner.className = `validation-banner ${action === 'warn' ? 'warn' : 'approve'}`;

    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = `引用檢查：${(validation.action || 'APPROVE').toUpperCase()}`;
    banner.appendChild(title);

    const warningList = [...(validation.errors || []), ...(validation.warnings || [])];
    if (warningList.length) {
      const list = document.createElement('ul');
      list.className = 'validation-list';
      warningList.forEach((msg) => {
        const item = document.createElement('li');
        item.textContent = msg;
        list.appendChild(item);
      });
      banner.appendChild(list);
    }

    return banner;
  }

  function removeMessage(msgId) {
    const elem = document.getElementById(msgId);
    if (elem) elem.remove();
    messages = messages.filter(m => m.id !== msgId);
  }

  function clearMessages() {
    messages = [];
    messagesContainer.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💬</div>
        <h2>歡迎使用台灣勞資 AI Chatbot</h2>
        <p>輸入您的問題，我們會盡力提供對應的法規條文與建議。</p>
      </div>
    `;
  }

  async function handleNewSession() {
    if (messages.length > 0 && !confirm('確定要建立新會話？此動作會清除目前對話。')) {
      return;
    }
    clearMessages();
    sessionId = null;
    await ensureSession();
  }

  async function handleFeedback() {
    const feedback = prompt('請留下您對本服務的建議或覺得不正確的地方：');
    if (!feedback) return;

    try {
      await fetch('/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          feedback,
          timestamp: new Date().toISOString()
        })
      });
      alert('已收到您的建議，感謝協助！');
    } catch (e) {
      alert('送出失敗，請稍後再試。');
    }
  }

  function setButtonState(disabled) {
    sendBtn.disabled = disabled;
    sendBtn.textContent = disabled ? '查詢中…' : '送出';
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function escapeAttr(text) {
    return text.replace(/["'<>&]/g, c => ({
      '<': '&lt;',
      '>': '&gt;',
      '&': '&amp;',
      '"': '&quot;',
      "'": '&#39;'
    }[c] || c));
  }

  function formatAnswer(text) {
    return escapeHtml(text).replace(/\n/g, '<br>');
  }

  async function ensureSession() {
    if (sessionId) return;
    try {
      const resp = await fetch('/session/new', { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        sessionId = data.session_id;
      }
    } catch (err) {
      console.warn('Session creation failed:', err);
    }
  }

  async function promptCitationReport(cite) {
    const reason = prompt('請描述您觀察到的引用錯誤：');
    if (!reason) return;
    try {
      await sendCitationReport({
        citation_id: cite.id || `${cite.law_name || cite.title || 'citation'}#${cite.article_no || cite.heading || ''}`,
        session_id: sessionId,
        law_name: cite.law_name || cite.title || '',
        article_no: cite.article_no || '',
        error_reason: reason
      });
      alert('已提交引用錯誤，感謝協助。');
    } catch (err) {
      alert(`回報失敗：${err.message}`);
    }
  }

  async function sendCitationReport(payload) {
    const resp = await fetch('/api/citation/report-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      const detail = await resp.json().catch(() => null);
      throw new Error(detail?.detail || detail?.message || `HTTP ${resp.status}`);
    }
  }

  function copyCitation(text, button) {
    navigator.clipboard.writeText(text).then(() => {
      if (button) {
        const original = button.textContent;
        button.textContent = '已複製';
        setTimeout(() => { button.textContent = original; }, 1500);
      }
    }).catch(err => {
      alert('複製失敗：' + err);
    });
  }

  init();
  ensureSession();
})();

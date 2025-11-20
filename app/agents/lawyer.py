"""律師代理：專業答案生成"""
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel
from pathlib import Path
from openai import OpenAI

from .receptionist import AnalysisResult
from ..law_guides import LawGuideEngine


ROOT = Path(__file__).resolve().parents[2]
API_KEY_PATH = ROOT / "api key.txt"


class LawyerResponse(BaseModel):
    """律師生成的答案"""
    answer: str
    confidence: float  # 0-1
    used_citations: List[str]  # 使用的引用 ID
    uncertainties: List[str] = []  # 不確定的部分


class LawyerAgent:
    """
    律師代理：負責生成專業、準確的法律答案
    
    職責：
    1. 根據查詢類型選擇Prompt策略
    2. 組裝上下文
    3. 生成答案
    4. 自我檢查
    """
    
    def __init__(self):
        self.client = self._init_openai_client()
        self.model = "gpt-5-mini"
        try:
            self.law_guide_engine = LawGuideEngine()
        except Exception as exc:
            print(f"[Lawyer] Warning: failed to load law guides: {exc}")
            self.law_guide_engine = None
        
        # Prompt 策略模板
        self.prompt_strategies = {
            "INFO": {
                "temperature": 1.0,
                "max_output_tokens": 2048,
                "system_prompt": """你是一個台灣勞動法專家助手。請用清晰、簡潔的語言回答問題，避免過多法律術語。

重要規則：
1. 優先使用提供的法律條文資料作為依據
2. 如果條文已涵蓋問題的核心面向，請積極提供答案並引用條文
3. 只有在條文完全無關或嚴重不足時，才說明「資料不足」
4. 可以基於條文進行合理的法律推論，但必須標註「依條文推論」
5. 答案控制在200-300字"""
            },
            "PROFESSIONAL": {
                "temperature": 1.0,
                "max_output_tokens": 3072,
                "system_prompt": """你是一位專業的台灣勞動法律師。請提供詳細、專業的法律分析，包含：
1. 明確的法律依據（引用具體條文）
2. 法律邏輯推理
3. 實務建議

重要規則：
1. **必須**準確引用提供的法律條文
2. 引用格式：《法規名稱第X條》
3. 如果條文已涵蓋問題的主要面向，請提供完整分析
4. 只有在關鍵條文缺失時，才建議「諮詢專業律師」
5. 可以基於條文進行合理推論，但需標註「依法理推論」
6. 答案控制在500-800字"""
            },
            "COMPLEX": {
                "temperature": 1.0,
                "max_output_tokens": 4096,
                "system_prompt": """你是一位資深的台灣勞動法律師。請針對複雜問題提供全面分析，包含：
1. 問題拆解與層次分析
2. 每個層面的法律依據
3. 不同情況的處理方式
4. 潛在風險與注意事項

重要規則：
1. **必須**準確引用提供的法律條文
2. 引用格式：《法規名稱第X條》
3. 分段清晰，邏輯嚴謹
4. 如果條文已涵蓋主要爭點，請提供完整分析
5. 對於條文未明確規定的次要細節，可標註「需進一步確認」但不影響主要答案
6. 可以基於既有條文進行合理的法律推論
7. 答案控制在800-1200字"""
            }
        }
    
    def _init_openai_client(self) -> Optional[OpenAI]:
        """初始化 OpenAI 客戶端"""
        try:
            if not API_KEY_PATH.exists():
                print("[Lawyer] Warning: API key file not found")
                return None
            
            api_key = self._read_api_key()
            if not api_key:
                print("[Lawyer] Warning: API key is empty")
                return None
            
            return OpenAI(api_key=api_key)
        except Exception as e:
            print(f"[Lawyer] Failed to initialize OpenAI client: {e}")
            return None
    
    def _read_api_key(self) -> Optional[str]:
        """讀取 API key"""
        try:
            content = API_KEY_PATH.read_text(encoding="utf-8")
            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                if "openai" in ln.lower() and i + 1 < len(lines):
                    return lines[i + 1]
            for ln in lines:
                if ln.startswith(("sk-", "sk-proj-")):
                    return ln
            if lines:
                return lines[0]
        except Exception as e:
            print(f"[Lawyer] Failed to read API key: {e}")
        return None
    
    def generate_answer(
        self,
        query: str,
        analysis: AnalysisResult,
        citations: List[Dict],
        retry_feedback: Optional[str] = None
    ) -> LawyerResponse:
        """
        生成答案
        
        Args:
            query: 用戶查詢
            analysis: 接待員分析結果
            citations: 檢索到的引用
            retry_feedback: 重試時的反饋（如果有）
        """
        if not self.client:
            return LawyerResponse(
                answer="抱歉，系統暫時無法生成答案（API未配置）",
                confidence=0.0,
                used_citations=[],
                uncertainties=["系統配置問題"]
            )
        
        # 1. 選擇 Prompt 策略
        strategy = self.prompt_strategies.get(
            analysis.query_type,
            self.prompt_strategies["INFO"]
        )
        
        # 2. 組裝上下文
        context = self._build_context(citations)
        
        # 3. 組裝用戶消息
        topic_guidance = self._build_topic_guidance(analysis)
        user_message = self._build_user_message(
            query=query,
            context=context,
            topic_guidance=topic_guidance,
            retry_feedback=retry_feedback
        )
        
        # 4. 調用 LLM 生成答案
        try:
            answer = self._invoke_llm(
                messages=[
                    {"role": "system", "content": strategy["system_prompt"]},
                    {"role": "user", "content": user_message}
                ],
                temperature=strategy["temperature"],
                max_tokens=strategy["max_output_tokens"]
            )
        except Exception as e:
            print(f"[Lawyer] LLM generation failed: {e}")
            return LawyerResponse(
                answer=f"抱歉，答案生成失敗：{str(e)}",
                confidence=0.0,
                used_citations=[],
                uncertainties=["LLM 錯誤"]
            )
        
        
# 5. 提取使用的引用
        used_citations = self._extract_used_citations(answer, citations)
        
        # 6. 自我檢查
        confidence = self._self_check(answer, citations, len(used_citations))
        
        # 7. 標註不確定部分
        uncertainties = self._mark_uncertainties(answer)
        
        return LawyerResponse(
            answer=answer,
            confidence=confidence,
            used_citations=used_citations,
            uncertainties=uncertainties
        )
    
    def _build_context(self, citations: List[Dict]) -> str:
        """組裝上下文"""
        if not citations:
            return "（無相關法律條文資料）"
        
        context_parts = []
        for i, c in enumerate(citations[:10], 1):  # 最多10個
            law_name = c.get("law_name") or c.get("law_id") or c.get("title") or "未知法規"
            article_no = c.get("article_no", "")
            heading = c.get("heading", "")
            text = c.get("text", "")
            
            # 格式化
            part = f"【條文 {i}】\n"
            part += f"法規：{law_name}\n"
            if article_no:
                part += f"條號：第{article_no}條\n"
            if heading:
                part += f"標題：{heading}\n"
            part += f"內容：{text}\n"
            
            context_parts.append(part)
        
        return "\n".join(context_parts)
    
    def _build_user_message(
        self,
        query: str,
        context: str,
        topic_guidance: Optional[str],
        retry_feedback: Optional[str] = None
    ) -> str:
        """組裝用戶消息"""
        message = f"用戶問題：{query}\n\n"
        message += f"相關法律條文：\n{context}\n\n"
        
        if topic_guidance:
            message += "系統判定的重點主題與必備法條（務必引用）：\n"
            message += topic_guidance + "\n\n"
        
        if retry_feedback:
            message += f"上次生成的反饋：{retry_feedback}\n請根據反饋改進答案。\n\n"
        
        message += "請根據上述法律條文回答用戶問題。"
        
        return message

    def _build_topic_guidance(self, analysis: AnalysisResult) -> Optional[str]:
        """
        將接待員識別的主題轉換為「必備法條」提示，協助 LLM 主動引用。
        """
        if not analysis.topics or not self.law_guide_engine:
            return None
        
        sections: List[str] = []
        for topic_id in analysis.topics:
            guide = self.law_guide_engine.guides.get(topic_id)
            if not guide:
                continue
            topic_name = guide.get("name") or topic_id
            article_labels: List[str] = []
            for entry in guide.get("core_articles", []):
                law = entry.get("law")
                articles = entry.get("articles") or []
                if not law or not articles:
                    continue
                items = [f"{law}第{str(a).strip()}條" for a in articles if str(a).strip()]
                article_labels.extend(items)
            if article_labels:
                sections.append(f"- {topic_name}：{', '.join(article_labels)}")
        return "\n".join(sections) if sections else None
    
    def _invoke_llm(self, messages, temperature: float, max_tokens: int) -> str:
        """調用 LLM（gpt-5-mini 使用 Responses API）"""
        if not self.client:
            return ""
        
        # gpt-5-mini 使用 Responses API
        if self.model.startswith('gpt-5'):
            response = self.client.responses.create(
                model=self.model,
                input=messages,
                temperature=temperature,
                max_output_tokens=max_tokens
            )
            return self._extract_response_text(response)
        
        # 其他模型使用 Chat Completions API
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_completion_tokens=max_tokens
        )
        return (response.choices[0].message.content or '').strip()

    def _extract_response_text(self, response) -> str:
        """�� Responses API ��X�峹��l�J��r��"""
        text = getattr(response, 'output_text', None)
        if text:
            return text.strip()
        output_parts = []
        for item in getattr(response, 'output', []) or []:
            content_list = getattr(item, 'content', None)
            if not content_list:
                continue
            for content in content_list:
                piece = getattr(content, 'text', None)
                if piece is None and isinstance(content, dict):
                    piece = content.get('text')
                if piece:
                    output_parts.append(piece)
        return '\n\n'.join(output_parts).strip()

    def _extract_used_citations(self, answer: str, citations: List[Dict]) -> List[str]:
        """
        提取答案中實際使用的引用
        
        簡單策略：檢查答案中是否包含條文編號
        """
        used = []
        for c in citations:
            article_no = c.get("article_no", "").strip()
            law_name = c.get("law_name") or c.get("law_id") or ""
            
            if article_no and (
                f"第{article_no}條" in answer or
                f"第 {article_no} 條" in answer or
                (law_name and f"{law_name}第{article_no}條" in answer)
            ):
                citation_id = c.get("id") or f"{law_name}_{article_no}"
                used.append(citation_id)
        
        return used
    
    def _self_check(self, answer: str, citations: List[Dict], used_count: int) -> float:
        """
        自我檢查：評估答案信心度
        
        考慮因素：
        1. 是否使用了引用
        2. 答案長度是否合理
        3. 是否包含不確定性語言
        """
        confidence = 0.5  # 基準分數
        
        # 1. 使用引用 (+0.3)
        if used_count > 0:
            confidence += 0.3
        
        # 2. 答案長度合理 (+0.1)
        if 50 < len(answer) < 1500:
            confidence += 0.1
        
        # 3. 不包含不確定性語言 (+0.1)
        uncertainty_phrases = [
            "不確定", "可能", "或許", "也許", "不清楚",
            "需進一步確認", "建議諮詢專業律師"
        ]
        
        if not any(phrase in answer for phrase in uncertainty_phrases):
            confidence += 0.1
        else:
            confidence -= 0.2  # 有不確定性語言，降低信心
        
        return max(0.0, min(1.0, confidence))
    
    def _mark_uncertainties(self, answer: str) -> List[str]:
        """標註不確定部分"""
        uncertainties = []
        
        uncertainty_phrases = [
            "不確定", "可能", "或許", "也許",
            "需進一步確認", "建議諮詢專業律師"
        ]
        
        for phrase in uncertainty_phrases:
            if phrase in answer:
                # 提取包含該短語的句子
                sentences = answer.split('。')
                for sentence in sentences:
                    if phrase in sentence:
                        uncertainties.append(sentence.strip())
        
        return uncertainties[:3]  # 最多3個


"""LLM 客户端：调用 OpenAI 兼容的 /chat/completions 接口。

兼容 OpenAI / 豆包 / DeepSeek / 通义 / Ollama(localhost) 等任意兼容端点。
未配置 API Key 时也可直连本地模型服务（如 Ollama），仅当请求失败才报错。
"""
import json
import time
from typing import Iterator, Optional

import httpx

from app.config import settings
from app.utils.logger import logger


class LLMClient:
    def __init__(self) -> None:
        self.base_url = settings.LLM_API_BASE.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.timeout = settings.LLM_TIMEOUT

    def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, dict]:
        """返回 (回复文本, usage)。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        data = self._post("/chat/completions", payload)
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return content, usage

    def stream(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Iterator[str]:
        """流式返回回复文本增量（SSE 解析，逐块 yield）。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
        }
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.stream(
                "POST", url, json=payload, headers=headers, timeout=self.timeout
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 流式请求中断: %s", exc)
            raise RuntimeError(
                f"LLM 流式接口不可用（请检查 LLM_API_BASE / LLM_API_KEY / 网络）: {exc}"
            )

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("LLM 请求失败(第 %s 次): %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(
            f"LLM 接口不可用（请检查 LLM_API_BASE / LLM_API_KEY / 网络）: {last_error}"
        )

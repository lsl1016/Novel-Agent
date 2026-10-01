from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request

from .phase2_prompt import SYSTEM_PROMPT_V2

SYSTEM_PROMPT = """你是长篇小说叙事结构抽取器。只依据给定章节，不补充外部知识，不把猜测当事实。
目标不是普通NER，而是识别：Event、Mystery、Foreshadowing/Clue、Reveal、Payoff、EmotionDebt、Fact、BeliefState。
必须区分：世界真实状态、角色认知、读者当前可知状态。疑似伏笔必须标 candidate，除非本章明确回指或后续输入证明。
输出 JSON 对象，顶层字段 nodes 和 edges。每个 node: id,type,name,confidence,status,properties；每个 edge: source,target,type,confidence,properties。
properties 可含 thread_key、evidence、holder、belief_status、fact_key、emotion_type、target_chapter_hint。证据应短，不要复制长段原文。"""


def call_openai_compatible(
    user_prompt: str,
    model: str | None = None,
    *,
    system_prompt: str | None = None,
    retries: int = 3,
    timeout: int = 180,
) -> dict:
    """调用兼容 OpenAI 的 chat-completions 接口并返回 JSON。

    保持零第三方依赖,便于部署整条流水线。二阶段抽取器会传入更严格的系统提示词,
    并对返回的载荷单独进行校验。
    """
    base = os.environ.get("NKG_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("NKG_LLM_API_KEY", "")
    model = model or os.environ.get("NKG_LLM_MODEL", "")
    if not key or not model:
        raise RuntimeError("Set NKG_LLM_API_KEY and NKG_LLM_MODEL for semantic extraction")
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            last = exc
            if attempt + 1 >= retries:
                break
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"LLM request failed after {retries} attempts: {last}")

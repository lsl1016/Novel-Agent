"""统一模型调用客户端:OpenAI chat/completions 与 Anthropic Message 双协议。

按 ``{PREFIX}_*`` 环境变量解析端点(支持 fallback 前缀链),协议由
``NOVEL_LLM_PROTOCOL`` 或 ``{PREFIX}_PROTOCOL`` 指定,auto 时根据 base URL
是否包含 ``/anthropic`` 判定。零第三方依赖;Anthropic 响应只拼接
``type=='text'`` 的内容块(跳过 thinking 块)。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_OPENAI_BASE = 'https://api.openai.com/v1'
DEFAULT_MAX_TOKENS = 16384
_ANTHROPIC_VERSION = '2023-06-01'


def endpoint(prefix: str, fallback_prefixes: tuple[str, ...] | str | None = None) -> tuple[str, str, str, str]:
    fallbacks = (fallback_prefixes,) if isinstance(fallback_prefixes, str) else (fallback_prefixes or ())
    prefixes = (prefix, *fallbacks)
    base = key = model = None
    for p in prefixes:
        base = base or os.environ.get(f'{p}_BASE_URL')
        key = key or os.environ.get(f'{p}_API_KEY')
        model = model or os.environ.get(f'{p}_MODEL')
    base = base or os.environ.get('NKG_LLM_BASE_URL') or DEFAULT_OPENAI_BASE
    key = key or os.environ.get('NKG_LLM_API_KEY') or ''
    model = model or os.environ.get('NKG_LLM_MODEL') or ''
    protocol = (os.environ.get(f'{prefix}_PROTOCOL') or os.environ.get('NOVEL_LLM_PROTOCOL') or 'auto').strip().lower()
    if protocol == 'auto':
        protocol = 'anthropic' if '/anthropic' in base else 'openai'
    if protocol not in {'openai', 'anthropic'}:
        raise ValueError('protocol must be openai, anthropic or auto')
    return base, key, model, protocol


def configured(prefix: str, fallback_prefixes: tuple[str, ...] | str | None = None) -> bool:
    _, key, model, _ = endpoint(prefix, fallback_prefixes)
    return bool(key and model)


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.I)
        text = re.sub(r'\s*```$', '', text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        raise ValueError('expected JSON object')
    except Exception:
        start, end = text.find('{'), text.rfind('}')
        if start >= 0 and end > start:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        raise ValueError('model did not return a JSON object')


def _max_tokens(prefix: str, default: int | None) -> int:
    if default is not None:
        return int(default)
    return int(os.environ.get(f'{prefix}_MAX_TOKENS') or DEFAULT_MAX_TOKENS)


def chat(system_prompt: str, user_prompt: str, *, prefix: str,
         fallback_prefixes: tuple[str, ...] | str | None = None, model: str | None = None,
         temperature: float = 0.7, json_mode: bool = False, max_tokens: int | None = None,
         timeout: int = 240) -> tuple[str, str]:
    base, key, configured_model, protocol = endpoint(prefix, fallback_prefixes)
    model = model or configured_model
    if not key or not model:
        raise RuntimeError(f'Set {prefix}_API_KEY and {prefix}_MODEL (or configured fallback)')
    limit = _max_tokens(prefix, max_tokens)

    if protocol == 'openai':
        url = base.rstrip('/') + '/chat/completions'
        headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
        payload: dict[str, Any] = {
            'model': model, 'temperature': temperature, 'max_tokens': limit,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        }
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}

        def extract(data: dict[str, Any]) -> str:
            return data['choices'][0]['message']['content']
    else:
        url = base.rstrip('/') + '/v1/messages'
        headers = {'x-api-key': key, 'Authorization': f'Bearer {key}',
                   'anthropic-version': _ANTHROPIC_VERSION, 'Content-Type': 'application/json'}
        payload = {
            'model': model, 'temperature': temperature, 'max_tokens': limit,
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': user_prompt}],
        }

        def extract(data: dict[str, Any]) -> str:
            text = ''.join(b.get('text', '') for b in data.get('content', []) if isinstance(b, dict) and b.get('type') == 'text')
            if not text.strip():
                raise ValueError(f"no text block in response (stop_reason={data.get('stop_reason')}); increase {prefix}_MAX_TOKENS if using a thinking model")
            return text

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers=headers, method='POST')
    # 思考型模型的非流式响应可能长时间无字节返回,超时按角色可配
    timeout = int(os.environ.get(f'{prefix}_TIMEOUT') or timeout)
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return extract(data), model
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last = exc
            if attempt < 2:
                time.sleep(min(2 ** attempt, 4))
    raise RuntimeError(f'{prefix.lower()} model request failed: {last}')


def chat_json(system_prompt: str, user_prompt: str, *, prefix: str,
              fallback_prefixes: tuple[str, ...] | str | None = None, model: str | None = None,
              temperature: float = 0.2, max_tokens: int | None = None,
              timeout: int = 240) -> tuple[dict[str, Any], str]:
    text, used = chat(system_prompt, user_prompt, prefix=prefix, fallback_prefixes=fallback_prefixes,
                      model=model, temperature=temperature, json_mode=True, max_tokens=max_tokens, timeout=timeout)
    return parse_json_object(text), used

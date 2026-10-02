"""统一模型调用客户端:OpenAI chat/completions 与 Anthropic Message 双协议。

按 ``{PREFIX}_*`` 环境变量解析端点(支持 fallback 前缀链),协议由
``NOVEL_LLM_PROTOCOL`` 或 ``{PREFIX}_PROTOCOL`` 指定,auto 时根据 base URL
是否包含 ``/anthropic`` 判定。零第三方依赖;Anthropic 响应只拼接
``type=='text'`` 的内容块(跳过 thinking 块)。设置 ``NOVEL_THINKING_LOG``
时,思考块(OpenAI 协议的 reasoning_content 同理)会追加写入该 JSONL 文件,
用于观察模型的思考创作过程。
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
DEFAULT_MAX_TOKENS = 32768
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


def _balanced_json_objects(text: str):
    """按出现顺序产出 text 中每个平衡的 JSON 对象片段(尊重字符串与转义)。

    模型偶尔在答案对象之后追加第二个对象或尾注;首尾截取(first{..last})
    会跨对象边界产生 "Extra data"。这里逐字符扫描,逐个尝试解析。
    """
    pos = 0
    while True:
        start = text.find('{', pos)
        if start < 0:
            return
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    yield text[start:i + 1]
                    pos = i + 1
                    break
        else:
            return  # 扫到结尾仍不平衡:后面不会再有完整对象


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.I)
        text = re.sub(r'\s*```$', '', text)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    for candidate in _balanced_json_objects(text):
        try:
            obj = json.loads(candidate)
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError('model did not return a JSON object')


def _max_tokens(prefix: str, default: int | None) -> int:
    if default is not None:
        return int(default)
    return int(os.environ.get(f'{prefix}_MAX_TOKENS') or DEFAULT_MAX_TOKENS)


def _note_thinking(prefix: str, model: str, thinking: str, answer_preview: str = '') -> None:
    """可选捕获思考型模型的思考过程,追加写 JSONL(NOVEL_THINKING_LOG 指定路径)。

    未设置该环境变量时零开销;写日志失败不影响模型调用主流程。
    """
    path = os.environ.get('NOVEL_THINKING_LOG', '').strip()
    if not path or not (thinking or '').strip():
        return
    try:
        entry = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'role': prefix, 'model': model,
                 'thinking': thinking, 'answer_preview': answer_preview[:400]}
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except OSError:
        pass


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
            msg = data['choices'][0]['message']
            _note_thinking(prefix, model, msg.get('reasoning_content') or msg.get('reasoning') or '',
                           msg.get('content') or '')
            return msg['content']
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
            blocks = [b for b in data.get('content', []) if isinstance(b, dict)]
            text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            _note_thinking(prefix, model,
                           '\n\n'.join(b.get('thinking') or '' for b in blocks if b.get('type') == 'thinking'),
                           text)
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
    # 解析失败(截断/夹带叙述)也重试:思考型模型偶发把 max_tokens 烧在 thinking 上,重试即恢复
    last_exc: Exception | None = None
    for _ in range(3):
        text, used = chat(system_prompt, user_prompt, prefix=prefix, fallback_prefixes=fallback_prefixes,
                          model=model, temperature=temperature, json_mode=True, max_tokens=max_tokens, timeout=timeout)
        try:
            return parse_json_object(text), used
        except ValueError as exc:
            last_exc = exc
    raise last_exc or ValueError('model did not return a JSON object')

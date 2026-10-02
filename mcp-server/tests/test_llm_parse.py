"""chat_json 输出形状防线:多对象/尾注/围栏/不平衡等病态输出必须能救回首个对象。"""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.llm_client import parse_json_object, _note_thinking


def test_plain_and_fenced():
    assert parse_json_object('{"a":1}') == {'a': 1}
    assert parse_json_object('```json\n{"a":1}\n```') == {'a': 1}


def test_trailing_junk_after_object():
    text = '{"a": {"b": 2}} 以上即最终答案。'
    assert parse_json_object(text) == {'a': {'b': 2}}


def test_two_objects_takes_first():
    # 首尾截取会跨对象边界报 Extra data(char 1907 类事故的根因)
    text = '{"title":"甲","body":"x"}{"title":"乙"}'
    assert parse_json_object(text) == {'title': '甲', 'body': 'x'}


def test_braces_inside_strings_do_not_break_balance():
    text = '说明 {"k": "v 含 } 与 { 字符"} 尾注 {"second": true}'
    assert parse_json_object(text) == {'k': 'v 含 } 与 { 字符'}


def test_no_object_raises():
    try:
        parse_json_object('没有任何对象')
        assert False
    except ValueError:
        pass


def test_thinking_capture(tmp_path):
    log = tmp_path / 'thinking.jsonl'
    old = os.environ.get('NOVEL_THINKING_LOG')
    try:
        os.environ['NOVEL_THINKING_LOG'] = str(log)
        _note_thinking('NOVEL_PLANNER', 'glm-4.6', '先确认视角约束…', '{"ok":true,…}')
        _note_thinking('NOVEL_PLANNER', 'glm-4.6', '')  # 空思考不写
        _note_thinking('NOVEL_PLANNER', 'glm-4.6', 'x' * 500, 'a' * 500)  # 答案预览截断
    finally:
        if old is None:
            os.environ.pop('NOVEL_THINKING_LOG', None)
        else:
            os.environ['NOVEL_THINKING_LOG'] = old
    lines = log.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first['role'] == 'NOVEL_PLANNER' and first['model'] == 'glm-4.6'
    assert first['thinking'] == '先确认视角约束…'
    assert len(json.loads(lines[1])['answer_preview']) == 400


def test_thinking_capture_disabled_by_default(tmp_path):
    log = tmp_path / 'thinking.jsonl'
    old = os.environ.pop('NOVEL_THINKING_LOG', None)
    try:
        _note_thinking('NOVEL_PLANNER', 'glm-4.6', '不该被写入')
    finally:
        if old is not None:
            os.environ['NOVEL_THINKING_LOG'] = old
    assert not log.exists()

"""summarizer_postprocess 对齐与增强逻辑单测。"""

import pytest

from backend.summarizer_postprocess import align_mindmap_l1_to_chapters, apply_summary_result_enhancements


def test_align_mindmap_l1_matches_chapter_by_overlap():
    chapters = [
        {"start": 0, "end": 60, "title": "引言与背景", "points": []},
        {"start": 60, "end": 120, "title": "核心方法", "points": []},
    ]
    children = [
        {"id": "a", "name": "错名", "start": 5, "end": 50, "importance": 3, "children": []},
        {"id": "b", "name": "另一错", "start": 70, "end": 100, "importance": 3, "children": []},
    ]
    align_mindmap_l1_to_chapters(children, chapters)
    assert children[0]["name"] == "引言与背景"
    assert children[0]["start"] == 0
    assert children[0]["end"] == 60
    assert children[1]["name"] == "核心方法"
    assert children[1]["start"] == 60


def test_apply_summary_result_enhancements_mutates_mindmap():
    normalized = {
        "summary": ["a"],
        "chapters": [{"start": 0, "end": 30, "title": "第一章", "points": ["p"]}],
        "highlights": [{"ts": 12, "text": "关键证据示例"}],
        "mindmap": {
            "title": "根",
            "children": [{"id": "n1", "name": "x", "start": 0, "end": 30, "importance": 3, "children": []}],
        },
        "summary_sections": {},
    }
    out = apply_summary_result_enhancements(normalized)
    assert out is normalized
    assert normalized["mindmap"]["children"][0]["name"] == "第一章"
    child_rows = normalized["mindmap"]["children"][0]["children"]
    assert child_rows
    assert any(str(n["name"]).startswith("主旨：") for n in child_rows)
    key_node = next((n for n in child_rows if str(n["name"]) == "关键要点"), None)
    evidence_node = next((n for n in child_rows if str(n["name"]) == "时间证据"), None)
    assert key_node and (key_node.get("children") or [])
    assert evidence_node and (evidence_node.get("children") or [])
    assert any(str(n["name"]).startswith("要点") for n in (key_node.get("children") or []))
    assert any(str(n["name"]).startswith("证据") for n in (evidence_node.get("children") or []))


def test_apply_summary_result_enhancements_works_with_truncated_l1_title():
    normalized = {
        "summary": ["a"],
        "chapters": [
            {"start": 0, "end": 80, "title": "这是一个很长很长的章节标题用于测试截断", "points": ["要点A", "要点B"]},
        ],
        "highlights": [{"ts": 20, "text": "高亮证据"}],
        "mindmap": {
            "title": "根",
            "children": [{"id": "n1", "name": "旧标题", "start": 0, "end": 80, "importance": 3, "children": []}],
        },
        "summary_sections": {},
    }
    apply_summary_result_enhancements(normalized)
    child_rows = normalized["mindmap"]["children"][0]["children"]
    assert child_rows
    assert any(str(n["name"]).startswith("主旨：") for n in child_rows)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

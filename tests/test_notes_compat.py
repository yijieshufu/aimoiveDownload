"""notes/summary 字段兼容层单测。"""

from backend.workspace_store import _sanitize_summary_sections, _to_note_sections


def test_sanitize_sections_accepts_key_takeaways():
    cleaned = _sanitize_summary_sections(
        {
            "overview": ["o1"],
            "outline": ["p1"],
            "key_takeaways": ["k1", "k2"],
            "one_liner": "x",
        }
    )
    assert cleaned["overview"] == ["o1"]
    assert cleaned["outline"] == ["p1"]
    assert cleaned["key_points"] == ["k1", "k2"]
    assert cleaned["one_liner"] == "x"


def test_to_note_sections_maps_key_points_to_key_takeaways():
    notes = _to_note_sections(
        {
            "overview": ["a"],
            "outline": ["b"],
            "key_points": ["c"],
            "one_liner": "d",
        }
    )
    assert notes == {
        "overview": ["a"],
        "outline": ["b"],
        "key_takeaways": ["c"],
        "one_liner": "d",
    }

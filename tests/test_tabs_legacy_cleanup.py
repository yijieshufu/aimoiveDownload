from backend.database import get_db, init_db
from backend.workspace_store import get_tabs


def test_init_db_removes_legacy_note_tab():
    now = 1
    with get_db() as conn:
        conn.execute("DELETE FROM ui_tabs")
        conn.execute(
            "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
            ("summary", "Summary", "system", 0, 1, now),
        )
        conn.execute(
            "INSERT INTO ui_tabs (id,name,type,order_index,visible,updated_at) VALUES (?,?,?,?,?,?)",
            ("note", "AI笔记", "system", 1, 1, now),
        )

    init_db()

    ids = [tab["id"] for tab in get_tabs()]
    assert "summary" in ids
    assert "note" not in ids

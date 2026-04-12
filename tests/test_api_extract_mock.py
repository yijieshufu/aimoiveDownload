"""外网与 yt-dlp 用 mock 隔离，仅验证路由与额度钩子可调用。"""
from unittest.mock import patch


def test_me_includes_usage(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    data = r.json()
    assert "usage" in data
    assert "hint" in data["usage"]


@patch("backend.api_video.extract_video_info")
def test_extract_ok_records_usage(mock_extract, client):
    mock_extract.return_value = {
        "title": "stub",
        "duration": 10,
        "uploader": "u",
        "view_count": 0,
        "thumbnail": "",
        "formats": [{"format_id": "18", "ext": "mp4", "height": 360, "width": 640, "filesize": 100}],
    }
    r = client.post("/api/extract", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "stub"
    me = client.get("/api/me").json()
    assert me["usage"]["extract_remaining"] is not None


@patch("backend.api_video.extract_video_info")
def test_extract_maps_error_message(mock_extract, client):
    mock_extract.side_effect = RuntimeError("ERROR: Private video")
    r = client.post("/api/extract", json={"url": "https://example.com/watch?v=1"})
    assert r.status_code == 400
    assert "私密" in r.json()["detail"] or "权限" in r.json()["detail"]

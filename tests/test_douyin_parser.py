"""抖音解析纯逻辑单测（不访问外网）。"""
from unittest.mock import patch

from backend.douyin_parser import (
    _find_playwm_url_in_share_html,
    build_douyin_nowm_url,
    get_douyin_item_info,
)


def test_build_douyin_nowm_url_replaces_playwm():
    item = {
        "video": {
            "play_addr": {
                "url_list": ["https://example.com/aweme/playwm/?token=1"],
            }
        }
    }
    out = build_douyin_nowm_url(item)
    assert "playwm" not in out
    assert "play?" in out or "/play" in out


def test_find_playwm_url_escaped_json():
    html = (
        r'foo "url_list":["https:\\u002F\\u002Fv.example.com\\u002F'
        r'path\\u002Fplaywm\\u002Ffile.mp4"] bar'
    )
    u = _find_playwm_url_in_share_html(html)
    assert "playwm" in u
    assert u.startswith("https://")


def test_find_playwm_url_plain_json():
    html = '"url_list":["https://v.example.com/aweme/playwm/abc.mp4"]'
    u = _find_playwm_url_in_share_html(html)
    assert "https://v.example.com" in u
    assert "playwm" in u


@patch("backend.douyin_parser._extract_item_from_share_page")
@patch("backend.douyin_parser._http_get_json")
@patch("backend.douyin_parser._resolve_redirect_url")
def test_get_douyin_item_info_uses_api_when_item_list_nonempty(
    mock_resolve, mock_json, mock_share,
):
    mock_resolve.return_value = "https://www.iesdouyin.com/share/video/12345/"
    mock_json.return_value = {
        "item_list": [
            {
                "desc": "api_title",
                "author": {"nickname": "u1"},
                "video": {
                    "play_addr": {"url_list": ["https://cdn/x/playwm/1"]},
                    "duration": 10000,
                },
                "statistics": {"play_count": 9},
            }
        ]
    }
    item = get_douyin_item_info("https://v.douyin.com/xx/")
    assert item["desc"] == "api_title"
    mock_share.assert_not_called()


@patch("backend.douyin_parser._extract_item_from_share_page")
@patch("backend.douyin_parser._http_get_json")
@patch("backend.douyin_parser._resolve_redirect_url")
def test_get_douyin_item_info_falls_back_to_share_page(
    mock_resolve, mock_json, mock_share,
):
    mock_resolve.return_value = "https://www.iesdouyin.com/share/video/99999/"
    mock_json.return_value = {"item_list": []}
    mock_share.return_value = {
        "desc": "share_title",
        "author": {"nickname": "u2"},
        "video": {
            "width": 720,
            "height": 1280,
            "duration": 5000,
            "cover": {"url_list": []},
            "play_addr": {"url_list": ["https://cdn/y/playwm/2"]},
        },
        "statistics": {"play_count": 0},
    }
    item = get_douyin_item_info("https://v.douyin.com/yy/")
    assert item["desc"] == "share_title"
    mock_share.assert_called_once_with("99999")

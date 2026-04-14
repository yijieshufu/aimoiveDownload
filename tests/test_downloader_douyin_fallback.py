from unittest.mock import patch

from backend.downloader import download_video


class _FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        if not download:
            return {
                "formats": [
                    {"format_id": "v1", "vcodec": "avc1", "acodec": "none"},
                ]
            }
        raise Exception("Unable to download video: [Errno 22] Invalid argument")


@patch("backend.downloader.is_douyin_url", return_value=True)
@patch("backend.downloader.download_douyin_video")
@patch("backend.downloader.yt_dlp.YoutubeDL", _FakeYDL)
def test_download_video_douyin_fallback_on_invalid_argument(mock_download_douyin, _mock_is_douyin):
    mock_download_douyin.return_value = {
        "title": "Douyin Video",
        "file_path": "temp/video_x.mp4",
        "file_size": 123,
        "ext": "mp4",
    }

    out = download_video("https://v.douyin.com/abc123/", "v1")
    assert out["ext"] == "mp4"
    mock_download_douyin.assert_called_once()


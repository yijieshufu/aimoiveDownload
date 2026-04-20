from backend.summarizer import (
    _expand_json_caption_blob_segments,
    _extract_subtitle_segments,
    _parse_json_subtitle_segments,
    _segments_to_transcript_text,
    normalize_summary_result_payload,
)


def test_parse_json_subtitle_segments_handles_youtube_json3():
    raw = """
    )]}'
    {
      "wireMagic": "pb3",
      "events": [
        {
          "tStartMs": 0,
          "dDurationMs": 2100,
          "segs": [{"utf8": "Hello"}, {"utf8": " world"}]
        },
        {
          "tStartMs": 2500,
          "dDurationMs": 1800,
          "segs": [{"utf8": "第二句\\n"}, {"utf8": "继续"}]
        }
      ]
    }
    """

    segs = _parse_json_subtitle_segments(raw)

    assert segs == [
        {"start": 0.0, "end": 2.1, "text": "Hello world"},
        {"start": 2.5, "end": 4.3, "text": "第二句 继续"},
    ]


def test_segments_to_transcript_text_skips_empty_and_consecutive_duplicates():
    text = _segments_to_transcript_text(
        [
            {"start": 0, "text": "第一句"},
            {"start": 1, "text": "第一句"},
            {"start": 2, "text": "第二句"},
            {"start": 3, "text": ""},
            {"start": 4, "text": "第三句"},
        ]
    )

    assert text == "第一句\n第二句\n第三句"


def test_parse_json_subtitle_segments_falls_back_to_jsonish_event_scan():
    raw = """
    random-prefix
    "tStartMs": 1000, "dDurationMs": 1600, "segs": [{"utf8": "Hello\\n"}, {"utf8": "again"}]
    random-middle
    "tStartMs": 4000, "dDurationMs": 1200, "segs": [{"utf8": "\\u4e0b\\u4e00\\u53e5"}]
    """

    segs = _parse_json_subtitle_segments(raw)

    assert segs == [
        {"start": 1.0, "end": 2.6, "text": "Hello again"},
        {"start": 4.0, "end": 5.2, "text": "下一句"},
    ]


def test_expand_json_caption_blob_segments_expands_single_json_blob_segment():
    segs = _expand_json_caption_blob_segments(
        [
            {
                "start": 0.0,
                "end": 12.0,
                "text": '{"events":[{"tStartMs":1000,"dDurationMs":1000,"segs":[{"utf8":"字幕一"}]},{"tStartMs":2500,"dDurationMs":1500,"segs":[{"utf8":"字幕二"}]}]}',
            }
        ]
    )

    assert segs == [
        {"start": 1.0, "end": 2.0, "text": "字幕一"},
        {"start": 2.5, "end": 4.0, "text": "字幕二"},
    ]


def test_normalize_summary_result_payload_repairs_saved_json_blob_segments():
    payload = normalize_summary_result_payload(
        {
            "title": "测试视频",
            "transcript_source": "low_signal_fallback",
            "transcript_text": "原始兜底文本",
            "transcript_quality_reason": "转写子句重复率过高",
            "subtitle_segments": [
                    {
                        "start": 0.0,
                        "end": 12.0,
                    "text": '{"events":[{"tStartMs":1000,"dDurationMs":1000,"segs":[{"utf8":"第一条字幕信息内容"}]},{"tStartMs":2500,"dDurationMs":1500,"segs":[{"utf8":"第二条字幕信息内容"}]}]}',
                    }
                ],
            }
        )

    assert payload["subtitle_segments"] == [
        {"start": 1.0, "end": 2.0, "text": "第一条字幕信息内容"},
        {"start": 2.5, "end": 4.0, "text": "第二条字幕信息内容"},
    ]
    assert "可用字幕片段：" in payload["transcript_text"]
    assert "[00:01] 第一条字幕信息内容" in payload["transcript_text"]


def test_extract_subtitle_segments_uses_json_subtitles_before_plain_text_fallback(monkeypatch):
    raw = """
    WEBVTT

    00:00:00.000 --> 00:00:12.000
    {
      "events": [
        {
          "tStartMs": 1000,
          "dDurationMs": 1000,
          "segs": [{"utf8": "字幕一"}]
        },
        {
          "tStartMs": 2500,
          "dDurationMs": 1500,
          "segs": [{"utf8": "字幕二"}]
        }
      ]
    }
    """

    class DummyYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return {
                "duration": 12,
                "automatic_captions": {
                    "zh-Hans": [{"url": "https://example.com/captions.json3"}],
                },
            }

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return raw.encode("utf-8")

    monkeypatch.setattr("backend.summarizer.build_ydl_option_variants", lambda base_opts, url: [base_opts])
    monkeypatch.setattr("backend.summarizer.yt_dlp.YoutubeDL", DummyYoutubeDL)
    monkeypatch.setattr("backend.summarizer.urllib.request.urlopen", lambda req, timeout=60: DummyResponse())

    segs, source = _extract_subtitle_segments("https://www.youtube.com/watch?v=test")

    assert source == "platform_caption"
    assert segs == [
        {"start": 1.0, "end": 2.0, "text": "字幕一"},
        {"start": 2.5, "end": 4.0, "text": "字幕二"},
    ]


def test_normalize_summary_result_payload_keeps_prebuilt_low_signal_text():
    prebuilt = "【低信号视频兜底模式】以下内容基于标题、简介、可用字幕片段整理，细节需二次核实。\n视频标题：测试视频"
    payload = normalize_summary_result_payload(
        {
            "title": "测试视频",
            "transcript_source": "low_signal_fallback",
            "transcript_text": prebuilt,
            "transcript_quality_reason": "转写存在明显循环重复片段",
            "subtitle_segments": [
                {"start": 0.0, "end": 3.0, "text": "字幕一"},
                {"start": 3.0, "end": 6.0, "text": "字幕二"},
            ],
        }
    )

    assert payload["transcript_text"] == prebuilt

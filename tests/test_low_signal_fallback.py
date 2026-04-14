from backend.summarizer import _build_low_signal_fallback_text


def test_build_low_signal_fallback_text_includes_context_and_segments():
    info = {
        "title": "AI 浏览器自动化流程与实践",
        "uploader": "测试作者",
        "description": "这是一段视频简介，介绍浏览器自动化、重复任务处理和低 token 成本。",
        "tags": ["Agent", "Playwright", "自动化"],
    }
    transcript = "music music 问题被解决因为问题被解决 浏览器自动化可以替代机械重复工作"
    subtitle_segments = [
        {"start": 0, "text": "浏览器自动化可以替代机械重复工作"},
        {"start": 29, "text": "Playwright CLI 能显著降低 Token 消耗"},
    ]

    text = _build_low_signal_fallback_text(info, transcript, subtitle_segments, "转写存在明显循环重复片段")

    assert "低信号视频兜底模式" in text
    assert "视频标题：AI 浏览器自动化流程与实践" in text
    assert "作者：测试作者" in text
    assert "可用字幕片段：" in text
    assert "[00:29] Playwright CLI 能显著降低 Token 消耗" in text
    assert "低信号原因：转写存在明显循环重复片段" in text

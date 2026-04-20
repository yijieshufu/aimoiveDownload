from __future__ import annotations

import yt_dlp
import os
import sys
import json
import subprocess
from typing import Optional, List, Dict
import urllib.parse
import re

from .douyin_parser import extract_douyin_info, download_douyin_video, is_douyin_url


def shorten_windows_path(path: str) -> str:
    """尽量缩短路径，降低 Win32 CreateFile EINVAL 概率。"""
    if sys.platform != "win32":
        return path
    try:
        import ctypes

        os.makedirs(path, exist_ok=True)
        buf = ctypes.create_unicode_buffer(4096)
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        n = k32.GetShortPathNameW(ctypes.c_wchar_p(path), buf, len(buf))
        if n and buf.value:
            return buf.value
    except Exception:
        pass
    return path


def windows_long_path(abs_path: str) -> str:
    """为绝对路径加 \\\\?\\ 前缀，便于突破 MAX_PATH（仅 win32）。"""
    if sys.platform != "win32":
        return abs_path
    p = os.path.abspath(os.path.normpath(abs_path))
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        rest = p[2:].replace("/", "\\").lstrip("\\")
        return "\\\\?\\UNC\\" + rest
    return "\\\\?\\" + p


# 确保临时目录存在（绝对路径，避免 Windows 下子进程/合并输出路径异常）
temp_dir = shorten_windows_path(os.path.abspath(os.path.join(os.getcwd(), "temp")))
os.makedirs(temp_dir, exist_ok=True)
cookie_file_path = os.path.join(temp_dir, "cookies.txt")
BROWSER_COOKIE_CANDIDATES = ("edge", "chrome", "chromium", "firefox")
_URL_TRAILING_CHARS = ")]},.;:!?\"'，。！？；：、】）》）】>"


def format_user_ytdlp_error(exc: BaseException) -> str:
    """将 yt-dlp / 本仓库异常转写为更可读的提示（仍保留部分原文便于排障）。"""
    text = str(exc).strip() or type(exc).__name__
    low = text.lower()
    if "pro" in text and "专享" in text:
        return text
    if "private video" in low or "私享" in text or "members only" in low:
        return "该视频为私密、会员专享或权限不足，无法解析。"
    if "login required" in low or "sign in to confirm" in low:
        return "该平台需要登录后才能访问：可尝试上传 cookies.txt（Netscape 格式）或先在浏览器登录。"
    if "drm" in low:
        return "受 DRM 或版权加密保护的内容无法通过此方式下载。"
    if "http error 403" in low or ("403" in text and "forbidden" in low):
        return "被拒绝访问 (403)：可能被风控或需要有效登录态。"
    if "not available on this app" in low:
        return "该内容在当前客户端类型下不可用，请尝试其它来源。"
    if "unable to download" in low:
        return "无法拉取媒体文件：链接可能过期、需登录或网络不稳定。"
    if "errno 22" in low or "invalid argument" in low:
        if sys.platform == "win32":
            return (
                "保存或合并文件失败（Invalid argument）：常见于 Windows 下文件名含非法字符。"
                "请升级 yt-dlp 到最新版后重试；若仍失败，可将项目放在较短英文路径下再试。"
            )
        return text[:420] + ("…" if len(text) > 420 else "")
    if "ffmpeg" in low or "ffprobe" in low or ("merge" in low and "audio" in low):
        return "音视频处理失败：请确认已安装 ffmpeg/ffprobe 且在 PATH 中可用。"
    return text[:420] + ("…" if len(text) > 420 else "")


def _is_invalid_argument_error(exc: BaseException) -> bool:
    low = str(exc).lower()
    return ("invalid argument" in low) or ("errno 22" in low)


def _format_is_ultra_hd(fmt: Optional[Dict]) -> bool:
    if not fmt:
        return False
    w = int(fmt.get("width") or 0)
    h = int(fmt.get("height") or 0)
    if w <= 0 and h <= 0:
        return False
    return max(w, h) >= 3840 or (w > 0 and h > 0 and min(w, h) >= 2160)


def format_duration(seconds: float) -> str:
    """将秒数格式化为 HH:mm:ss 字符串"""
    if not seconds:
        return "00:00"
    
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def _estimate_format_bytes_from_bitrate(fmt: Dict, duration_s: float) -> int:
    """yt-dlp 很多站点不提供 filesize，用码率 × 时长估算（字节，偏保守展示用）。"""
    d = float(duration_s or 0)
    if d <= 0:
        return 0
    tbr = fmt.get("tbr")
    try:
        if tbr is not None and float(tbr) > 0:
            return int(d * float(tbr) * 1000 / 8)
    except (TypeError, ValueError):
        pass
    try:
        vbr = float(fmt.get("vbr") or 0)
        abr = float(fmt.get("abr") or 0)
        br = vbr + abr
        if br > 0:
            return int(d * br * 1000 / 8)
    except (TypeError, ValueError):
        pass
    return 0


def _merged_display_size(fmt: Dict, duration_s: float) -> tuple[int, str]:
    """
    返回 (bytes, kind)，kind: exact | approx | estimate | unknown
    """
    try:
        fs = fmt.get("filesize")
        if fs is not None and int(fs) > 0:
            return int(fs), "exact"
    except (TypeError, ValueError):
        pass
    try:
        fa = fmt.get("filesize_approx")
        if fa is not None and int(fa) > 0:
            return int(fa), "approx"
    except (TypeError, ValueError):
        pass
    est = _estimate_format_bytes_from_bitrate(fmt, duration_s)
    if est > 0:
        return est, "estimate"
    return 0, "unknown"


def _normalize_thumbnail_url(url: str) -> str:
    """协议相对、http 转 https，避免封面代理 urlparse 失败或混合内容。"""
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http://"):
        return "https://" + u[len("http://") :]
    return u


def _youtube_avoid_maxres(url: str) -> str:
    """YouTube maxresdefault 大量视频不存在，统一降级为 hqdefault。"""
    u = (url or "").strip()
    if not u:
        return u
    low = u.lower()
    if "ytimg.com" in low and "maxresdefault" in low:
        return re.sub(r"maxresdefault", "hqdefault", u, flags=re.IGNORECASE)
    return u


def get_best_thumbnail(thumbnails: List[Dict]) -> str:
    """从缩略图列表中选择质量最高的缩略图"""
    if not thumbnails:
        return ''

    def _get_url(t: Dict) -> str:
        # yt-dlp 不同站点/版本字段名可能略有差异
        for key in ("url", "thumbnail", "src"):
            v = t.get(key)
            if v:
                return v
        return ''

    def _url_lower(t: Dict) -> str:
        return _get_url(t).lower()

    # 优先选择有 width 和 height 的缩略图
    valid_thumbnails = [t for t in thumbnails if t.get('width') and t.get('height')]
    if not valid_thumbnails:
        # 如果没有尺寸信息，返回第一个有 URL 的缩略图
        for t in thumbnails:
            url = _get_url(t)
            if url:
                return _youtube_avoid_maxres(_normalize_thumbnail_url(url))
        return ''

    # YouTube：尽量避免选到常 404 的 maxres（有其它档位时优先用其它）
    non_maxres = [t for t in valid_thumbnails if "maxresdefault" not in _url_lower(t)]
    pick_pool = non_maxres if non_maxres else valid_thumbnails
    best = max(pick_pool, key=lambda t: t['width'] * t['height'])
    return _youtube_avoid_maxres(_normalize_thumbnail_url(_get_url(best)))


def check_ffmpeg_available() -> bool:
    """检查 FFmpeg 是否可用"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=False)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def normalize_input_to_url(s: str) -> str:
    def _strip_trailing(url: str) -> str:
        return (url or "").strip().rstrip(_URL_TRAILING_CHARS)

    s = (s or "").strip()
    if not s:
        return ""
    if re.match(r"^https?://", s, flags=re.IGNORECASE):
        return _strip_trailing(s)
    m = re.search(r"(https?://[^\s\"'<>]+)", s, flags=re.IGNORECASE)
    if m:
        return _strip_trailing(m.group(1))
    m2 = re.search(r"\b(v\.douyin\.com/[A-Za-z0-9]+)\b", s, flags=re.IGNORECASE)
    if m2:
        return "https://" + m2.group(1)
    return ""


def _default_http_headers(url: str) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if "bilibili.com" in (url or "").lower():
        headers.setdefault("Referer", "https://www.bilibili.com/")
    return headers


def _apply_platform_ydl_defaults(opts: Dict, url: str) -> None:
    """Windows 下 DASH/分片临时文件名若含标题中的 : | 等会触发 OSError(22, EINVAL)。"""
    h = opts.get("http_headers")
    merged = _default_http_headers(url)
    if isinstance(h, dict) and h:
        merged = {**merged, **h}
    opts["http_headers"] = merged
    if sys.platform == "win32":
        # YoutubeDL 参数名为 windowsfilenames（非 windows_filenames），否则不会生效
        opts.setdefault("windowsfilenames", True)
        opts.setdefault("restrictfilenames", True)


def build_ydl_option_variants(base_opts: Dict, url: str) -> List[Dict]:
    """
    优先顺序：
    1) 手动上传 cookies.txt
    2) 自动读取浏览器 cookies（edge/chrome/chromium/firefox）
    3) 无 cookies（非抖音可用）
    """
    base_opts = dict(base_opts)
    _apply_platform_ydl_defaults(base_opts, url)
    variants: List[Dict] = []
    if os.path.exists(cookie_file_path):
        with_file = dict(base_opts)
        with_file["cookiefile"] = cookie_file_path
        variants.append(with_file)

    if is_douyin_url(url):
        for browser in BROWSER_COOKIE_CANDIDATES:
            with_browser = dict(base_opts)
            with_browser["cookiesfrombrowser"] = (browser,)
            variants.append(with_browser)

    variants.append(dict(base_opts))
    return variants


def extract_video_info(url: str) -> Dict:
    """提取视频信息"""
    normalized_url = normalize_input_to_url(url)
    if not normalized_url:
        raise Exception("请输入有效的视频URL（抖音请粘贴包含 https://v.douyin.com/... 的分享链接，而不是口令文案）")
    douyin_primary_error = None
    if is_douyin_url(normalized_url):
        try:
            # 优先使用“短链跳转 -> video_id -> 公开接口 -> playwm=>play”的轻量方案
            return extract_douyin_info(normalized_url)
        except Exception as e:
            # 某些公开视频在风控下会返回空 JSON，自动回退 yt-dlp 方案
            douyin_primary_error = e

    ydl_opts = {
        'noplaylist': True,
        'quiet': True,
        'skip_download': True,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'playlistend': 1,
        # 这里不要吞错误，便于前端看到真实失败原因
        'ignoreerrors': False,
        'no_warnings': True,
    }
    info_dict = None
    last_error = None
    for opts in build_ydl_option_variants(ydl_opts, normalized_url):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info_dict = ydl.extract_info(normalized_url, download=False)
                if info_dict:
                    break
        except Exception as e:
            last_error = e

    if not info_dict:
        if is_douyin_url(normalized_url):
            raise Exception(
                "抖音解析失败：公开接口和回退方案都不可用。"
                f"主方案错误: {douyin_primary_error}; 回退错误: {last_error}. "
                "可稍后重试或更换分享链接。"
            )
        raise Exception(f"解析失败：{last_error}")
        
        # 获取最佳缩略图
    thumbnails = info_dict.get('thumbnails', [])
    thumbnail = info_dict.get('thumbnail') or get_best_thumbnail(thumbnails)
    thumbnail = _youtube_avoid_maxres(_normalize_thumbnail_url(thumbnail or ""))
    # 封面可能有防盗链，统一走后端代理（相对路径）
    if thumbnail:
        thumbnail = "/api/thumbnail?src=" + urllib.parse.quote(thumbnail, safe="") + "&referer=" + urllib.parse.quote(normalized_url, safe="")
    
    # 时长（秒），前端自己格式化
    duration_seconds = info_dict.get('duration', 0) or 0
    
    # 整理视频信息
    video_info = {
        'title': info_dict.get('title', 'N/A'),
        'duration': duration_seconds,
        'uploader': info_dict.get('uploader', 'N/A'),
        'view_count': info_dict.get('view_count', 0),
        'thumbnail': thumbnail,
        'formats': []
    }
    
    # 处理可用格式
    formats = info_dict.get('formats', [])
    
    # 添加所有格式，包括视频和音频
    for fmt in formats:
        disp_bytes, disp_kind = _merged_display_size(fmt, float(duration_seconds))
        format_info = {
            'format_id': fmt.get('format_id'),
            'format_note': fmt.get('format_note', ''),
            'ext': fmt.get('ext'),
            'height': fmt.get('height', 0),
            'width': fmt.get('width', 0),
            'filesize': fmt.get('filesize') or 0,
            'display_size_bytes': disp_bytes,
            'display_size_kind': disp_kind,
            'fps': fmt.get('fps', 0),
            'vcodec': fmt.get('vcodec', ''),
            'acodec': fmt.get('acodec', ''),
            'is_video_only': fmt.get('vcodec') and fmt.get('vcodec') != 'none' and (not fmt.get('acodec') or fmt.get('acodec') == 'none'),
            'is_audio_only': fmt.get('acodec') and fmt.get('acodec') != 'none' and (not fmt.get('vcodec') or fmt.get('vcodec') == 'none')
        }
        video_info['formats'].append(format_info)
    
    return video_info


def download_video(url: str, format_id: str, *, allow_ultra_hd: bool = False) -> Dict:
    """下载视频，自动合并音视频。allow_ultra_hd 为 False 时禁止下载 4K/超清档位。"""
    try:
        normalized_url = normalize_input_to_url(url)
        if not normalized_url:
            raise Exception("请输入有效的视频URL")
        if is_douyin_url(normalized_url) and format_id == "douyin_nowm":
            try:
                return download_douyin_video(normalized_url, temp_dir)
            except Exception:
                # 直链方案失败时，继续走 yt-dlp 回退下载
                pass

        # 确保临时目录存在
        os.makedirs(temp_dir, exist_ok=True)
        
        # 生成临时文件名
        temp_file = os.path.join(temp_dir, f"video_{os.urandom(8).hex()}")
        
        # 先提取视频信息，了解所选格式的类型
        ydl_info_opts = {
            'simulate': True,
            'noplaylist': True,
            'quiet': True,
            'skip_download': True,
        }
        
        info_dict = None
        formats = []
        last_error = None
        for opts in build_ydl_option_variants(ydl_info_opts, normalized_url):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info_dict = ydl.extract_info(normalized_url, download=False)
                    if info_dict:
                        formats = info_dict.get('formats', [])
                        break
            except Exception as e:
                last_error = e
        if not info_dict:
            raise Exception(f"解析下载格式失败: {last_error}")

        # 查找所选格式的详细信息
        selected_format = None
        for fmt in formats:
            if fmt.get('format_id') == format_id:
                selected_format = fmt
                break

        if selected_format and _format_is_ultra_hd(selected_format) and not allow_ultra_hd:
            raise Exception("该清晰度为 Pro 专享，请升级后下载。")

        # 确定是否需要合并音频
        if selected_format:
            vcodec = selected_format.get('vcodec', '')
            acodec = selected_format.get('acodec', '')
            is_video_only = bool(vcodec) and vcodec != 'none' and (not acodec or acodec == 'none')
            is_audio_only = bool(acodec) and acodec != 'none' and (not vcodec or vcodec == 'none')
        else:
            is_video_only = False
            is_audio_only = False
        
        # 构建下载格式字符串
        if is_video_only:
            # 纯视频格式，强制带上音频流（由 yt-dlp/ffmpeg 合并）
            download_format = f'{format_id}+bestaudio'
        elif is_audio_only:
            # 纯音频格式，直接下载
            download_format = format_id
        else:
            # 混合格式或未知情况
            download_format = format_id
        
        # 下载选项
        ydl_opts = {
            'format': download_format,
            'outtmpl': temp_file + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            # 如果合并失败也忽略，会导致“只有视频没有声音”，这里改为直接报错。
            'ignoreerrors': False,
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'playlistend': 1,
        }
        download_ydl_opts_candidates = build_ydl_option_variants(ydl_opts, normalized_url)
        
        # 实际下载视频
        def _has_audio_stream(file_path: str) -> Optional[bool]:
            """用 ffprobe 检测是否包含音频流。返回 None 表示 ffprobe 不可用。"""
            try:
                p = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-select_streams",
                        "a:0",
                        "-show_entries",
                        "stream=codec_type",
                        "-of",
                        "json",
                        file_path,
                    ],
                    capture_output=True,
                    text=True,
                )
                if p.returncode != 0:
                    return False
                data = json.loads(p.stdout or "{}")
                streams = data.get("streams") or []
                return len(streams) > 0
            except FileNotFoundError:
                return None

        def _pick_output_file(prefix: str) -> str:
            # yt-dlp 的 prepare_filename 在“带 + 合并”时不一定指向最终产物，
            # 这里按临时目录里实际产出的文件挑一个最可能的。
            import glob
            files = glob.glob(prefix + ".*")
            if not files:
                return ""
            mp4s = [f for f in files if f.lower().endswith(".mp4")]
            candidates = mp4s or files
            return max(candidates, key=lambda f: os.path.getsize(f))

        def _download_with_format(download_format: str, outtmpl_prefix: str) -> tuple[Dict, str]:
            last_err_local = None
            for base_opt in download_ydl_opts_candidates:
                try:
                    ydl_opts_local = dict(base_opt)
                    ydl_opts_local["format"] = download_format
                    ydl_opts_local["outtmpl"] = outtmpl_prefix + ".%(ext)s"
                    with yt_dlp.YoutubeDL(ydl_opts_local) as ydl:
                        info_dict_local = ydl.extract_info(normalized_url, download=True)
                        if not info_dict_local:
                            continue
                        output_file_local = _pick_output_file(outtmpl_prefix) or ydl.prepare_filename(info_dict_local)
                        return info_dict_local, output_file_local
                except Exception as ex:
                    last_err_local = ex
            raise Exception(f"无法获取视频信息: {last_err_local}")

        info_dict = None
        output_file = ""
        try:
            info_dict, output_file = _download_with_format(download_format, temp_file)

            audio_check = _has_audio_stream(output_file) if output_file else None
            if is_video_only and audio_check is False:
                # 只重试一次，避免重复下载太多。
                retry_temp_file = os.path.join(temp_dir, f"video_{os.urandom(8).hex()}")
                info_dict, output_file = _download_with_format(
                    f"{format_id}+bestaudio/best",
                    retry_temp_file,
                )
                audio_check = _has_audio_stream(output_file) if output_file else None

            if is_video_only and audio_check is False:
                raise Exception("下载完成但未检测到音频流：请确认系统已安装并能被 yt-dlp/ffmpeg 使用 ffmpeg。")

            if not output_file or not os.path.exists(output_file):
                raise Exception("下载失败：找不到下载的文件")

            return {
                "title": info_dict.get("title") if info_dict else None,
                "file_path": output_file,
                "file_size": os.path.getsize(output_file),
                "ext": os.path.splitext(output_file)[1][1:],
            }
        except Exception as ex:
            # 抖音在某些 Windows 环境下走 yt-dlp 分片/合并时会偶发 EINVAL，
            # 自动回退到抖音直链下载，避免用户卡死在“Invalid argument”。
            if is_douyin_url(normalized_url) and _is_invalid_argument_error(ex):
                try:
                    return download_douyin_video(normalized_url, temp_dir)
                except Exception:
                    pass
            raise
    except Exception as e:
        raise Exception(format_user_ytdlp_error(e))

import yt_dlp
import os
import tempfile
import json
import subprocess
from typing import Optional, List, Dict
import urllib.parse
import re

# 确保临时目录存在
temp_dir = os.path.join(os.getcwd(), 'temp')
os.makedirs(temp_dir, exist_ok=True)
cookie_file_path = os.path.join(temp_dir, "cookies.txt")


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
    
    # 优先选择有 width 和 height 的缩略图
    valid_thumbnails = [t for t in thumbnails if t.get('width') and t.get('height')]
    if not valid_thumbnails:
        # 如果没有尺寸信息，返回第一个有 URL 的缩略图
        for t in thumbnails:
            url = _get_url(t)
            if url:
                return url
        return ''
    
    # 选择分辨率最高的缩略图
    best = max(valid_thumbnails, key=lambda t: t['width'] * t['height'])
    return _get_url(best)


def check_ffmpeg_available() -> bool:
    """检查 FFmpeg 是否可用"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=False)
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def extract_video_info(url: str) -> Dict:
    """提取视频信息"""
    def _normalize_input_to_url(s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        if re.match(r"^https?://", s, flags=re.IGNORECASE):
            return s
        m = re.search(r"(https?://[^\s\"'<>]+)", s, flags=re.IGNORECASE)
        if m:
            return m.group(1).rstrip(").,;]}>\"'")
        m2 = re.search(r"\b(v\.douyin\.com/[A-Za-z0-9]+)\b", s, flags=re.IGNORECASE)
        if m2:
            return "https://" + m2.group(1)
        return ""

    normalized_url = _normalize_input_to_url(url)
    if not normalized_url:
        raise Exception("请输入有效的视频URL（抖音请粘贴包含 https://v.douyin.com/... 的分享链接，而不是口令文案）")

    ydl_opts = {
        'noplaylist': True,
        'quiet': True,
        'skip_download': True,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'playlistend': 1,
        'ignoreerrors': False,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        },
    }
    if os.path.exists(cookie_file_path):
        ydl_opts["cookiefile"] = cookie_file_path
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(normalized_url, download=False)
        if not info_dict:
            raise Exception("解析失败：未获取到视频信息（可能链接无效或平台限制）")
        
        # 获取最佳缩略图
        thumbnails = info_dict.get('thumbnails', [])
        thumbnail = info_dict.get('thumbnail') or get_best_thumbnail(thumbnails)
        # 某些页面以 https/file scheme 打开时会拒绝 http 图片
        if thumbnail and thumbnail.startswith("http://"):
            thumbnail = thumbnail.replace("http://", "https://", 1)
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
            format_info = {
                'format_id': fmt.get('format_id'),
                'format_note': fmt.get('format_note', ''),
                'ext': fmt.get('ext'),
                'height': fmt.get('height', 0),
                'width': fmt.get('width', 0),
                'filesize': fmt.get('filesize', 0),
                'fps': fmt.get('fps', 0),
                'vcodec': fmt.get('vcodec', ''),
                'acodec': fmt.get('acodec', ''),
                'is_video_only': fmt.get('vcodec') and fmt.get('vcodec') != 'none' and (not fmt.get('acodec') or fmt.get('acodec') == 'none'),
                'is_audio_only': fmt.get('acodec') and fmt.get('acodec') != 'none' and (not fmt.get('vcodec') or fmt.get('vcodec') == 'none')
            }
            video_info['formats'].append(format_info)
        
        return video_info


def download_video(url: str, format_id: str) -> Dict:
    """下载视频，自动合并音视频"""
    try:
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
        if os.path.exists(cookie_file_path):
            ydl_info_opts["cookiefile"] = cookie_file_path
        
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            formats = info_dict.get('formats', [])
            
            # 查找所选格式的详细信息
            selected_format = None
            for fmt in formats:
                if fmt.get('format_id') == format_id:
                    selected_format = fmt
                    break
            
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
        if os.path.exists(cookie_file_path):
            ydl_opts["cookiefile"] = cookie_file_path
        
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
            import glob
            files = glob.glob(prefix + ".*")
            if not files:
                return ""
            mp4s = [f for f in files if f.lower().endswith(".mp4")]
            candidates = mp4s or files
            return max(candidates, key=lambda f: os.path.getsize(f))

        def _download_with_format(download_format: str, outtmpl_prefix: str) -> tuple[Dict, str]:
            ydl_opts_local = dict(ydl_opts)
            ydl_opts_local["format"] = download_format
            ydl_opts_local["outtmpl"] = outtmpl_prefix + ".%(ext)s"
            with yt_dlp.YoutubeDL(ydl_opts_local) as ydl:
                info_dict_local = ydl.extract_info(url, download=True)
                if not info_dict_local:
                    raise Exception("无法获取视频信息")
                output_file_local = _pick_output_file(outtmpl_prefix) or ydl.prepare_filename(info_dict_local)
                return info_dict_local, output_file_local

        info_dict = None
        output_file = ""
        info_dict, output_file = _download_with_format(download_format, temp_file)

        audio_check = _has_audio_stream(output_file) if output_file else None
        if is_video_only and audio_check is False:
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
    except Exception as e:
        raise Exception(f"下载失败: {str(e)}")
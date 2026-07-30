from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Callable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YT_DLP = Path(r"D:\GitProject\yt-dlp\yt-dlp.exe")
DEFAULT_DOUYIN_ROOT = Path(r"D:\GitProject\douyin-downloader")
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING_PUNCTUATION = ".,;:!?，。；：！？、）》】」』}"

PLATFORM_DOMAINS = {
    "douyin": ("douyin.com", "iesdouyin.com"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be"),
    "tiktok": ("tiktok.com",),
}


class LinkImportError(RuntimeError):
    pass


class LinkImportCancelled(LinkImportError):
    pass


@dataclass
class ResolvedVideo:
    input_url: str
    canonical_url: str
    platform: str
    source_id: str
    title: str
    filename: str
    download_data: dict = field(default_factory=dict, repr=False)


def extract_video_url(text: str) -> str:
    value = (text or "").strip()
    if not value:
        raise LinkImportError("请输入视频链接或分享文本")
    match = URL_RE.search(value)
    if not match:
        raise LinkImportError("没有找到 http 或 https 视频链接")
    url = match.group(0).rstrip(TRAILING_PUNCTUATION)
    if len(url) > 4096:
        raise LinkImportError("链接过长")
    return url


def identify_platform(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LinkImportError("只支持有效的 http 或 https 链接")
    if parsed.username or parsed.password:
        raise LinkImportError("链接中不能包含用户名或密码")

    hostname = parsed.hostname.lower().rstrip(".")
    for platform, domains in PLATFORM_DOMAINS.items():
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
            return platform
    raise LinkImportError("暂不支持该网站；目前支持抖音、Bilibili、YouTube 和 TikTok")


def resolve_video(
    text: str,
    progress: Callable[[int, str], None],
    should_cancel: Callable[[], bool],
) -> ResolvedVideo:
    url = extract_video_url(text)
    platform = identify_platform(url)
    progress(10, f"已识别链接：{platform_label(platform)}")
    if platform == "douyin":
        return _resolve_douyin(url, progress, should_cancel)
    return _resolve_ytdlp(url, platform, progress, should_cancel)


def download_video(
    resolved: ResolvedVideo,
    output_dir: Path,
    progress: Callable[[int, str], None],
    should_cancel: Callable[[], bool],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    progress(38, "正在下载视频")
    if resolved.platform == "douyin":
        path = _download_douyin(resolved, output_dir, should_cancel)
    else:
        path = _download_ytdlp(resolved, output_dir, should_cancel)
    if not path.exists() or not path.is_file():
        raise LinkImportError("下载完成后未找到视频文件")
    progress(86, "视频下载完成，正在写入本地历史")
    return path


def platform_label(platform: str) -> str:
    return {
        "douyin": "抖音",
        "bilibili": "Bilibili",
        "youtube": "YouTube",
        "tiktok": "TikTok",
    }.get(platform, platform)


def _resolve_douyin(
    url: str,
    progress: Callable[[int, str], None],
    should_cancel: Callable[[], bool],
) -> ResolvedVideo:
    douyin_root = Path(os.environ.get("VIDEO_TRANSCRIBER_DOUYIN_ROOT", DEFAULT_DOUYIN_ROOT))
    python = douyin_root / ".venv" / "Scripts" / "python.exe"
    resolver = douyin_root / "tools" / "resolve_play_url.py"
    config = douyin_root / "config.local.yml"
    _require_files(
        (python, "抖音解析器的 Python 环境"),
        (resolver, "抖音解析脚本"),
        (config, "抖音本地配置"),
    )
    progress(22, "正在解析抖音视频信息")
    output = _run_process(
        [str(python), str(resolver), "-c", str(config), url],
        should_cancel,
        timeout=120,
        error_prefix="抖音链接解析失败",
    )
    try:
        data = json.loads(output.strip().splitlines()[-1])
        source_id = str(data["aweme_id"])
        filename = Path(str(data["filename"])).name
        media_url = str(data["media_url"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise LinkImportError("抖音解析器返回了无法识别的数据") from exc

    progress(30, "已解析抖音视频信息")
    return ResolvedVideo(
        input_url=url,
        canonical_url=f"https://www.douyin.com/video/{source_id}",
        platform="douyin",
        source_id=source_id,
        title=str(data.get("title") or source_id),
        filename=filename,
        download_data={"media_url": media_url, "headers": data.get("headers") or {}},
    )


def _resolve_ytdlp(
    url: str,
    platform: str,
    progress: Callable[[int, str], None],
    should_cancel: Callable[[], bool],
) -> ResolvedVideo:
    yt_dlp = Path(os.environ.get("VIDEO_TRANSCRIBER_YT_DLP", DEFAULT_YT_DLP))
    _require_files((yt_dlp, "yt-dlp"))
    progress(22, f"正在解析{platform_label(platform)}视频信息")
    output = _run_process(
        [
            str(yt_dlp),
            "--no-playlist",
            "--skip-download",
            "--dump-single-json",
            "--no-warnings",
            url,
        ],
        should_cancel,
        timeout=180,
        error_prefix=f"{platform_label(platform)}链接解析失败",
    )
    try:
        data = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise LinkImportError("视频解析器返回了无法识别的数据") from exc
    if data.get("_type") == "playlist":
        raise LinkImportError("暂不支持播放列表，请输入单个视频链接")

    source_id = str(data.get("id") or "").strip()
    if not source_id:
        raise LinkImportError("无法取得视频 ID")
    title = str(data.get("title") or source_id)
    extension = str(data.get("ext") or "mp4")
    progress(30, f"已解析{platform_label(platform)}视频信息")
    return ResolvedVideo(
        input_url=url,
        canonical_url=str(data.get("webpage_url") or url),
        platform=platform,
        source_id=source_id,
        title=title,
        filename=f"{title} [{source_id}].{extension}",
    )


def _download_douyin(
    resolved: ResolvedVideo,
    output_dir: Path,
    should_cancel: Callable[[], bool],
) -> Path:
    target = output_dir / Path(resolved.filename).name
    temporary = target.with_name(f"{target.name}.part")
    headers = resolved.download_data.get("headers") or {}
    args = [
        "curl.exe",
        "-L",
        "--noproxy",
        "*",
        "--retry",
        "5",
        "--retry-delay",
        "2",
        "--retry-all-errors",
        "--connect-timeout",
        "20",
        "--max-time",
        "1200",
        "--silent",
        "--show-error",
    ]
    user_agent = headers.get("User-Agent")
    if user_agent:
        args.extend(["-A", str(user_agent)])
    args.extend(
        [
            "-e",
            "https://www.douyin.com/",
            "-H",
            "Origin: https://www.douyin.com",
            "-o",
            str(temporary),
            str(resolved.download_data["media_url"]),
        ]
    )
    try:
        _run_process(args, should_cancel, timeout=1250, error_prefix="抖音视频下载失败")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _download_ytdlp(
    resolved: ResolvedVideo,
    output_dir: Path,
    should_cancel: Callable[[], bool],
) -> Path:
    yt_dlp = Path(os.environ.get("VIDEO_TRANSCRIBER_YT_DLP", DEFAULT_YT_DLP))
    output = _run_process(
        [
            str(yt_dlp),
            "--no-playlist",
            "-P",
            str(output_dir),
            "-o",
            "%(title).120B [%(id)s].%(ext)s",
            "--print",
            "after_move:result:%(filepath)s",
            resolved.canonical_url,
        ],
        should_cancel,
        timeout=3600,
        error_prefix=f"{platform_label(resolved.platform)}视频下载失败",
    )
    result_lines = [line[7:] for line in output.splitlines() if line.startswith("result:")]
    if result_lines:
        result = Path(result_lines[-1].strip())
        if result.exists():
            return result

    candidates = [
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.suffix.lower() not in {".part", ".ytdl", ".temp"}
    ]
    if len(candidates) != 1:
        raise LinkImportError("下载完成后无法确定最终视频文件")
    return candidates[0]


def _run_process(
    args: list[str],
    should_cancel: Callable[[], bool],
    *,
    timeout: int,
    error_prefix: str,
) -> str:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process_env = os.environ.copy()
    process_env["PYTHONIOENCODING"] = "utf-8"
    process_env["PYTHONUTF8"] = "1"
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
            env=process_env,
        )
    except OSError as exc:
        raise LinkImportError(f"{error_prefix}：无法启动本地下载工具") from exc

    deadline = time.monotonic() + timeout
    while True:
        try:
            output, _ = process.communicate(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            if should_cancel():
                _stop_process(process)
                raise LinkImportCancelled("已终止链接导入")
            if time.monotonic() >= deadline:
                _stop_process(process)
                raise LinkImportError(f"{error_prefix}：等待超时")

    if process.returncode != 0:
        detail = _safe_error_detail(output)
        suffix = f"：{detail}" if detail else ""
        raise LinkImportError(f"{error_prefix}{suffix}")
    return output


def _stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _safe_error_detail(output: str) -> str:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if not lines:
        return ""
    detail = lines[-1]
    detail = re.sub(r"https?://\S+", "[链接已隐藏]", detail)
    return detail[:300]


def _require_files(*items: tuple[Path, str]) -> None:
    for path, label in items:
        if not path.is_file():
            raise LinkImportError(f"未找到{label}：{path}")

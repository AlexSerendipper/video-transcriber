from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app import link_importer


class LinkImporterTests(unittest.TestCase):
    def test_extracts_url_from_share_text_and_removes_chinese_punctuation(self) -> None:
        text = "复制这段内容打开抖音 https://v.douyin.com/abc123/。"

        self.assertEqual(link_importer.extract_video_url(text), "https://v.douyin.com/abc123/")

    def test_identifies_supported_platform_subdomains(self) -> None:
        cases = {
            "https://v.douyin.com/abc/": "douyin",
            "https://www.bilibili.com/video/BV123": "bilibili",
            "https://youtu.be/abc": "youtube",
            "https://www.tiktok.com/@name/video/123": "tiktok",
        }

        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(link_importer.identify_platform(url), expected)

    def test_rejects_lookalike_and_local_hosts(self) -> None:
        invalid_urls = [
            "https://douyin.com.example.test/video/1",
            "http://127.0.0.1/video.mp4",
            "file:///D:/video.mp4",
        ]

        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(link_importer.LinkImportError):
                link_importer.identify_platform(url)

    def test_ytdlp_resolution_returns_stable_source_identity(self) -> None:
        info = {
            "id": "BV1test",
            "title": "示例视频",
            "ext": "mp4",
            "webpage_url": "https://www.bilibili.com/video/BV1test",
        }
        progress_events: list[tuple[int, str]] = []

        with (
            patch.object(link_importer, "_require_files"),
            patch.object(link_importer, "_run_process", return_value=json.dumps(info, ensure_ascii=False)),
        ):
            resolved = link_importer.resolve_video(
                "分享链接：https://www.bilibili.com/video/BV1test",
                lambda value, message: progress_events.append((value, message)),
                lambda: False,
            )

        self.assertEqual(resolved.platform, "bilibili")
        self.assertEqual(resolved.source_id, "BV1test")
        self.assertEqual(resolved.canonical_url, info["webpage_url"])
        self.assertTrue(progress_events)

    def test_ytdlp_download_uses_reported_final_path(self) -> None:
        resolved = link_importer.ResolvedVideo(
            input_url="https://youtu.be/example",
            canonical_url="https://www.youtube.com/watch?v=example",
            platform="youtube",
            source_id="example",
            title="Example",
            filename="Example [example].mp4",
        )
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            final_path = output_dir / "Example [example].mp4"
            final_path.write_bytes(b"video")
            with patch.object(link_importer, "_run_process", return_value=f"result:{final_path}\n"):
                result = link_importer.download_video(
                    resolved,
                    output_dir,
                    lambda _value, _message: None,
                    lambda: False,
                )

        self.assertEqual(result, final_path)

    def test_subprocess_forces_utf8_for_child_python_output(self) -> None:
        process = MagicMock()
        process.communicate.return_value = ("中文标题", None)
        process.returncode = 0

        with patch.object(link_importer.subprocess, "Popen", return_value=process) as popen:
            output = link_importer._run_process(
                ["resolver.exe"],
                lambda: False,
                timeout=1,
                error_prefix="解析失败",
            )

        self.assertEqual(output, "中文标题")
        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(environment["PYTHONUTF8"], "1")


if __name__ == "__main__":
    unittest.main()

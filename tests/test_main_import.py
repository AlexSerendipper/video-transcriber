from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import main


class SaveImportedFileTests(unittest.TestCase):
    def test_link_reimport_refreshes_existing_history_title_and_source(self) -> None:
        existing = {
            "hash": "same-hash",
            "video_name": "A���.mp4",
            "source_file": "source.mp4",
            "status": "done",
            "segments": [],
        }
        source_details = {
            "source_type": "url",
            "source_platform": "douyin",
            "source_id": "123",
            "source_title": "A股市场指数体系",
        }

        with tempfile.TemporaryDirectory() as directory:
            downloaded = Path(directory) / "download.mp4"
            downloaded.write_bytes(b"same video")
            with (
                patch.object(main, "read_metadata", return_value=existing),
                patch.object(main, "write_metadata") as write_metadata,
                patch.object(main, "activate_record") as activate_record,
            ):
                result = main.save_imported_file(
                    downloaded,
                    "same-hash",
                    "A股市场指数体系.mp4",
                    source_details=source_details,
                )

        self.assertTrue(result["exists"])
        self.assertFalse(downloaded.exists())
        saved = write_metadata.call_args.args[1]
        self.assertEqual(saved["video_name"], "A股市场指数体系.mp4")
        self.assertEqual(saved["source_platform"], "douyin")
        self.assertEqual(saved["source_title"], "A股市场指数体系")
        activate_record.assert_called_once()


if __name__ == "__main__":
    unittest.main()

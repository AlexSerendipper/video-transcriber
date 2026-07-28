from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import hashlib
import json
import shutil
import threading
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .transcriber import TranscriptionCancelled, transcribe_video


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
TEMP_DIR = ROOT / "temp"
DATA_DIR = ROOT / "data"
ITEMS_DIR = DATA_DIR / "items"
TEMP_DIR.mkdir(exist_ok=True)
ITEMS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Local Video Transcriber")
API_VERSION = 2

state_lock = threading.Lock()
cancel_events: dict[str, threading.Event] = {}
ACTIVE_STATUSES = {"queued", "running", "cancelling"}
current_task: dict = {
    "id": None,
    "hash": None,
    "status": "idle",
    "progress": 0,
    "message": "等待导入视频",
    "video_path": None,
    "video_name": None,
    "segments": [],
    "duration": 0,
    "error": None,
    "engine": None,
    "fallback_reason": None,
}


def item_dir(file_hash: str) -> Path:
    return ITEMS_DIR / file_hash


def metadata_path(file_hash: str) -> Path:
    return item_dir(file_hash) / "result.json"


def source_path(file_hash: str, suffix: str) -> Path:
    return item_dir(file_hash) / f"source{suffix or '.mp4'}"


def read_metadata(file_hash: str) -> dict | None:
    path = metadata_path(file_hash)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_metadata(file_hash: str, data: dict) -> None:
    path = metadata_path(file_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_state(**updates: object) -> None:
    with state_lock:
        current_task.update(updates)


def snapshot() -> dict:
    with state_lock:
        data = dict(current_task)
    data["video_path"] = str(data["video_path"]) if data.get("video_path") else None
    return data


def metadata_status(metadata: dict) -> str:
    status = metadata.get("status")
    if status in {"done", "untranscribed"}:
        return status
    return "done" if "segments" in metadata else "untranscribed"


def ensure_task_idle() -> None:
    if snapshot().get("status") in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="当前正在转写，请先等待完成或终止任务")


def activate_record(file_hash: str, metadata: dict, message: str = "已打开历史记录") -> None:
    video_path = item_dir(file_hash) / metadata["source_file"]
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="历史视频副本不存在")
    status = metadata_status(metadata)
    set_state(
        id=None,
        hash=file_hash,
        status=status,
        progress=100 if status == "done" else 0,
        message=message,
        video_path=video_path,
        video_name=metadata["video_name"],
        segments=metadata.get("segments", []),
        duration=metadata.get("duration", 0),
        error=None,
        engine=None,
        fallback_reason=None,
    )


def hash_and_save_upload(upload: UploadFile, target: Path) -> str:
    digest = hashlib.sha256()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as output:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


@app.post("/api/import")
async def import_video(file: UploadFile = File(...)) -> dict:
    ensure_task_idle()
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择视频文件")

    upload_id = uuid.uuid4().hex
    suffix = Path(file.filename).suffix or ".mp4"
    temp_path = TEMP_DIR / f"upload_{upload_id}{suffix}"
    file_hash = hash_and_save_upload(file, temp_path)
    existing = read_metadata(file_hash)

    if existing:
        temp_path.unlink(missing_ok=True)
        activate_record(file_hash, existing, "已打开已有视频")
        return {
            "exists": True,
            "hash": file_hash,
            "item": history_summary(existing),
        }

    destination = source_path(file_hash, suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temp_path), destination)
    metadata = {
        "hash": file_hash,
        "video_name": file.filename,
        "source_file": destination.name,
        "duration": 0,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "untranscribed",
        "segments": [],
    }
    write_metadata(file_hash, metadata)
    activate_record(file_hash, metadata, "视频已导入，尚未转写")
    return {
        "exists": False,
        "hash": file_hash,
        "item": history_summary(metadata),
    }


@app.post("/api/history/{file_hash}/transcribe")
def transcribe_imported(file_hash: str, preset: str = Form("balanced")) -> dict:
    ensure_task_idle()
    metadata = read_metadata(file_hash)
    if not metadata:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    video_path = item_dir(file_hash) / metadata["source_file"]
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="历史视频副本不存在")
    metadata["status"] = "untranscribed"
    metadata["segments"] = []
    write_metadata(file_hash, metadata)
    return start_transcription_task(file_hash, video_path, metadata, preset)


def start_transcription_task(
    file_hash: str,
    video_path: Path,
    metadata: dict,
    preset: str,
) -> dict:
    task_id = uuid.uuid4().hex

    set_state(
        id=task_id,
        hash=file_hash,
        status="queued",
        progress=3,
        message="正在准备转写",
        video_path=video_path,
        video_name=metadata["video_name"],
        segments=[],
        duration=metadata.get("duration", 0),
        error=None,
        engine=None,
        fallback_reason=None,
    )

    cancel_events[task_id] = threading.Event()
    worker = threading.Thread(
        target=run_task,
        args=(task_id, file_hash, video_path, metadata["video_name"], preset),
        daemon=True,
    )
    worker.start()
    return {"task_id": task_id, "hash": file_hash}


def run_task(task_id: str, file_hash: str, video_path: Path, video_name: str, preset: str) -> None:
    cancel_event = cancel_events.get(task_id)

    def progress(value: int, message: str, **fields: object) -> None:
        if snapshot().get("id") == task_id:
            set_state(status="running", progress=value, message=message, **fields)

    def should_cancel() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    try:
        blocks = transcribe_video(video_path, preset, progress, should_cancel=should_cancel)
        segments = [asdict(block) for block in blocks]
        duration = round(max((segment["end"] for segment in segments), default=0), 2)
        previous = read_metadata(file_hash) or {}
        metadata = {
            "hash": file_hash,
            "video_name": video_name,
            "source_file": video_path.name,
            "duration": duration,
            "created_at": previous.get("created_at") or datetime.now().isoformat(timespec="seconds"),
            "transcribed_at": datetime.now().isoformat(timespec="seconds"),
            "status": "done",
            "segments": segments,
        }
        write_metadata(file_hash, metadata)
        if snapshot().get("id") == task_id:
            set_state(
                id=None,
                status="done",
                progress=100,
                message="完成",
                video_path=video_path,
                video_name=video_name,
                segments=segments,
                duration=duration,
                error=None,
            )
    except TranscriptionCancelled:
        metadata = read_metadata(file_hash) or {
            "hash": file_hash,
            "video_name": video_name,
            "source_file": video_path.name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        metadata.update(status="untranscribed", segments=[])
        write_metadata(file_hash, metadata)
        if snapshot().get("id") == task_id:
            set_state(
                id=None,
                hash=file_hash,
                status="untranscribed",
                progress=0,
                message="已终止转写，视频已保留",
                video_path=video_path,
                video_name=video_name,
                segments=[],
                duration=metadata.get("duration", 0),
                error=None,
                engine=None,
                fallback_reason=None,
            )
    except Exception as exc:
        metadata = read_metadata(file_hash) or {
            "hash": file_hash,
            "video_name": video_name,
            "source_file": video_path.name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        metadata.update(status="untranscribed", segments=[])
        write_metadata(file_hash, metadata)
        if snapshot().get("id") == task_id:
            set_state(
                id=None,
                status="untranscribed",
                progress=0,
                message="转写失败，视频已保留",
                video_path=video_path,
                video_name=video_name,
                segments=[],
                duration=metadata.get("duration", 0),
                error=str(exc),
                engine=None,
                fallback_reason=None,
            )
    finally:
        cancel_events.pop(task_id, None)


@app.post("/api/cancel")
def cancel_task() -> dict:
    data = snapshot()
    task_id = data.get("id")
    if not task_id or data.get("status") not in {"queued", "running"}:
        return {"ok": False, "message": "当前没有正在转写的任务"}

    event = cancel_events.get(task_id)
    if event:
        event.set()
    set_state(status="cancelling", message="正在终止，当前片段结束后会停止")
    return {"ok": True}


@app.get("/api/status")
def status() -> dict:
    data = snapshot()
    return {
        "api_version": API_VERSION,
        "id": data["id"],
        "hash": data["hash"],
        "status": data["status"],
        "progress": data["progress"],
        "message": data["message"],
        "video_name": data["video_name"],
        "duration": data["duration"],
        "error": data["error"],
        "engine": data["engine"],
        "fallback_reason": data["fallback_reason"],
        "segment_count": len(data["segments"]),
    }


@app.get("/api/result")
def result() -> dict:
    data = snapshot()
    if data["status"] != "done":
        raise HTTPException(status_code=409, detail="转写尚未完成")
    return {
        "hash": data["hash"],
        "video_name": data["video_name"],
        "duration": data["duration"],
        "segments": data["segments"],
        "text": "\n\n".join(segment["text"] for segment in data["segments"]),
    }


@app.get("/api/video")
def video() -> FileResponse:
    data = snapshot()
    video_path = data.get("video_path")
    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=404, detail="当前没有可播放的视频")
    return FileResponse(video_path)


@app.get("/api/history")
def history() -> dict:
    items = []
    for path in sorted(ITEMS_DIR.glob("*/result.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        items.append(history_summary(metadata))

    data = snapshot()
    if data.get("status") in ACTIVE_STATUSES and data.get("hash"):
        matched = False
        for item in items:
            if item["hash"] == data["hash"]:
                item["status"] = data.get("status")
                item["video_name"] = data.get("video_name") or item["video_name"]
                matched = True
                break
        if not matched:
            items.insert(
                0,
                {
                    "hash": data["hash"],
                    "video_name": data.get("video_name") or "正在转写",
                    "duration": data.get("duration", 0),
                    "created_at": None,
                    "status": data.get("status"),
                },
            )
    return {"items": items}


@app.post("/api/history/{file_hash}/open")
def open_history(file_hash: str) -> dict:
    ensure_task_idle()
    metadata = read_metadata(file_hash)
    if not metadata:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    activate_record(file_hash, metadata)
    return {"ok": True, "item": history_summary(metadata)}


@app.delete("/api/history/{file_hash}")
def delete_history(file_hash: str) -> dict:
    ensure_task_idle()
    target = item_dir(file_hash)
    if not target.exists():
        raise HTTPException(status_code=404, detail="历史记录不存在")

    shutil.rmtree(target)
    if snapshot().get("hash") == file_hash:
        set_state(
            id=None,
            hash=None,
            status="idle",
            progress=0,
            message="等待导入视频",
            video_path=None,
            video_name=None,
            segments=[],
            duration=0,
            error=None,
            engine=None,
            fallback_reason=None,
        )
    return {"ok": True}


def history_summary(metadata: dict) -> dict:
    return {
        "hash": metadata["hash"],
        "video_name": metadata["video_name"],
        "duration": metadata.get("duration", 0),
        "created_at": metadata.get("created_at"),
        "status": metadata_status(metadata),
    }


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

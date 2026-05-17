from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading
import time

from .cuda_dll import add_cuda_dll_directories

add_cuda_dll_directories()

from faster_whisper import WhisperModel
from opencc import OpenCC

from .punctuation import restore_punctuation_blocks
from .segmenter import RawSegment, TextBlock, merge_segments


OPENCC = OpenCC("t2s")

MODEL_PRESETS = {
    "fast": {
        "model": "small",
        "device": "cuda",
        "compute_type": "int8_float16",
        "beam_size": 1,
    },
    "balanced": {
        "model": "medium",
        "device": "cuda",
        "compute_type": "float16",
        "beam_size": 3,
    },
    "accurate": {
        "model": "large-v3",
        "device": "cuda",
        "compute_type": "float16",
        "beam_size": 5,
    },
}

_model_lock = threading.Lock()
_model_cache: dict[tuple[str, str, str], WhisperModel] = {}


def transcribe_video(
    video_path: Path,
    preset: str,
    progress: Callable[..., None],
    should_cancel: Callable[[], bool] | None = None,
) -> list[TextBlock]:
    config = MODEL_PRESETS.get(preset, MODEL_PRESETS["balanced"])
    progress(8, "Loading speech model")

    try:
        return _run_transcription(video_path, progress, should_cancel=should_cancel, **config)
    except Exception as exc:
        if config["device"] != "cuda":
            raise
        progress(
            12,
            f"CUDA failed, falling back to CPU: {exc}",
            fallback_reason=str(exc),
        )
        cpu_config = {
            "model": config["model"],
            "device": "cpu",
            "compute_type": "int8",
            "beam_size": config["beam_size"],
        }
        return _run_transcription(
            video_path,
            progress,
            should_cancel=should_cancel,
            fallback_reason=str(exc),
            **cpu_config,
        )


def _get_model(model: str, device: str, compute_type: str) -> WhisperModel:
    key = (model, device, compute_type)
    with _model_lock:
        cached = _model_cache.get(key)
        if cached is None:
            cached = WhisperModel(model, device=device, compute_type=compute_type)
            _model_cache[key] = cached
        return cached


def _run_transcription(
    video_path: Path,
    progress: Callable[..., None],
    model: str,
    device: str,
    compute_type: str,
    beam_size: int,
    should_cancel: Callable[[], bool] | None = None,
    fallback_reason: str | None = None,
) -> list[TextBlock]:
    engine = f"{model} / {device} / {compute_type} / beam {beam_size}"
    whisper = _get_model(model, device, compute_type)
    progress(18, f"Transcribing with {engine}", engine=engine, fallback_reason=fallback_reason)
    started = time.time()

    segments_iter, info = whisper.transcribe(
        str(video_path),
        language="zh",
        vad_filter=True,
        beam_size=beam_size,
        condition_on_previous_text=True,
    )

    duration = max(float(info.duration or 0), 1.0)
    raw_segments: list[RawSegment] = []
    for segment in segments_iter:
        if should_cancel and should_cancel():
            raise TranscriptionCancelled()
        raw_segments.append(
            RawSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=OPENCC.convert(segment.text),
            )
        )
        percent = min(88, 18 + int((float(segment.end) / duration) * 68))
        progress(
            percent,
            f"Transcribing {format_seconds(segment.end)} / {format_seconds(duration)} | {engine}",
            engine=engine,
            fallback_reason=fallback_reason,
        )

    progress(92, "Merging transcript blocks")
    blocks = merge_segments(raw_segments)
    if should_cancel and should_cancel():
        raise TranscriptionCancelled()
    progress(94, "Restoring punctuation with Chinese punctuation model", engine=engine)
    blocks = restore_punctuation_blocks(blocks)
    elapsed = time.time() - started
    progress(98, f"Transcription finished in {format_seconds(elapsed)} | {engine}", engine=engine)
    return blocks


class TranscriptionCancelled(Exception):
    pass


def format_seconds(value: float) -> str:
    total = max(int(value), 0)
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"

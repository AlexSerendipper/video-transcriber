# Local Video Transcriber

A lightweight local web app for transcribing Chinese videos on your own Windows machine.

It is designed as a local alternative to uploading videos to meeting-note tools when the main workflow is:

- drag in a video
- transcribe speech to readable text
- click a transcript paragraph to jump to the matching video time
- copy all text or select partial text manually
- keep local history so the same file does not need to be transcribed again

## Features

- Local browser UI at `http://127.0.0.1:8000`
- Drag-and-drop video/audio upload
- `faster-whisper` transcription with model presets
- GPU acceleration via CUDA when available
- Clear engine status, including CPU fallback reason
- Chinese traditional-to-simplified conversion
- Chinese punctuation restoration with a FunASR CT-Transformer ONNX model
- Clickable transcript paragraphs with hidden timestamps
- Selectable transcript text for partial copy
- One-click full transcript copy
- Local history by file content hash
- Stored video copy + transcript result for history replay
- Duplicate upload detection
- Cancellable transcription jobs

## Requirements

- Windows
- Python 3.10+
- NVIDIA GPU recommended

The app installs Python dependencies into `.venv` on first run. CUDA runtime DLLs required by `ctranslate2` are installed through Python packages on Windows.

## Start

The easiest way on Windows is to double-click:

```text
Start Local Video Transcriber.cmd
```

Keep the startup window open while using the app. Closing that window stops the local server.

You can also start from PowerShell:

```powershell
cd D:\CodexProject\video-transcriber
.\run.ps1
```

If PowerShell blocks scripts on your machine, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

## Stop

If you started with `Start Local Video Transcriber.cmd`, close the startup window.

If you started from PowerShell with `.\run.ps1`, stop it by pressing:

```text
Ctrl + C
```

If the server is running in the background, stop the local `uvicorn` process:

```powershell
$procs = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like '*uvicorn*app.main:app*' -and $_.Name -like 'python*'
}
foreach ($p in $procs) {
  Stop-Process -Id $p.ProcessId -Force
}
```

## Model Presets

- Speed: `small / cuda / int8_float16 / beam 1`
- Balanced: `medium / cuda / float16 / beam 3`
- Accurate: `large-v3 / cuda / float16 / beam 5`

If CUDA cannot be loaded, the app falls back to CPU and displays the fallback reason in the progress area.

## Local Data

History is stored under:

```text
data/items/<file_hash>/
```

This directory contains local video copies and transcript JSON files. It is intentionally ignored by git.

## Do Not Commit

The following are local-only and ignored:

- `.venv/`
- `data/`
- `temp/`
- `server.log`
- `server.err.log`
- Python cache files

Do not commit local videos, transcripts, model caches, or environment files.

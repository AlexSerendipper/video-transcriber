# Local Video Transcriber

A local Windows web app for importing videos, playing them immediately, and generating readable Chinese transcripts without uploading media to a third-party service.

The core workflow is deliberately split into two steps:

1. Import a video. The app stores a local copy, adds it to history, and makes it playable immediately.
2. Start transcription when needed. Until then, the transcript panel shows `未转写`.

## Features

- Local browser UI at `http://127.0.0.1:8876`
- Separate video import and transcription actions
- Immediate playback after import
- Local history keyed by SHA-256 file content hash
- Duplicate import detection that reopens the existing record
- Collapsible overlay history drawer with filename search
- Persistent `未转写` and `已完成` history states
- `faster-whisper` transcription with speed, balanced, and accuracy presets
- GPU acceleration through CUDA when available, with automatic CPU fallback
- Chinese traditional-to-simplified conversion
- Chinese punctuation restoration with a FunASR CT-Transformer ONNX model
- Transcription progress and cancellation controls inside the transcript panel
- Cancellation and failure keep the imported video and return it to `未转写`
- Confirmed re-transcription for completed records
- Clickable transcript paragraphs that seek the video to the matching time
- Selectable transcript text for manual partial copy
- Restored active history item and per-video playback position after refresh
- Version-aware startup that replaces an outdated local backend before opening the page

## Requirements

- Windows
- Python 3.10+
- NVIDIA GPU recommended

Python dependencies are installed into `.venv` on first run. CUDA runtime DLLs required by `ctranslate2` are provided through Python packages on Windows.

## Start

The easiest option is to double-click:

```text
Local Video Transcriber.lnk
```

or:

```text
Start Local Video Transcriber.cmd
```

The browser opens automatically after the correct backend version is ready. Keep the startup window open while using the app when it was launched through the shortcut.

The shortcut calls `launch.ps1`, which waits for the expected API version and opens the browser. `launch.ps1` delegates environment setup and the Uvicorn process to `run.ps1`.

You can also start it from PowerShell:

```powershell
cd D:\CodexProject\video-transcriber
.\run.ps1
```

To install or update dependencies explicitly:

```powershell
.\run.ps1 -InstallDeps
```

If PowerShell blocks scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

The default address is:

```text
http://127.0.0.1:8876
```

To use another port:

```powershell
.\run.ps1 -Port 8766
```

## Usage

### Import a video

Click `导入视频` and select a supported video or audio file. Importing immediately:

- copies the media into local history;
- opens it in the player;
- creates a history entry with status `未转写`;
- enables `开始转写`.

Importing the same file again opens the existing history record instead of creating another copy or overwriting its transcript.

### Transcribe

Choose a preset and click `开始转写`. Progress, engine information, fallback details, and `终止转写` are shown only inside the transcript panel.

While a task is active, importing, switching history records, and deleting history are disabled. Video playback remains available.

When transcription finishes, the transcript replaces the progress view. Click a transcript paragraph to seek to its corresponding video time.

### Re-transcribe

For a completed record, the action changes to `重新转写`. The existing transcript is replaced only after confirmation.

If transcription is cancelled or fails, the video remains in history and its state returns to `未转写`.

After re-transcription is confirmed, the previous transcript is cleared before the new task starts. If that task is cancelled or fails, the previous transcript is not restored. A failure reason survives page refresh while the same backend process keeps that record active. Reopening the record, switching records, or restarting the backend clears the transient error display and leaves the persistent state as `未转写`.

### History drawer

Use the history icon next to the page title to open the drawer. The drawer:

- overlays the workspace without resizing it;
- supports filename filtering;
- stays open after a record is selected;
- closes through its button, the backdrop, or `Esc`.

## Model Presets

- Speed: `small / cuda / int8_float16 / beam 1`
- Balanced: `medium / cuda / float16 / beam 3`
- Accurate: `large-v3 / cuda / float16 / beam 5`

If CUDA cannot be loaded, the app falls back to CPU and shows the reason in the transcript progress view.

## Local Data

History is stored under:

```text
data/items/<file_hash>/
```

Each directory contains:

- a local media copy named `source.<extension>`;
- `result.json` with the original filename, status, timestamps, duration, and transcript segments.

The primary persistent states are:

- `untranscribed`: imported and playable, without a transcript;
- `done`: transcription completed.

Active states (`queued`, `running`, and `cancelling`) are exposed by the current backend task and reflected in the history list while the process is running.

For compatibility, legacy records without a `status` field are treated as completed when the `segments` field exists, including an empty array produced by a completed no-speech transcription.

## Stop

If started through `Start Local Video Transcriber.cmd`, close the startup window.

If started with `run.ps1`, press:

```text
Ctrl + C
```

## Troubleshooting

### The layout looks outdated

Refresh once with `Ctrl + Shift + R`. CSS and JavaScript URLs include explicit versions to prevent stale asset combinations.

### Import returns `Method Not Allowed`

This indicates an outdated backend is still serving the port. Start the app again through `launch.ps1` or the shortcut. The launcher checks `api_version` and safely replaces an idle outdated project backend.

The current frontend/backend protocol version is `2`. If a page is opened directly against another version, the frontend disables actions and asks the user to restart through the launcher.

It will not automatically stop an outdated backend while that backend reports an active transcription task.

## Do Not Commit

The following are local-only and ignored:

- `.venv/`
- `data/`
- `temp/`
- `server.log`
- `server.err.log`
- Python cache files

Do not commit local videos, transcripts, model caches, credentials, or environment files.

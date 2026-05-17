from __future__ import annotations

import os
from pathlib import Path
import sys


def add_cuda_dll_directories() -> None:
    if os.name != "nt":
        return

    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    candidates = [
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "nvidia" / "cuda_nvrtc" / "bin",
    ]

    existing = []
    for path in candidates:
        if path.exists():
            os.add_dll_directory(str(path))
            existing.append(str(path))

    if existing:
        os.environ["PATH"] = ";".join(existing + [os.environ.get("PATH", "")])

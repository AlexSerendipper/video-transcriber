from __future__ import annotations

from pathlib import Path
import importlib.util
import re
import sys
import threading
import types

from huggingface_hub import snapshot_download

from .segmenter import PUNCTUATION_RE, TextBlock, restore_light_punctuation


MODEL_REPO = "lucasjin/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
_model = None
_model_lock = threading.Lock()


def restore_punctuation_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    try:
        model = _get_punctuation_model()
    except Exception:
        return [
            TextBlock(start=block.start, end=block.end, text=restore_light_punctuation(block.text))
            for block in blocks
        ]

    restored: list[TextBlock] = []
    for block in blocks:
        text = _strip_punctuation(block.text)
        if not text:
            restored.append(block)
            continue
        try:
            punctuated = model(text)[0]
        except Exception:
            punctuated = restore_light_punctuation(block.text)
        restored.append(TextBlock(start=block.start, end=block.end, text=punctuated.strip()))
    return restored


def _strip_punctuation(text: str) -> str:
    return re.sub(PUNCTUATION_RE, "", text).strip()


def _get_punctuation_model():
    global _model
    with _model_lock:
        if _model is not None:
            return _model

        model_dir = snapshot_download(MODEL_REPO)
        CTTransformer = _load_ct_transformer()
        _model = CTTransformer(model_dir, device_id="-1", intra_op_num_threads=4)
        return _model


def _load_ct_transformer():
    package_root = Path(sys.prefix) / "Lib" / "site-packages" / "funasr_onnx"
    package = types.ModuleType("funasr_onnx")
    package.__path__ = [str(package_root)]
    sys.modules.setdefault("funasr_onnx", package)

    module_name = "funasr_onnx.punc_bin"
    if module_name in sys.modules:
        return sys.modules[module_name].CT_Transformer

    spec = importlib.util.spec_from_file_location(module_name, package_root / "punc_bin.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load funasr_onnx punctuation module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.CT_Transformer

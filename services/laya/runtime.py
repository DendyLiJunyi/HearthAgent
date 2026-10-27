"""Project-local caches and a reproducible checkpoint selection."""
import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_REPO = "convaiinnovations/laya"
MODEL_REVISION = "7b928d828b7b0e022f929d9bd2e44165aa270148"
MODEL_SUBFOLDER = "multilingual"


def configure_environment():
    os.environ["HF_HOME"] = str(ROOT / ".tools" / "huggingface")
    os.environ["TORCH_HOME"] = str(ROOT / ".tools" / "torch")
    os.environ["USE_TF"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["LAYA_REVISION"] = MODEL_REVISION


def synthetic_state():
    return json.loads((ROOT / "fixtures" / "laya" / "lethal.json").read_text(encoding="utf-8"))

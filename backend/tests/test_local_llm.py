"""Local LLM fallback (Ollama): which installed model the analyst uses."""
import io
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.ml.explainer import llm


def _tags(*names):
    payload = json.dumps({"models": [{"name": n} for n in names]}).encode("utf-8")
    return mock.MagicMock(__enter__=lambda self: io.BytesIO(payload), __exit__=lambda *a: False)


def _pick(*installed, env=None):
    llm._ollama_checked_at = -1e9  # force a fresh check
    with mock.patch.object(llm.urllib.request, "urlopen", return_value=_tags(*installed)), \
         mock.patch.dict(llm.os.environ, {"OLLAMA_MODEL": env} if env else {}, clear=False):
        if not env:
            llm.os.environ.pop("OLLAMA_MODEL", None)
        return llm._ollama_model()


def test_embedding_models_are_never_used_to_write_text():
    assert _pick("all-minilm:latest") is None


def test_preferred_chat_model_wins_over_other_installed_models():
    assert _pick("all-minilm:latest", "mistral:latest", "llama3.2:3b") == "llama3.2:3b"


def test_any_installed_chat_model_is_used_when_none_is_preferred():
    assert _pick("all-minilm:latest", "tinyllama:latest") == "tinyllama:latest"


def test_ollama_model_env_overrides_the_preference():
    assert _pick("llama3.2:3b", "qwen2.5:3b", env="qwen2.5:3b") == "qwen2.5:3b"


def test_no_local_model_when_ollama_is_not_running():
    llm._ollama_checked_at = -1e9
    with mock.patch.object(llm.urllib.request, "urlopen", side_effect=OSError("connection refused")):
        assert llm._ollama_model() is None

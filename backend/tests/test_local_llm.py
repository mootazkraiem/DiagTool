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


# ── provider chain: Gemini → Ollama → rule-based ────────────────────────────

ALERT = {
    "can_id": "0x7B0", "score": 0.97, "severity": "CRITICAL", "attack_type": "dos_burst",
    "reason": "top_feature=msg_rate, cluster=4", "dominant_detection_layer": "timing",
}
GOOD_JSON = '{"summary": "s", "detail": "d", "recommendation": "r"}'


def _no_side_effects(monkeypatch):
    """Keep explain_alert off the network and the anomaly store."""
    monkeypatch.setattr(llm, "_web_search", lambda *a, **k: "")
    monkeypatch.setattr(llm, "_persist", lambda *a, **k: None)


def test_gemini_is_used_first_and_ollama_is_not_called(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: {"summary": "g", "detail": "", "recommendation": ""})
    called = []
    monkeypatch.setattr(llm, "_try_ollama", lambda *a, **k: called.append(1))
    assert llm.explain_alert(ALERT)["mode"] == "gemini"
    assert called == []


def test_ollama_answers_when_gemini_fails(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: ("llama3.2:3b", GOOD_JSON))
    result = llm.explain_alert(ALERT)
    assert result["mode"] == "ollama"
    assert result["summary"] == "s"


def test_rule_based_when_both_providers_fail(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: None)  # no local model
    result = llm.explain_alert(ALERT)
    assert result["mode"] == "rule_based"
    assert result["summary"]


def test_malformed_json_from_the_local_model_never_reaches_the_caller(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: ("llama3.2:3b", "Sure! here is json {oops"))
    result = llm.explain_alert(ALERT)
    assert result["mode"] == "rule_based"
    assert result["summary"]


def test_unreachable_ollama_service_does_not_crash_the_explanation(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: None)
    llm._ollama_checked_at = -1e9
    monkeypatch.setattr(llm.urllib.request, "urlopen", mock.MagicMock(side_effect=OSError("connection refused")))
    result = llm.explain_alert(ALERT)
    assert result["mode"] == "rule_based"


# ── Gemini pausing ──────────────────────────────────────────────────────────

def test_network_failure_pauses_gemini_briefly_so_offline_alerts_reach_ollama():
    llm._gemini_paused_until = 0.0
    llm._pause_gemini_after(llm.urllib.error.URLError("no route to host"))
    assert not llm._gemini_available()
    llm._gemini_paused_until = 0.0


def test_rate_limit_and_missing_model_pause_gemini_for_their_own_periods():
    for code, expected in ((429, llm._GEMINI_RATE_LIMIT_RETRY_S), (404, llm._GEMINI_RETRY_AFTER_S)):
        llm._gemini_paused_until = 0.0
        llm._pause_gemini_after(llm.urllib.error.HTTPError("u", code, "m", {}, None))
        remaining = llm._gemini_paused_until - llm.time.monotonic()
        assert expected - 2 < remaining <= expected
    llm._gemini_paused_until = 0.0


def test_server_errors_do_not_pause_gemini():
    llm._gemini_paused_until = 0.0
    llm._pause_gemini_after(llm.urllib.error.HTTPError("u", 503, "busy", {}, None))
    assert llm._gemini_available()


# ── grounding: figures stated but never supplied ────────────────────────────

def test_a_figure_absent_from_the_prompt_is_flagged():
    prompt = "Frequency: not measured for this alert\nAnomaly score: 0.97"
    assert llm._unsupported_figures("Traffic ran at 4000 msg/s.", prompt) == ["4000"]


def test_figures_taken_from_the_prompt_are_not_flagged():
    prompt = "Normal frequency: 40–150 msg/s\nAnomaly score: 0.97"
    assert llm._unsupported_figures("Between 40 and 150 msg/s is normal; score 0.97.", prompt) == []


def test_a_percentage_of_a_supplied_fraction_is_supported():
    assert llm._unsupported_figures("Confidence is 97%.", "Anomaly score: 0.97") == []


def test_small_numbers_in_prose_are_not_treated_as_measurements():
    assert llm._unsupported_figures("Check 3 ECUs and 2 harnesses.", "Anomaly score: 0.97") == []


def test_explanations_carry_the_figure_check(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k:
                        ("llama3.2:3b", '{"summary": "Flood at 4000 msg/s", "detail": "", "recommendation": ""}'))
    assert llm.explain_alert(ALERT)["unsupported_figures"] == ["4000"]


# ── prompt honesty about missing data ───────────────────────────────────────

def test_missing_measurements_are_stated_as_missing_not_as_unknown():
    assert llm._measured(None) == "not measured for this alert"
    assert llm._measured("unknown") == "not measured for this alert"
    assert llm._measured(120, "msg/s") == "120 msg/s"


def test_a_borrowed_baseline_is_labelled_when_the_state_is_unknown():
    from backend.ml.explainer.context_builder import build_context
    ctx = build_context(ALERT)
    prompt = llm._build_analyst_prompt(ALERT, ctx, "")
    assert "not measured for this alert" in prompt
    # The hand-written driving-state profile is no longer offered as this identifier's normal rate.
    assert "No measured normal rate for this identifier" in prompt
    assert "40–150" not in prompt and "Normal frequency" not in prompt
    assert "never invent or estimate a number" in prompt


def test_a_merged_alert_burst_is_not_presented_as_a_measured_flood():
    from backend.ml.explainer.context_builder import build_context
    alert = dict(ALERT, is_burst_summary=True, suppressed_count=12, burst_window_s=2.0,
                 layer_scores={"timing": 0.55, "payload": 1.0, "ml": 0.828, "temporal": 0.0})
    ctx = build_context(alert)
    prompt = llm._build_analyst_prompt(alert, ctx, "")
    assert "12 flagged frames merged into this alert within 2 s" in prompt
    assert "not a measured message rate" in prompt
    assert "temporal 0.000" in prompt and "engine's final score" in prompt
    assert "Do not call the alert a flood" in prompt


def test_dedup_labels_a_merged_burst_as_an_alert_burst_not_a_dos_burst():
    from backend.ml import dedup
    ctxs = [{"can_id": "0x0AA", "timestamp": i * 0.1, "anomaly_score": 0.6 + i * 0.01} for i in range(12)]
    out = dedup.deduplicate(ctxs)
    assert len(out) == 1
    assert out[0]["temporal_pattern"] == "alert_burst"
    assert "12 flagged frames" in out[0]["burst_label"]


# ── grounding: figures quoted for values that were never measured ───────────

PROMPT_WITH_MISSING = (
    "=== CURRENT ANOMALY ===\n"
    "CAN-ID:          0x17FE007B\n"
    "Frequency:       not measured for this alert\n"
    "Entropy:         not measured for this alert\n"
    "Anomaly score:   0.663\n"
    "=== NORMAL BEHAVIOR BASELINE ===\n"
    "  Normal frequency:    40–150 msg/s\n"
)


def test_turning_an_unmeasured_value_into_a_number_is_flagged():
    # The exact failure seen in QA with the local 3B model.
    answer = ("The observed frequency of 0 msg/s is significantly lower than the normal "
              "range of 40-150 msg/s, indicating a potential DoS attack.")
    claims = llm._unmeasured_claims(answer, PROMPT_WITH_MISSING)
    assert len(claims) == 1 and "0 msg/s" in claims[0]


def test_saying_a_value_was_not_measured_is_not_flagged():
    answer = "The frequency was not measured for this alert, so no comparison is possible."
    assert llm._unmeasured_claims(answer, PROMPT_WITH_MISSING) == []


def test_measured_fields_are_not_flagged():
    prompt = "Frequency:       120.0 msg/s\nAnomaly score:   0.663\n"
    assert llm._unmeasured_claims("Frequency reached 120 msg/s.", prompt) == []


def test_explanations_carry_the_unmeasured_claim_check(monkeypatch):
    _no_side_effects(monkeypatch)
    monkeypatch.setattr(llm, "_try_gemini", lambda *a, **k: None)
    monkeypatch.setattr(llm, "_ollama_generate", lambda *a, **k: (
        "llama3.2:3b",
        '{"summary": "Entropy of 0.0 is far below normal.", "detail": "", "recommendation": ""}'))
    result = llm.explain_alert(ALERT)
    assert result["unmeasured_claims"]

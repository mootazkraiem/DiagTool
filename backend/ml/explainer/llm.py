"""CAN Security Analyst Assistant — multi-provider LLM explainer.

Identity: domain-specific automotive cybersecurity analyst assistant.
Focus: explainability, contextual reasoning, historical similarity, investigation.

Provider chain (in order):
1. Gemini 1.5 Flash — free tier (1M tokens/day). Needs GOOGLE_API_KEY env var.
   Uses the Gemini REST API via urllib — no extra package required.
2. Ollama — local LLM at localhost:11434. Tries llama3, mistral, gemma, phi3.
3. Template — deterministic fallback, always works.

Context sources injected into every prompt (via context_builder):
  1. Current anomaly features (can_id, state, freq, entropy, score, layer)
  2. Normal state statistics (expected ranges for the detected driving state)
  3. Attack KB match (keyword retrieval from attack_kb.json)
  4. Historical similar anomalies (cosine similarity from anomaly_history.jsonl)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from backend.ml.explainer.context_builder import build_context
from backend.ml.explainer.anomaly_store import save_anomaly

logger = logging.getLogger(__name__)

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-flash:generateContent?key={key}"
)
_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_MODELS = ["llama3", "gemma", "mistral", "phi3"]

_SIGNAL_MAP_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "signal_map.json"
_signal_map: dict[str, Any] | None = None
_signal_map_mtime: float = 0.0


def _load_signal_map() -> dict[str, Any]:
    global _signal_map, _signal_map_mtime
    try:
        mtime = _SIGNAL_MAP_PATH.stat().st_mtime
    except OSError:
        return _signal_map or {}
    if _signal_map is None or mtime != _signal_map_mtime:
        try:
            _signal_map = json.loads(_SIGNAL_MAP_PATH.read_text(encoding="utf-8"))
            _signal_map_mtime = mtime
        except Exception:
            _signal_map = {}
    return _signal_map


def _signal_context(can_id: str) -> str:
    smap = _load_signal_map()
    key = can_id.upper().lstrip("0X") if can_id else ""
    entry: dict[str, Any] | None = None
    for k, v in smap.items():
        if k.upper().lstrip("0X") == key:
            entry = v
            break
    if entry is None:
        return ""
    system = entry.get("system", "Unknown ECU")
    short = entry.get("short", "")
    vehicles = entry.get("vehicles", "")
    header = f"Message: {system} (sender: {short}) on CAN-ID {can_id}"
    if vehicles:
        header += f"\nKnown vehicle(s): {vehicles}"
    lines = [header]
    for sig in entry.get("signals", []):
        name = sig.get("name", "?")
        unit = sig.get("unit", "")
        lo = sig.get("min_normal", "?")
        hi = sig.get("max_normal", "?")
        nominal = sig.get("nominal", "?")
        scale = sig.get("scale", 1.0)
        offset = sig.get("offset", 0.0)
        decode = sig.get("decode", "uint8")
        lines.append(
            f"  • {name} ({decode} × {scale}"
            + (f" + {offset}" if offset else "")
            + (f" {unit}" if unit else "")
            + f"): normal {lo}–{hi}"
            + (f" {unit}" if unit else "")
            + f", nominal {nominal}"
        )
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────────────────

def explain_alert(alert: dict[str, Any]) -> dict[str, str]:
    """Return summary/detail/recommendation/kb_match_label for the given alert."""
    ctx = build_context(alert)
    sig_ctx = _signal_context(str(alert.get("can_id", "")))

    result = _try_gemini(alert, ctx, sig_ctx)
    if result:
        _persist(alert, result)
        return result

    result = _try_ollama(alert, ctx, sig_ctx)
    if result:
        _persist(alert, result)
        return result

    result = _template(alert, ctx, sig_ctx)
    _persist(alert, result)
    return result


def chat_reply(alert: dict[str, Any], message: str) -> str:
    """Return a focused analyst reply about the alert, answering the user's question."""
    ctx = build_context(alert)
    sig_ctx = _signal_context(str(alert.get("can_id", "")))

    result = _try_gemini_chat(alert, ctx, sig_ctx, message)
    if result:
        return result
    result = _try_ollama_chat(alert, ctx, sig_ctx, message)
    if result:
        return result
    return _template_chat(alert, ctx, sig_ctx, message)


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_analyst_prompt(alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str) -> str:
    a = ctx["anomaly"]
    kb = ctx.get("kb")
    similar = ctx.get("similar_history", [])
    sn = ctx.get("state_normal", {})
    dev = ctx.get("deviations", {})

    freq_range = sn.get("frequency_range", ["?", "?"])
    ent_range = sn.get("entropy_range", ["?", "?"])
    td_range = sn.get("time_diff_range", ["?", "?"])

    # Block 1 — current anomaly
    anomaly_block = (
        f"CAN-ID:          {a['can_id']}\n"
        f"Vehicle state:   {a['state']}\n"
        f"Frequency:       {dev.get('frequency', str(a['frequency']) + ' msg/s')}\n"
        f"Entropy:         {dev.get('entropy', str(a['entropy']))}\n"
        f"Inter-arrival:   {dev.get('time_diff', str(a['time_diff']) + 's')}\n"
        f"Anomaly score:   {a['score']}\n"
        f"Severity:        {a['severity']}\n"
        f"Detection layer: {a['layer']}\n"
        f"Raw reason:      {a['reason']}"
    )

    # Block 2 — normal baseline
    baseline_block = (
        f"State: {sn.get('label', a['state'])}\n"
        f"  Normal frequency:    {freq_range[0]}–{freq_range[1]} msg/s\n"
        f"  Normal entropy:      {ent_range[0]}–{ent_range[1]}\n"
        f"  Normal inter-arrival:{td_range[0]}–{td_range[1]} s\n"
        f"  Notes: {sn.get('notes', '—')}"
    )

    # Block 3 — KB match
    if kb:
        kb_block = (
            f"Attack type:     {kb['attack_type']}\n"
            f"Summary:         {kb['summary']}\n"
            f"Detail:          {kb['detail'][:400]}\n"
            f"Recommendation:  {kb['recommendation']}"
        )
    else:
        kb_block = "No strong KB match — likely novel or mixed-vector pattern."

    # Block 4 — historical
    if similar:
        history_lines = []
        for h in similar:
            history_lines.append(
                f"  • CAN-ID {h.get('can_id','?')} | state={h.get('state','?')} | "
                f"freq={h.get('frequency',0):.0f} msg/s | entropy={h.get('entropy',0):.2f} | "
                f"score={h.get('score',0):.3f} | attack={h.get('attack_type','?')}\n"
                f"    → {h.get('summary','')}"
            )
        history_block = "\n".join(history_lines)
    else:
        history_block = "No similar historical anomalies on record yet."

    # Block 5 — signal map
    sig_block = f"\n\nECU Signal Map:\n{sig_ctx}" if sig_ctx else ""

    return (
        "You are the CAN Security Analyst Assistant — a specialized automotive cybersecurity expert.\n"
        "Your role: help engineers investigate CAN bus anomalies. Focus on explainability, "
        "comparison with normal behavior, and identification of likely attack patterns.\n\n"
        "=== CURRENT ANOMALY ===\n"
        f"{anomaly_block}\n\n"
        "=== NORMAL BEHAVIOR BASELINE ===\n"
        f"{baseline_block}\n\n"
        "=== ATTACK PATTERN MATCH ===\n"
        f"{kb_block}\n\n"
        "=== SIMILAR HISTORICAL ANOMALIES ===\n"
        f"{history_block}"
        f"{sig_block}\n\n"
        "Analyze this anomaly. Compare observed behavior with the normal baseline. "
        "Identify the most likely attack pattern. "
        "Respond in JSON with exactly three keys: "
        "\"summary\" (one sentence finding), "
        "\"detail\" (2–3 sentences: observed vs normal comparison + attack vector + risk), "
        "\"recommendation\" (one sentence mitigation)."
    )


def _build_analyst_chat_prompt(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, message: str
) -> str:
    a = ctx["anomaly"]
    kb = ctx.get("kb")
    similar = ctx.get("similar_history", [])
    sn = ctx.get("state_normal", {})
    dev = ctx.get("deviations", {})

    freq_range = sn.get("frequency_range", ["?", "?"])
    ent_range = sn.get("entropy_range", ["?", "?"])

    kb_line = f"KB match: {kb['attack_type']} — {kb['summary'][:120]}" if kb else "KB: no strong match"
    history_line = ""
    if similar:
        top = similar[0]
        history_line = (
            f"\nMost similar case: CAN-ID {top.get('can_id','?')}, "
            f"freq={top.get('frequency',0):.0f} msg/s, score={top.get('score',0):.3f}, "
            f"attack={top.get('attack_type','?')} → {top.get('summary','')[:120]}"
        )
    sig_line = f"\nECU: {sig_ctx.split(chr(10))[0]}" if sig_ctx else ""

    return (
        "You are the CAN Security Analyst Assistant — an automotive cybersecurity expert.\n"
        f"Current alert context:\n"
        f"  CAN-ID {a['can_id']} | state={a['state']} | score={a['score']} | severity={a['severity']}\n"
        f"  Frequency:  {dev.get('frequency', str(a['frequency']))}\n"
        f"  Entropy:    {dev.get('entropy', str(a['entropy']))}\n"
        f"  Normal freq range ({a['state']}): {freq_range[0]}–{freq_range[1]} msg/s\n"
        f"  Normal entropy range: {ent_range[0]}–{ent_range[1]}\n"
        f"  Detection layer: {a['layer']} | Reason: {a['reason'][:180]}\n"
        f"  {kb_line}{history_line}{sig_line}\n\n"
        f"Engineer asks: {message}\n\n"
        "Rules:\n"
        "- Answer questions about this anomaly, the attack type, signal meaning, "
        "vehicle cybersecurity, CAN features, or investigation steps. Be specific.\n"
        "- Compare observed values to the normal baseline when relevant.\n"
        "- Reference similar historical cases when they add insight.\n"
        "- If the question is completely unrelated to vehicle security: "
        "respond exactly: 'I can only help with questions about this CAN bus alert.'\n"
        "Plain text only — no JSON, no markdown, no bullet points."
    )


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _http_post(
    url: str, body: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 20
) -> str:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_json_response(text: str) -> dict[str, str] | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "summary" in obj:
            return {
                "summary":        str(obj.get("summary", "")),
                "detail":         str(obj.get("detail", "")),
                "recommendation": str(obj.get("recommendation", "")),
            }
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _persist(alert: dict[str, Any], result: dict[str, str]) -> None:
    try:
        save_anomaly(alert, result.get("summary", ""))
    except Exception as exc:
        logger.debug("[analyst] anomaly_store save failed: %s", exc)


# ── Gemini provider ───────────────────────────────────────────────────────────

def _try_gemini(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str
) -> dict[str, str] | None:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        prompt = _build_analyst_prompt(alert, ctx, sig_ctx)
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 450},
        }
        raw = _http_post(_GEMINI_URL.format(key=api_key), body, timeout=18)
        resp = json.loads(raw)
        candidates = resp.get("candidates")
        if not candidates:
            err = resp.get("error", {})
            logger.warning(
                "[analyst] Gemini returned no candidates: [%s] %s",
                err.get("code", "?"),
                err.get("message", raw[:200]),
            )
            return None
        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        result = _parse_json_response(text)
        if result:
            result["kb_match_label"] = ctx["kb"]["attack_type"] if ctx.get("kb") else ""
            logger.info("[analyst] Gemini provider succeeded.")
            return result
    except Exception as exc:
        logger.warning("[analyst] Gemini failed: %s", exc)
    return None


def _try_gemini_chat(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, message: str
) -> str | None:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        prompt = _build_analyst_chat_prompt(alert, ctx, sig_ctx, message)
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 200},
        }
        raw = _http_post(_GEMINI_URL.format(key=api_key), body, timeout=15)
        resp = json.loads(raw)
        candidates = resp.get("candidates")
        if not candidates:
            err = resp.get("error", {})
            logger.warning(
                "[analyst] Gemini chat returned no candidates: [%s] %s",
                err.get("code", "?"),
                err.get("message", raw[:200]),
            )
            return None
        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        if text:
            logger.info("[analyst] Gemini chat succeeded.")
            return text
    except Exception as exc:
        logger.warning("[analyst] Gemini chat failed: %s", exc)
    return None


# ── Ollama provider ───────────────────────────────────────────────────────────

def _try_ollama(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str
) -> dict[str, str] | None:
    prompt = _build_analyst_prompt(alert, ctx, sig_ctx)
    for model in _OLLAMA_MODELS:
        try:
            body = {"model": model, "prompt": prompt, "stream": False}
            raw = _http_post(_OLLAMA_URL, body, timeout=35)
            resp = json.loads(raw)
            text = resp.get("response", "")
            result = _parse_json_response(text)
            if result:
                result["kb_match_label"] = ctx["kb"]["attack_type"] if ctx.get("kb") else ""
                logger.info("[analyst] Ollama/%s provider succeeded.", model)
                return result
        except Exception as exc:
            logger.debug("[analyst] Ollama/%s failed: %s", model, exc)
    return None


def _try_ollama_chat(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, message: str
) -> str | None:
    prompt = _build_analyst_chat_prompt(alert, ctx, sig_ctx, message)
    for model in _OLLAMA_MODELS:
        try:
            body = {"model": model, "prompt": prompt, "stream": False}
            raw = _http_post(_OLLAMA_URL, body, timeout=25)
            resp = json.loads(raw)
            text = resp.get("response", "").strip()
            if text:
                logger.info("[analyst] Ollama/%s chat succeeded.", model)
                return text
        except Exception as exc:
            logger.debug("[analyst] Ollama/%s chat failed: %s", model, exc)
    return None


# ── Template fallback ─────────────────────────────────────────────────────────

def _template(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str
) -> dict[str, str]:
    a = ctx["anomaly"]
    kb = ctx.get("kb")
    dev = ctx.get("deviations", {})
    can_id = a["can_id"]
    score = a["score"]
    severity = a["severity"]
    layer = a["layer"]

    layer_map = {
        "timing":   "inter-frame timing deviation",
        "payload":  "payload entropy anomaly",
        "ml":       "ML isolation-forest outlier",
        "temporal": "temporal persistence pattern",
    }
    layer_desc = layer_map.get(layer, "multi-layer fusion anomaly")

    # Build comparison note from deviations
    freq_note = dev.get("frequency", "")
    ent_note = dev.get("entropy", "")
    comparison = ""
    if "ABOVE NORMAL" in freq_note or "BELOW NORMAL" in freq_note:
        comparison = f" Frequency: {freq_note}."
    elif "ABOVE NORMAL" in ent_note or "BELOW NORMAL" in ent_note:
        comparison = f" Entropy: {ent_note}."

    ecu_note = (
        f" ECU: {sig_ctx.split(chr(10))[0]}." if sig_ctx
        else f" CAN-ID {can_id} is not in the vehicle signal map — possible foreign node."
    )

    similar = ctx.get("similar_history", [])
    sim_note = ""
    if similar:
        top = similar[0]
        sim_note = (
            f" Similar historical case: {top.get('attack_type','unknown')} pattern "
            f"(score {top.get('score',0):.3f}, {top.get('state','?')} state)."
        )

    if kb:
        return {
            "summary": f"{kb['attack_type']} pattern detected on {can_id} — score {score:.3f} ({severity}).{comparison}{ecu_note}",
            "detail":  f"{kb['detail'][:450]}{comparison} Fusion score {score:.3f} via {layer_desc}.{sim_note}",
            "recommendation": kb["recommendation"],
            "kb_match_label": kb["attack_type"],
        }

    sev_desc = {
        "CRITICAL": "critical intrusion", "HIGH": "high-risk anomaly", "WARNING": "elevated alert"
    }.get(severity, "anomaly")
    return {
        "summary": f"{sev_desc.capitalize()} on {can_id} — score {score:.3f}, {layer_desc}.{comparison}{ecu_note}",
        "detail":  (
            f"Dominant layer: {layer_desc}. Raw scores: {a['reason'] or 'unavailable'}.{comparison}"
            f" Score {score:.3f} exceeds the {severity.lower()} threshold.{sim_note}"
        ),
        "recommendation": (
            "Isolate the CAN segment carrying this ID, capture raw frames for forensic analysis, "
            "and cross-reference against the vehicle's expected DBC signal map."
        ),
        "kb_match_label": "",
    }


def _template_chat(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, message: str
) -> str:
    a = ctx["anomaly"]
    kb = ctx.get("kb")
    dev = ctx.get("deviations", {})
    similar = ctx.get("similar_history", [])
    sn = ctx.get("state_normal", {})

    can_id = a["can_id"]
    score = a["score"]
    severity = a["severity"].lower()
    layer = a["layer"]

    layer_map = {
        "timing":   "inter-frame timing deviation",
        "payload":  "payload entropy anomaly",
        "ml":       "ML isolation-forest outlier",
        "temporal": "temporal persistence pattern",
    }
    layer_desc = layer_map.get(layer, "multi-layer fusion anomaly")
    q = message.lower()

    _can_topics = (
        "attack", "anomaly", "inject", "spoof", "flood", "fuzzy", "replay", "dos", "intrusion",
        "threat", "malicious", "unauthorized",
        "can-id", "can id", "canid", "frame", "ecu", "bus", "payload", "timing", "temporal",
        "score", "alert", "layer", "detect", "severity",
        "signal", "sensor", "voltage", "speed", "rpm", "gear", "temperature",
        "frequency", "entropy", "inter-arrival", "time", "normal", "baseline",
        "history", "similar", "previous", "historic",
        "fix", "mitigate", "prevent", "recommend",
        "this id", "that id", "this can", "the id", "this alert", "this anomaly",
        "cause", "reason", "flagged", "triggered",
    )
    if not any(t in q for t in _can_topics):
        return "I'm the CAN Security Analyst Assistant — I can only help with questions about this alert, the attack type, signal meanings, or investigation steps."

    freq_range = sn.get("frequency_range", [None, None])
    ent_range = sn.get("entropy_range", [None, None])

    # Why / cause / reason
    if any(t in q for t in ("cause", "reason", "flagged", "triggered", "why", "how did", "how was", "detect")):
        freq_note = dev.get("frequency", "")
        ent_note = dev.get("entropy", "")
        comparison = ""
        if "ABOVE NORMAL" in freq_note:
            comparison = f" Its frequency ({a['frequency']} msg/s) is far above the expected {freq_range[0]}–{freq_range[1]} msg/s for the {a['state']} state."
        elif "BELOW NORMAL" in freq_note:
            comparison = f" Its frequency ({a['frequency']} msg/s) is well below the expected {freq_range[0]}–{freq_range[1]} msg/s."
        elif "ABOVE NORMAL" in ent_note:
            comparison = f" Its entropy ({a['entropy']}) exceeds the expected {ent_range[0]}–{ent_range[1]} range."
        kb_note = f" Pattern matches: {kb['attack_type']}." if kb else ""
        sig_note = f" Affected system: {sig_ctx.split(chr(10))[0]}." if sig_ctx else ""
        return (
            f"CAN-ID {can_id} was flagged because its {layer_desc} is statistically abnormal "
            f"(fusion score {score:.3f}, {severity}).{comparison}{kb_note}{sig_note}"
        )

    # Normal baseline / compare
    if any(t in q for t in ("normal", "baseline", "expected", "compare", "difference", "typical")):
        freq_dev = dev.get("frequency", f"observed: {a['frequency']}")
        ent_dev = dev.get("entropy", f"observed: {a['entropy']}")
        return (
            f"For the {a['state']} state, normal frequency is {freq_range[0]}–{freq_range[1]} msg/s "
            f"and entropy {ent_range[0]}–{ent_range[1]}. "
            f"This anomaly shows: frequency {freq_dev}; entropy {ent_dev}. "
            f"Anomaly score: {score:.3f} ({severity})."
        )

    # Historical / similar
    if any(t in q for t in ("history", "similar", "previous", "historic", "before", "past")):
        if similar:
            lines = []
            for h in similar:
                lines.append(
                    f"CAN-ID {h.get('can_id','?')} — {h.get('attack_type','?')}, "
                    f"score {h.get('score',0):.3f}, state={h.get('state','?')}: {h.get('summary','')}"
                )
            return "Similar historical anomalies:\n" + "\n".join(lines)
        return "No similar historical anomalies have been recorded yet. This may be the first instance of this pattern."

    # Signal / ECU identity
    _id_patterns = ("this id", "that id", "the id", "this can", "can-id", "can id",
                    "which ecu", "what ecu", "signal", "sensor", "voltage", "speed",
                    "rpm", "gear", "temperature", "represent", "belongs to", "mapped to")
    if any(t in q for t in _id_patterns):
        if sig_ctx:
            ecu_line = sig_ctx.split("\n")[0]
            signals = "\n".join(sig_ctx.split("\n")[1:5])
            return (
                f"{ecu_line}\n{signals}\n\n"
                f"Currently under a {severity} alert (score {score:.3f}) — "
                f"its {layer_desc} is outside the expected range."
            )
        return (
            f"CAN-ID {can_id} is not in this vehicle's DBC signal map. "
            f"That absence is suspicious — legitimate ECUs are always pre-registered. "
            f"With a {layer_desc} (score {score:.3f}), this looks like a spoofed or injected frame."
        )

    # Fix / mitigation
    if any(t in q for t in ("fix", "mitigate", "prevent", "recommend", "what to do", "next step", "action", "stop")):
        if kb:
            sig_note = f" Also verify the signal state of {sig_ctx.split(chr(10))[0]}." if sig_ctx else ""
            return f"{kb['recommendation']}{sig_note}"
        return (
            "Isolate the CAN segment carrying this ID, capture raw frames for forensic analysis, "
            "and compare against the vehicle's expected DBC signal map to identify the transmitting node."
        )

    # Attack / anomaly type
    if any(t in q for t in ("attack", "anomaly", "inject", "spoof", "fuzzy", "dos", "intrusion", "this alert")):
        if kb:
            detail = kb.get("detail", "")[:350]
            sig_note = f" Affected system: {sig_ctx.split(chr(10))[0]}." if sig_ctx else ""
            return f"This is a {kb['attack_type']} pattern. {detail}{sig_note} Fusion score: {score:.3f} ({severity})."
        ecu_note = (
            f" Affected system: {sig_ctx.split(chr(10))[0]}." if sig_ctx
            else f" CAN-ID {can_id} is not in the vehicle signal map."
        )
        return (
            f"This is a {layer_desc} anomaly on CAN-ID {can_id} — score {score:.3f} ({severity}).{ecu_note} "
            f"Ask me about the cause, the normal baseline, similar cases, or mitigation steps."
        )

    # Default
    freq_dev = dev.get("frequency", f"{a['frequency']} msg/s")
    ecu_note = f" ECU: {sig_ctx.split(chr(10))[0]}." if sig_ctx else f" CAN-ID {can_id} not in signal map."
    return (
        f"Anomaly on {can_id}: {layer_desc}, score {score:.3f} ({severity}). "
        f"Frequency: {freq_dev}.{ecu_note} "
        f"Ask me about the attack type, the normal baseline, similar historical cases, or what to do next."
    )

"""CAN Security Analyst Assistant — multi-provider LLM explainer.

Identity: domain-specific automotive cybersecurity analyst assistant.
Focus: explainability, contextual reasoning, historical similarity, investigation.

Provider chain (in order):
1. Gemini Flash (GEMINI_MODEL, default the gemini-flash-latest alias). Needs GOOGLE_API_KEY env var.
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
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

from backend.ml.explainer.context_builder import build_context
from backend.ml.explainer.anomaly_store import save_anomaly

logger = logging.getLogger(__name__)

# A pinned Gemini version is eventually retired (gemini-1.5-flash now returns 404),
# so the default is Google's alias for the current Flash model. Set GEMINI_MODEL to
# pin a specific version instead.
_GEMINI_DEFAULT_MODEL = "gemini-flash-latest"
_GEMINI_MAX_OUTPUT_TOKENS = 2048   # newer models spend part of this on thinking

# After a failed call Gemini is skipped for a while, so one outage does not cost a
# full failed round-trip on every alert of a large log.
_GEMINI_RETRY_AFTER_S = 300.0      # model missing, bad key, bad request
_GEMINI_RATE_LIMIT_RETRY_S = 60.0  # quota / rate limit (HTTP 429)
_GEMINI_NETWORK_RETRY_S = 30.0     # no route to the API (offline)
_gemini_paused_until = 0.0


def _gemini_url(api_key: str) -> str:
    model = os.environ.get("GEMINI_MODEL", "").strip() or _GEMINI_DEFAULT_MODEL
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )


def _gemini_available() -> bool:
    return time.monotonic() >= _gemini_paused_until


def _pause_gemini_after(exc: Exception) -> None:
    """Skip Gemini for a while after a failure, so the next alerts go straight to
    the local model instead of paying the same failed cloud call again.

    Client errors (missing model, bad key, quota) are the long pause. Network
    errors get a short one: offline, every explanation would otherwise wait for
    the connection to fail before reaching Ollama, and the pause must expire
    quickly once the network returns."""
    global _gemini_paused_until
    if isinstance(exc, urllib.error.HTTPError):
        if not 400 <= exc.code < 500:
            return
        delay = _GEMINI_RATE_LIMIT_RETRY_S if exc.code == 429 else _GEMINI_RETRY_AFTER_S
        _gemini_paused_until = time.monotonic() + delay
        logger.warning("[analyst] Gemini HTTP %s - skipping Gemini for %.0f s.", exc.code, delay)
        return
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        _gemini_paused_until = time.monotonic() + _GEMINI_NETWORK_RETRY_S
        logger.warning("[analyst] Gemini unreachable (%s) - skipping Gemini for %.0f s.", exc, _GEMINI_NETWORK_RETRY_S)


def _candidate_text(candidate: dict[str, Any]) -> str:
    """Joined answer text of a candidate, without thought parts."""
    parts = (candidate.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
# Preferred local chat models, best fit first. llama3.2:3b runs fully on a 4 GB
# GPU; OLLAMA_MODEL overrides the choice. Only models that are actually
# installed are used (see _ollama_model).
_OLLAMA_PREFERRED = ["llama3.2:3b", "llama3.2", "qwen2.5:3b", "phi3:mini", "gemma2:2b", "llama3", "mistral", "phi3", "gemma"]
# Embedding-only models can be installed alongside (all-minilm is, for RAG)
# but cannot write text.
_OLLAMA_EMBEDDING_HINTS = ("minilm", "embed", "bge", "nomic")
_OLLAMA_CHECK_TTL_S = 60.0
_ollama_checked_at = -1e9
_ollama_model_cache: str | None = None


def _ollama_model() -> str | None:
    """The installed local chat model to use, or None when Ollama is not
    running or has none. Re-checked every minute, so starting Ollama (or
    pulling a model) after the backend started still takes effect."""
    global _ollama_checked_at, _ollama_model_cache
    now = time.monotonic()
    if now - _ollama_checked_at < _OLLAMA_CHECK_TTL_S:
        return _ollama_model_cache
    _ollama_checked_at = now
    try:
        with urllib.request.urlopen(_OLLAMA_TAGS_URL, timeout=1.5) as resp:
            installed = [m.get("name", "") for m in json.loads(resp.read().decode("utf-8")).get("models", [])]
    except Exception:
        _ollama_model_cache = None
        return None
    chat_models = [n for n in installed if not any(h in n.lower() for h in _OLLAMA_EMBEDDING_HINTS)]
    wanted = [os.environ.get("OLLAMA_MODEL", "").strip()] + _OLLAMA_PREFERRED
    choice = None
    for name in [w for w in wanted if w]:
        for installed_name in chat_models:
            if installed_name == name or installed_name == f"{name}:latest" or installed_name.split(":")[0] == name:
                choice = installed_name
                break
        if choice:
            break
    if choice is None and chat_models:
        choice = chat_models[0]
    if choice != _ollama_model_cache:
        logger.info("[analyst] Local LLM: %s", choice or "none installed")
    _ollama_model_cache = choice
    return choice


def _ollama_generate(prompt: str, *, json_mode: bool, temperature: float, max_tokens: int, timeout: int) -> tuple[str, str] | None:
    """One Ollama completion: (model, text), or None."""
    model = _ollama_model()
    if model is None:
        return None
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:
        body["format"] = "json"
    raw = _http_post(_OLLAMA_URL, body, timeout=timeout)
    return model, json.loads(raw).get("response", "").strip()

# ── Web research (Wikipedia + NIST NVD — no API key required) ─────────────────

_search_cache: dict[str, str] = {}
_USER_AGENT = "CANvision-IDS/2.0 (automotive cybersecurity research tool)"


def _wikipedia_search(query: str) -> str:
    """Return a plain-text extract from the most relevant Wikipedia article."""
    try:
        encoded = urllib.parse.quote_plus(query)
        search_url = (
            f"https://en.wikipedia.org/w/api.php"
            f"?action=query&format=json&list=search&srsearch={encoded}&srlimit=2&srprop=snippet"
        )
        req = urllib.request.Request(search_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = data.get("query", {}).get("search", [])
        if not results:
            return ""
        title = results[0]["title"]
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
        req2 = urllib.request.Request(summary_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req2, timeout=6) as resp2:
            sdata = json.loads(resp2.read().decode("utf-8"))
        extract = sdata.get("extract", "")[:700].strip()
        if extract:
            return f"[Wikipedia — {title}]\n{extract}"
    except Exception as exc:
        logger.debug("[search] Wikipedia failed: %s", exc)
    return ""


def _nvd_cve_search(query: str) -> str:
    """Return recent CVE summaries from NIST NVD matching the query."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = (
            f"https://services.nvd.nist.gov/rest/json/cves/2.0"
            f"?keywordSearch={encoded}&resultsPerPage=3"
        )
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return ""
        lines = []
        for vuln in vulns[:3]:
            cve = vuln.get("cve", {})
            cve_id = cve.get("id", "?")
            descs = cve.get("descriptions", [])
            desc = next((d["value"] for d in descs if d.get("lang") == "en"), "")
            if desc:
                lines.append(f"  {cve_id}: {desc[:200]}")
        return ("[NIST NVD — Related CVEs]\n" + "\n".join(lines)) if lines else ""
    except Exception as exc:
        logger.debug("[search] NIST NVD failed: %s", exc)
    return ""


def _web_search(query: str) -> str:
    """Aggregate research from Wikipedia and NIST NVD. Results are cached."""
    if query in _search_cache:
        return _search_cache[query]
    parts: list[str] = []
    wiki = _wikipedia_search(query)
    if wiki:
        parts.append(wiki)
    # NVD works best with short keyword queries — strip question words, keep nouns
    stop_words = {"what", "is", "are", "how", "does", "do", "a", "an", "the",
                  "for", "of", "in", "to", "and", "or", "exist", "there", "any"}
    nvd_words = [w for w in query.split() if w.lower() not in stop_words][:5]
    nvd = _nvd_cve_search(" ".join(nvd_words))
    if nvd:
        parts.append(nvd)
    result = "\n\n".join(parts)
    _search_cache[query] = result
    if result:
        logger.info("[search] Web research complete for: %s", query[:60])
    return result


def _build_search_query(alert: dict[str, Any], ctx: dict[str, Any], user_message: str = "") -> str:
    """Build a targeted web search query from alert context + optional user question."""
    kb = ctx.get("kb")
    a = ctx["anomaly"]
    attack = kb["attack_type"] if kb else a.get("layer", "anomaly")

    if user_message and len(user_message) > 10:
        # Use the user question directly — clean for search without adding ECU-specific noise
        clean = user_message.strip().rstrip("?.!")[:120]
        return f"{clean} automotive CAN bus security"

    # Alert-based query (no user message) — include ECU if known
    can_id = a.get("can_id", "")
    sig_ctx = _signal_context(can_id, a)
    ecu = sig_ctx.split("\n")[0].replace("Message:", "").split("(")[0].strip() if sig_ctx else ""
    if ecu:
        return f"automotive CAN bus {attack} {ecu} cybersecurity CVE vulnerability"
    return f"automotive CAN bus {attack} attack cybersecurity mitigation"


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


def _signal_context(can_id: str, alert: dict[str, Any] | None = None) -> str:
    """Signal names for this identifier, only from the DBC decoded in this session.

    The global signal map is keyed by CAN ID alone and mixes vehicles, so it named a
    Jaguar frame (no DBC) after another vehicle's message. It is used only when the
    alert names the vehicle and the map entry lists that vehicle.
    """
    decoded = (alert or {}).get("decoded_signals")
    if isinstance(decoded, list) and decoded:
        parts = []
        for d in decoded[:8]:
            if isinstance(d, dict) and d.get("name"):
                parts.append(f"  • {d.get('name')} = {d.get('value', '?')} {d.get('unit', '')}".rstrip())
        if parts:
            return f"Signals decoded with the loaded DBC on CAN-ID {can_id}:\n" + "\n".join(parts)
    vehicle = str((alert or {}).get("vehicle", "")).strip().lower()
    if not vehicle:
        return ""
    smap = _load_signal_map()
    key = can_id.upper().lstrip("0X") if can_id else ""
    entry: dict[str, Any] | None = None
    for k, v in smap.items():
        if k.upper().lstrip("0X") == key:
            entry = v
            break
    if entry is None or vehicle not in str(entry.get("vehicles", "")).lower():
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
    """Return summary/detail/recommendation/kb_match_label/mode for the given alert.

    "mode" tells the caller — and, ultimately, the UI — which engine actually
    produced the text: "gemini" | "ollama" | "rule_based". The UI must not
    present rule_based output as if it were generative AI (see explain_alert
    callers in server.py and the CANvision Anomaly Intel panel).
    """
    ctx = build_context(alert)
    sig_ctx = _signal_context(str(alert.get("can_id", "")), alert)
    web_ctx = _web_search(_build_search_query(alert, ctx))

    prompt = _build_analyst_prompt(alert, ctx, sig_ctx)

    result = _try_gemini(alert, ctx, sig_ctx, web_ctx)
    if result:
        result["mode"] = "gemini"
        _flag_unsupported_figures(result, prompt + web_ctx)
        _persist(alert, result)
        return result

    result = _try_ollama(alert, ctx, sig_ctx)
    if result:
        result["mode"] = "ollama"
        _flag_unsupported_figures(result, prompt)
        _persist(alert, result)
        return result

    result = _template(alert, ctx, sig_ctx, web_ctx)
    result["mode"] = "rule_based"
    _persist(alert, result)
    return result


_RESEARCH_TRIGGERS = (
    "what is", "what are", "explain", "how does", "how do", "how is", "how are",
    "cve", "vulnerability", "vulnerabilities", "exploit", "research",
    "attack work", "real world", "real-world", "example", "case study",
    "mitigation", "prevent", "protect", "defend", "tool", "framework",
    "standard", "protocol", "regulation", "compliance", "iso ", "autosar",
    "can fd", "can-fd", "mitre", "att&ck", "history of", "background",
)
_ALERT_SPECIFIC_TRIGGERS = (
    "why", "cause", "reason", "flagged", "triggered", "this alert",
    "normal", "baseline", "expected", "compare", "this id", "this can",
    "similar", "previous", "historic",
)


def chat_reply(
    alert: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    """Return (reply_text, mode) for the given chat message.

    "mode" is "gemini" | "ollama" | "rule_based" — same contract as
    explain_alert(). The UI must not present a rule_based reply as if it were
    generative AI.
    """
    ctx = build_context(alert)
    sig_ctx = _signal_context(str(alert.get("can_id", "")), alert)
    msg_lower = message.lower()
    # Only search the web for educational/concept questions, not alert-specific queries
    needs_research = (
        any(t in msg_lower for t in _RESEARCH_TRIGGERS)
        and not any(t in msg_lower for t in _ALERT_SPECIFIC_TRIGGERS)
    )
    web_ctx = _web_search(_build_search_query(alert, ctx, message)) if needs_research else ""

    result = _try_gemini_chat(alert, ctx, sig_ctx, message, history or [], web_ctx)
    if result:
        return result, "gemini"
    result = _try_ollama_chat(alert, ctx, sig_ctx, message)
    if result:
        return result, "ollama"
    return _template_chat(alert, ctx, sig_ctx, message, web_ctx), "rule_based"


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

    # Block 1 — current anomaly. Values the detector did not report are stated
    # as missing rather than as "unknown", which a model reads as a value it may
    # fill in itself.
    anomaly_block = (
        f"CAN-ID:          {a['can_id']}\n"
        f"Vehicle state:   {a['state']}\n"
        f"Frequency:       {_measured(dev.get('frequency', a['frequency']), 'msg/s')}\n"
        f"Entropy:         {_measured(dev.get('entropy', a['entropy']))}\n"
        f"Inter-arrival:   {_measured(dev.get('time_diff', a['time_diff']), 's')}\n"
        f"Anomaly score:   {a['score']}\n"
        f"Severity:        {a['severity']}\n"
        f"Detection layer: {a['layer']}\n"
        f"Raw reason:      {a['reason']}"
        + _layer_and_burst_lines(a)
    )

    # Block 2 — normal baseline. When the detector could not identify the vehicle
    # state, context_builder falls back to the driving profile; say so, so the
    # model does not present it as this alert's own baseline.
    baseline_block = _NO_BASELINE

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
        "comparison with normal behavior, and the possible causes of the anomaly.\n"
        "The recording has no attack labels: an anomaly is traffic that differs from the "
        "training recordings, not a confirmed attack. Never state that an attack happened; "
        "name the causes that fit the evidence (for example a faulty or newly active ECU, a "
        "configuration change, or injected frames) and say which evidence would tell them apart.\n\n"
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
        "Say which known pattern it resembles, if any, without calling it an attack. "
        "Use only the figures given above: never invent or estimate a number, and where a "
        "value reads \"not measured for this alert\" say that it was not measured instead of "
        "supplying one. A value that was not measured is not zero: do not describe it as 0, and "
        "do not compare it with any range. "
        "Do not call the alert a flood, an injection or a high message rate unless a measured rate "
        "above a measured normal rate is given above; a merged alert burst is a cluster of flagged "
        "frames, not a measured rate, and a missing rate can also mean dropped or absent traffic. "
        "Keep the score and severity of the detection engine; when the layer scores differ from the "
        "final score, say that the final score is the engine's fusion, not one layer. "
        "If the evidence does not support the label, say what evidence is missing. "
        "Respond in JSON with exactly three keys: "
        "\"summary\" (one sentence finding), "
        "\"detail\" (3–4 sentences: observed vs normal, possible causes, possible impact, what to check), "
        "\"recommendation\" (1–2 sentences: immediate mitigation + long-term hardening)."
    )


def _build_analyst_chat_prompt(
    alert: dict[str, Any],
    ctx: dict[str, Any],
    sig_ctx: str,
    message: str,
    web_ctx: str = "",
) -> str:
    a = ctx["anomaly"]
    kb = ctx.get("kb")
    similar = ctx.get("similar_history", [])
    sn = ctx.get("state_normal", {})
    dev = ctx.get("deviations", {})

    freq_range = sn.get("frequency_range", ["?", "?"])
    ent_range = sn.get("entropy_range", ["?", "?"])

    kb_line = f"KB match: {kb['attack_type']} — {kb['summary'][:160]}" if kb else "KB: no strong match"
    similar_line = ""
    if similar:
        top = similar[0]
        similar_line = (
            f"\nMost similar past case: CAN-ID {top.get('can_id','?')}, "
            f"freq={top.get('frequency',0):.0f} msg/s, score={top.get('score',0):.3f}, "
            f"attack={top.get('attack_type','?')} → {top.get('summary','')[:140]}"
        )
    sig_line = f"\nECU context: {sig_ctx.split(chr(10))[0]}" if sig_ctx else ""
    web_block = f"\n\nRecent web research on this topic:\n{web_ctx}" if web_ctx else ""

    return (
        "You are the CAN Security Analyst — a senior automotive cybersecurity expert embedded in "
        "the CANvision IDS. You have deep knowledge of CAN bus protocols, ISO 15765, OBD-II, "
        "AUTOSAR, MITRE ATT&CK for ICS, known CVEs, and real-world vehicle attack campaigns.\n\n"
        "=== ACTIVE ALERT CONTEXT ===\n"
        f"CAN-ID {a['can_id']} | state={a['state']} | score={a['score']} | severity={a['severity']}\n"
        f"Frequency:       {dev.get('frequency', str(a['frequency']))}\n"
        f"Entropy:         {dev.get('entropy', str(a['entropy']))}\n"
        f"Normal baseline: {_NO_BASELINE}\n"
        f"Detection layer: {a['layer']}{_layer_and_burst_lines(a)}\n"
        f"Reason: {a['reason'][:200]}\n"
        f"{kb_line}{similar_line}{sig_line}"
        f"{web_block}\n\n"
        f"=== ENGINEER QUESTION ===\n{message}\n\n"
        "Instructions:\n"
        "- Answer in clear, detailed, conversational English. Be thorough — 3 to 6 sentences minimum.\n"
        "- You may discuss: CAN bus security, this anomaly, attack taxonomy, protocol details, "
        "CVEs, real-world incidents, investigation techniques, remediation, or general automotive cybersecurity.\n"
        "- When the web research section above is present, incorporate those findings naturally.\n"
        "- Use only the figures above. Never invent a normal range, a rate or a signal name, and never "
        "call the alert a flood or an attack without a measured rate above a measured baseline.\n"
        "- If historical cases are relevant, mention them.\n"
        "- Write as if briefing a colleague: specific, and clear about what was not measured.\n"
        "Plain text only. No JSON, no markdown headers, no bullet lists."
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


_UNKNOWN_VALUES = {"", "unknown", "none", "null", "?", "n/a", "nan"}

_NO_BASELINE = ("No measured normal rate for this identifier is available here. The knowledge "
                "base only holds generic driving-state profiles, which were not measured on this "
                "vehicle or this identifier, so no comparison with a normal range is possible.")


def _layer_and_burst_lines(a: dict[str, Any]) -> str:
    """Per-layer scores and burst facts measured by the detection engine, as prompt lines."""
    lines = ""
    ls = a.get("layer_scores")
    if ls:
        lines += "\nLayer scores:    " + ", ".join(f"{k} {v:.3f}" for k, v in ls.items())
        lines += f" (the anomaly score {a['score']} is the engine's final score)"
    b = a.get("burst")
    if b:
        win = b.get("window_s")
        lines += (f"\nAlert burst:     {b['merged_frames']} flagged frames merged into this alert"
                  + (f" within {win:g} s" if isinstance(win, (int, float)) else "")
                  + "; this is a count of flagged frames, not a measured message rate")
    return lines
# Small integers are prose ("3 tests", "one or two"), not claimed measurements.
_FIGURE_MIN = 10.0
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _measured(value: Any, unit: str = "") -> str:
    """A measured value for the prompt, or a plain statement that it is missing."""
    text = "" if value is None else str(value).strip()
    if text.lower() in _UNKNOWN_VALUES:
        return "not measured for this alert"
    return f"{text} {unit}".strip() if unit and not text.endswith(unit) else text


def _unsupported_figures(text: str, prompt: str, limit: int = 5) -> list[str]:
    """Numbers the answer states that were not in the prompt it was given.

    Deterministic and advisory: it never rewrites or rejects an answer, it only
    records that a figure has no source in the supplied data, which the smaller
    local model does occasionally. Percentages of a supplied fraction (0.97 ->
    97) count as supported, as do small integers used in prose."""
    if not text:
        return []
    given = set(_NUMBER_RE.findall(prompt.replace(",", ".")))
    given_values = set()
    for token in given:
        try:
            given_values.add(round(float(token), 4))
        except ValueError:
            continue
    unsupported: list[str] = []
    for token in _NUMBER_RE.findall(text.replace(",", ".")):
        if token in given:
            continue
        try:
            value = float(token)
        except ValueError:
            continue
        if value < _FIGURE_MIN:
            continue
        # A percentage of a supplied fraction is the same figure (0.97 -> 97%);
        # scaling by 100 is only that, never "40" justifying "4000".
        if any(abs(value - candidate) < 0.01
               or (candidate <= 1 and abs(value - candidate * 100) < 0.01)
               or (value <= 1 and abs(value * 100 - candidate) < 0.01)
               for candidate in given_values):
            continue
        if token not in unsupported:
            unsupported.append(token)
        if len(unsupported) >= limit:
            break
    return unsupported


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


# Fields the prompt reports, and the words an answer uses for each.
_MEASURED_FIELDS = (
    ("Frequency", ("frequency", "msg/s", "message rate", "msg rate")),
    ("Entropy", ("entropy",)),
    ("Inter-arrival", ("inter-arrival", "interarrival", "time diff", "inter arrival")),
)
_NOT_MEASURED = "not measured for this alert"
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def _unmeasured_claims(text: str, prompt: str, limit: int = 3) -> list[str]:
    """Sentences that quote a figure for a field the data did not measure.

    The local model sometimes reads "not measured for this alert" as zero and
    then compares that zero with the baseline. Deterministic and advisory: the
    answer is recorded, never rewritten."""
    if not text:
        return []
    missing = [
        words for label, words in _MEASURED_FIELDS
        if re.search(rf"^{label}:\s*{re.escape(_NOT_MEASURED)}", prompt, re.MULTILINE)
    ]
    if not missing:
        return []
    claims: list[str] = []
    for sentence in _SENTENCE_RE.findall(text):
        lowered = sentence.lower()
        if not any(word in lowered for word in (w for words in missing for w in words)):
            continue
        if _NOT_MEASURED in lowered or "not measured" in lowered:
            continue
        if not _NUMBER_RE.search(lowered):
            continue
        claims.append(sentence.strip())
        if len(claims) >= limit:
            break
    return claims


def _flag_unsupported_figures(result: dict[str, Any], prompt: str) -> None:
    """Record, on a model-written explanation, any figure it states that the
    prompt did not contain. Advisory only — the text is left exactly as the
    model wrote it (see _unsupported_figures)."""
    try:
        answer = " ".join(str(result.get(key, "")) for key in ("summary", "detail", "recommendation"))
        figures = _unsupported_figures(answer, prompt)
    except Exception as exc:  # never let a check break an explanation
        logger.debug("[analyst] figure check failed: %s", exc)
        return
    result["unsupported_figures"] = figures
    if figures:
        logger.warning(
            "[analyst] %s answer states figures absent from its input: %s",
            result.get("mode", "?"), ", ".join(figures),
        )
    try:
        claims = _unmeasured_claims(answer, prompt)
    except Exception as exc:
        logger.debug("[analyst] unmeasured-claim check failed: %s", exc)
        return
    result["unmeasured_claims"] = claims
    if claims:
        logger.warning(
            "[analyst] %s answer quotes figures for values the data did not measure: %s",
            result.get("mode", "?"), " | ".join(claims),
        )


def _persist(alert: dict[str, Any], result: dict[str, str]) -> None:
    try:
        save_anomaly(alert, result.get("summary", ""))
    except Exception as exc:
        logger.debug("[analyst] anomaly_store save failed: %s", exc)


# ── Gemini provider ───────────────────────────────────────────────────────────

def _try_gemini(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, web_ctx: str = ""
) -> dict[str, str] | None:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key or not _gemini_available():
        return None
    try:
        prompt = _build_analyst_prompt(alert, ctx, sig_ctx)
        if web_ctx:
            prompt += f"\n\n=== RECENT WEB RESEARCH ===\n{web_ctx}\nIncorporate relevant findings above into your analysis."
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": _GEMINI_MAX_OUTPUT_TOKENS},
        }
        raw = _http_post(_gemini_url(api_key), body, timeout=22)
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
        text = _candidate_text(candidates[0])
        result = _parse_json_response(text)
        if result:
            result["kb_match_label"] = ctx["kb"]["attack_type"] if ctx.get("kb") else ""
            logger.info("[analyst] Gemini provider succeeded.")
            return result
    except Exception as exc:
        logger.warning("[analyst] Gemini failed: %s", exc)
        _pause_gemini_after(exc)
    return None


def _try_gemini_chat(
    alert: dict[str, Any],
    ctx: dict[str, Any],
    sig_ctx: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    web_ctx: str = "",
) -> str | None:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key or not _gemini_available():
        return None
    try:
        # Build multi-turn conversation from history (last 8 turns = 16 messages)
        contents: list[dict[str, Any]] = []
        for msg in (history or [])[-16:]:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

        # Current turn — inject full context only on first message, abbreviated after
        prompt = _build_analyst_chat_prompt(alert, ctx, sig_ctx, message, web_ctx)
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        body = {
            "contents": contents,
            # Google Search Grounding: Gemini will search the web automatically when useful
            # (google_search replaces the Gemini 1.5-era google_search_retrieval tool)
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": _GEMINI_MAX_OUTPUT_TOKENS},
        }
        raw = _http_post(_gemini_url(api_key), body, timeout=22)
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
        text = _candidate_text(candidates[0])
        if text:
            grounding = candidates[0].get("groundingMetadata", {})
            queries = grounding.get("webSearchQueries", [])
            if queries:
                logger.info("[analyst] Gemini chat used search grounding: %s", queries)
            else:
                logger.info("[analyst] Gemini chat succeeded (no grounding needed).")
            return text
    except Exception as exc:
        logger.warning("[analyst] Gemini chat failed: %s", exc)
        _pause_gemini_after(exc)
    return None


# ── Ollama provider ───────────────────────────────────────────────────────────

def _try_ollama(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str
) -> dict[str, str] | None:
    prompt = _build_analyst_prompt(alert, ctx, sig_ctx)
    try:
        # First call after a while loads the model into memory, hence the timeout.
        generated = _ollama_generate(prompt, json_mode=True, temperature=0.3, max_tokens=700, timeout=90)
        if generated is None:
            return None
        model, text = generated
        result = _parse_json_response(text)
        if result:
            result["kb_match_label"] = ctx["kb"]["attack_type"] if ctx.get("kb") else ""
            logger.info("[analyst] Ollama/%s provider succeeded.", model)
            return result
        logger.warning("[analyst] Ollama/%s returned no usable JSON.", model)
    except Exception as exc:
        logger.warning("[analyst] Ollama failed: %s", exc)
    return None


def _try_ollama_chat(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, message: str
) -> str | None:
    prompt = _build_analyst_chat_prompt(alert, ctx, sig_ctx, message)
    try:
        generated = _ollama_generate(prompt, json_mode=False, temperature=0.5, max_tokens=600, timeout=90)
        if generated is None:
            return None
        model, text = generated
        if text:
            logger.info("[analyst] Ollama/%s chat succeeded.", model)
            return text
    except Exception as exc:
        logger.warning("[analyst] Ollama chat failed: %s", exc)
    return None


# ── Template fallback ─────────────────────────────────────────────────────────

def _template(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, web_ctx: str = ""
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
        f" {sig_ctx.split(chr(10))[0]}" if sig_ctx
        else f" No DBC signal names are available for {can_id} in this session."
    )
    if a.get("burst"):
        comparison += (f" This alert merges {a['burst']['merged_frames']} flagged frames that came close together;"
                       f" that is a cluster of flagged frames, not a measured message rate.")
    if a.get("layer_scores"):
        comparison += (" Layer scores: " + ", ".join(f"{k} {v:.3f}" for k, v in a["layer_scores"].items())
                       + f"; {score:.3f} is the detection engine's final score.")

    similar = ctx.get("similar_history", [])
    sim_note = ""
    if similar:
        top = similar[0]
        sim_note = (
            f" Similar historical case: {top.get('attack_type','unknown')} pattern "
            f"(score {top.get('score',0):.3f}, {top.get('state','?')} state)."
        )

    web_note = f" Additional context from online research: {web_ctx[:300]}" if web_ctx else ""

    if kb:
        return {
            "summary": (f"Anomaly on {can_id}, score {score:.3f} ({severity}). It resembles the knowledge-base "
                        f"pattern '{kb['attack_type']}'; that is not a confirmed attack.{comparison}{ecu_note}"),
            "detail":  (f"What the knowledge base says about that pattern in general (not a finding about this "
                        f"alert): {kb['detail'][:400]}{comparison} Final score {score:.3f}, dominant layer: "
                        f"{layer_desc}. Check the measured values above before assuming this pattern.{sim_note}{web_note}"),
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
            f" Score {score:.3f} exceeds the {severity.lower()} threshold.{sim_note}{web_note}"
        ),
        "recommendation": (
            "Isolate the CAN segment carrying this ID, capture raw frames for forensic analysis, "
            "and cross-reference against the vehicle's expected DBC signal map."
        ),
        "kb_match_label": "",
    }


def _template_chat(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, message: str, web_ctx: str = ""
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

    freq_range = sn.get("frequency_range", [None, None])
    ent_range = sn.get("entropy_range", [None, None])
    freq_note = dev.get("frequency", "")
    ent_note = dev.get("entropy", "")
    ecu_line = sig_ctx.split("\n")[0] if sig_ctx else ""
    ecu_note = f" Affected system: {ecu_line}." if ecu_line else f" CAN-ID {can_id} is not in the vehicle DBC signal map — possible foreign node."
    web_block = f"\n\nFrom online research: {web_ctx}" if web_ctx else ""

    # Why / cause / reason
    if any(t in q for t in ("cause", "reason", "flagged", "triggered", "why", "how did", "how was", "detect", "what happened")):
        comparison = ""
        if "ABOVE NORMAL" in freq_note:
            comparison = f" Its frequency ({a['frequency']} msg/s) is far above the expected {freq_range[0]}–{freq_range[1]} msg/s for the {a['state']} vehicle state. A flood of this identifier, from injected frames or a faulty ECU, would look like this."
        elif "BELOW NORMAL" in freq_note:
            comparison = f" Its frequency ({a['frequency']} msg/s) dropped well below the expected {freq_range[0]}–{freq_range[1]} msg/s range. A silenced or disconnected ECU, or a node in bus-off state, would look like this."
        elif "ABOVE NORMAL" in ent_note:
            comparison = f" Its payload entropy ({a['entropy']}) is higher than the expected {ent_range[0]}–{ent_range[1]} range, indicating randomized or fuzzed byte content."
        if a.get("burst"):
            comparison += (f" This alert merges {a['burst']['merged_frames']} flagged frames that came close "
                           f"together; that is a cluster of flagged frames, not a measured message rate.")
        kb_note = f" This matches the '{kb['attack_type']}' pattern in our attack knowledge base: {kb['summary']}" if kb else ""
        sig_note = f" The affected system is {ecu_line}." if ecu_line else ""
        return (
            f"CAN-ID {can_id} was flagged because its {layer_desc} is statistically abnormal "
            f"(fusion score {score:.3f}, severity: {severity}).{comparison}{kb_note}{sig_note}"
            f"{web_block}"
        )

    # Normal baseline / compare
    if any(t in q for t in ("normal", "baseline", "expected", "compare", "difference", "typical", "usual")):
        freq_dev = dev.get("frequency", f"observed: {a['frequency']}")
        ent_dev = dev.get("entropy", f"observed: {a['entropy']}")
        state_notes = sn.get("notes", "")
        notes_line = f" Note: {state_notes}" if state_notes else ""
        return (
            f"{_NO_BASELINE} "
            f"This alert on {can_id} shows: frequency {freq_dev}; entropy {ent_dev}. "
            f"The deviation pushed the fusion score to {score:.3f}, which exceeds the {severity.lower()} threshold. "
            f"{ecu_note.strip()}"
            f"{web_block}"
        )

    # Historical / similar
    if any(t in q for t in ("history", "similar", "previous", "historic", "before", "past", "seen before")):
        if similar:
            lines = []
            for h in similar:
                lines.append(
                    f"CAN-ID {h.get('can_id','?')} | {h.get('attack_type','unknown')} | "
                    f"score {h.get('score',0):.3f} | state={h.get('state','?')} — {h.get('summary','')}"
                )
            return (
                f"Found {len(similar)} similar case(s) in anomaly history:\n"
                + "\n".join(lines)
                + f"\nThe pattern on {can_id} (score {score:.3f}) is consistent with these prior events."
                + web_block
            )
        return (
            f"No similar cases have been recorded yet — this appears to be the first instance of this pattern on {can_id}. "
            f"Once more anomalies are logged, the historical similarity engine will surface matching events for comparison."
            + web_block
        )

    # Signal / ECU identity — only when question is clearly about the specific CAN-ID, not a general concept
    if any(t in q for t in ("this id", "that id", "the id", "this can", "can-id", "can id",
                            "which ecu", "what ecu", "represent", "belongs", "mapped to",
                            "what does this id", "what ecu sends", "who sends")):
        if sig_ctx:
            signals = "\n".join(sig_ctx.split("\n")[1:6])
            return (
                f"{ecu_line}\n{signals}\n\n"
                f"This ECU is currently under a {severity} alert — its {layer_desc} (score {score:.3f}) "
                f"is outside the expected operating range for the {a['state']} state."
                + web_block
            )
        return (
            f"CAN-ID {can_id} is not present in this vehicle's DBC signal map. "
            f"All legitimate ECUs in the target vehicle profile are pre-registered — an unmapped ID is itself suspicious. "
            f"Combined with its {layer_desc} (score {score:.3f}, {severity}), "
            f"this strongly suggests a spoofed or externally injected frame."
            + web_block
        )

    # Fix / mitigation
    if any(t in q for t in ("fix", "mitigate", "prevent", "recommend", "what to do", "next step", "action", "stop", "protect", "defend")):
        if kb:
            sig_note = f" Additionally, verify the signal integrity of {ecu_line}." if ecu_line else ""
            return f"{kb['recommendation']}{sig_note}{web_block}"
        return (
            f"Immediate steps: isolate the CAN segment carrying {can_id}, capture raw frames with timestamps "
            f"(tools like candump or CANalyzer), and compare injection rates against the vehicle's DBC nominal rates. "
            f"Long-term: deploy a CAN gateway with allowlist filtering for this message ID, "
            f"and consider CAN-FD with Message Authentication Codes (MACs) if the vehicle hardware supports it."
            + web_block
        )

    # Attack / anomaly type description
    if any(t in q for t in ("attack", "type", "what kind", "what sort", "what is this", "anomaly", "inject", "spoof", "fuzzy", "dos", "intrusion", "alert")):
        if kb:
            detail = kb.get("detail", "")[:500]
            return f"This is a {kb['attack_type']} event. {detail}{ecu_note} Fusion score: {score:.3f} ({severity}).{web_block}"
        return (
            f"This is a {layer_desc} anomaly on CAN-ID {can_id} — score {score:.3f} ({severity}).{ecu_note} "
            f"The {layer_desc} is the dominant indicator: observed values are outside the statistical model "
            f"trained on normal vehicle behavior. You can ask me about the cause, the baseline comparison, "
            f"similar historical cases, or what mitigation steps to take."
            + web_block
        )

    # Video / YouTube requests
    if any(t in q for t in ("youtube", "video", "tutorial", "watch", "recording", "lecture", "talk")):
        attack_label = kb["attack_type"] if kb else f"CAN bus {layer_desc}"
        search_q = urllib.parse.quote_plus(f"{attack_label} automotive cybersecurity")
        return (
            f"I cannot embed videos, but here are the best places to look:\n"
            f"  • YouTube search: '{attack_label} CAN bus attack tutorial'\n"
            f"  • YouTube search: 'automotive cybersecurity DEF CON'\n"
            f"  • Jeep Cherokee hack (Charlie Miller & Chris Valasek, DEF CON 2015) — the canonical vehicle CAN attack demo\n"
            f"  • ESCAR conference talks — the premier European automotive security venue\n"
            f"  • CyCar / automotive ISAC channel for industry-facing material\n\n"
            f"For this alert specifically ({can_id}, {severity}, {layer_desc}), the Miller/Valasek Jeep talk is directly relevant — it demonstrates exactly how spoofed CAN frames bypass the normal ECU trust model."
        )

    # Resource / read-more / link requests
    if any(t in q for t in ("read more", "internet", "online", "article", "link", "website",
                            "resource", "reference", "source", "where can i", "give me")):
        attack_label = kb["attack_type"] if kb else "CAN bus anomaly"
        wiki_q = urllib.parse.quote_plus(f"{attack_label} automotive security")
        nvd_q = urllib.parse.quote_plus(attack_label)
        return (
            f"Here are resources for further reading on this topic:\n"
            f"  • Wikipedia: en.wikipedia.org/w/index.php?search={wiki_q}\n"
            f"  • NIST NVD CVEs: services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch={nvd_q}\n"
            f"  • MITRE ATT&CK for ICS: attack.mitre.org (search '{attack_label}')\n"
            f"  • ISO/SAE 21434 (vehicle cybersecurity engineering): iso.org\n"
            f"  • UNECE WP.29 Regulation No. 155: unece.org\n"
            f"  • AUTOSAR SecOC spec: autosar.org\n"
            f"\nCurrent alert: CAN-ID {can_id}, {severity} severity, score {score:.3f} — {layer_desc}.{ecu_note}"
            + web_block
        )

    # Capability / meta questions — only pure meta queries, not action requests
    _cap_phrases = ("what can you", "what do you do", "what do you know", "capabilities",
                    "able to", "answer all", "all questions", "what questions",
                    "who are you", "what are you", "your role", "your purpose")
    _action_phrases = ("give me", "show me", "find me", "search for", "look up", "fetch", "get me")
    _is_capability = (
        any(t in q for t in _cap_phrases)
        or ("can you" in q and not any(t in q for t in _action_phrases))
    )
    if _is_capability:
        topics = [
            "the cause and detection logic for the active anomaly",
            "comparison with the normal CAN bus baseline (frequency, entropy, timing)",
            "the attack type and how it works in real vehicles (DoS, fuzzy, replay, spoofing, etc.)",
            "similar historical anomalies from the session database",
            "the ECU and signal identity of any CAN-ID in the vehicle signal map",
            "mitigation steps and incident response procedures",
            "general CAN bus security — protocols, ISO/SAE 21434, UNECE WP.29, AUTOSAR SecOC",
            "automotive cybersecurity concepts, real-world attack campaigns, and relevant CVEs",
            "MITRE ATT&CK for ICS techniques that apply to vehicle networks",
        ]
        return (
            f"Yes, I can answer a wide range of questions about this alert and automotive cybersecurity. "
            f"Here is what I cover:\n"
            + "\n".join(f"  • {t}" for t in topics)
            + f"\n\nActive alert context: CAN-ID {can_id}, {severity} severity, score {score:.3f} — {layer_desc}."
            + (f" {ecu_note.strip()}" if ecu_note else "")
            + " Ask me anything."
        )

    # General automotive / CAN security question (broad topic support)
    if web_ctx:
        return (
            f"Regarding your question about '{message[:80]}': "
            f"Here is what I found from online research combined with the active alert context "
            f"(CAN-ID {can_id}, {severity} severity, score {score:.3f}):"
            f"{web_block}"
        )

    # Default fallback
    freq_dev = dev.get("frequency", f"{a['frequency']} msg/s")
    return (
        f"Active anomaly — CAN-ID {can_id}: {layer_desc}, fusion score {score:.3f} ({severity}). "
        f"Frequency: {freq_dev}.{ecu_note} "
        f"Ask me about the cause, attack type, normal baseline, historical cases, or mitigation steps."
    )

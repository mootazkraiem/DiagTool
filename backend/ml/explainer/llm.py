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
import re
import urllib.request
import urllib.error
import urllib.parse
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


def _check_ollama_available() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


_OLLAMA_AVAILABLE: bool = _check_ollama_available()

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
    sig_ctx = _signal_context(can_id)
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
    web_ctx = _web_search(_build_search_query(alert, ctx))

    result = _try_gemini(alert, ctx, sig_ctx, web_ctx)
    if result:
        _persist(alert, result)
        return result

    result = _try_ollama(alert, ctx, sig_ctx)
    if result:
        _persist(alert, result)
        return result

    result = _template(alert, ctx, sig_ctx, web_ctx)
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
) -> str:
    """Return a detailed analyst reply, optionally using prior conversation history."""
    ctx = build_context(alert)
    sig_ctx = _signal_context(str(alert.get("can_id", "")))
    msg_lower = message.lower()
    # Only search the web for educational/concept questions, not alert-specific queries
    needs_research = (
        any(t in msg_lower for t in _RESEARCH_TRIGGERS)
        and not any(t in msg_lower for t in _ALERT_SPECIFIC_TRIGGERS)
    )
    web_ctx = _web_search(_build_search_query(alert, ctx, message)) if needs_research else ""

    result = _try_gemini_chat(alert, ctx, sig_ctx, message, history or [], web_ctx)
    if result:
        return result
    result = _try_ollama_chat(alert, ctx, sig_ctx, message)
    if result:
        return result
    return _template_chat(alert, ctx, sig_ctx, message, web_ctx)


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
        "\"detail\" (3–4 sentences: observed vs normal, attack vector, real-world impact, forensic indicators), "
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
        f"Normal freq ({a['state']}): {freq_range[0]}–{freq_range[1]} msg/s\n"
        f"Normal entropy:  {ent_range[0]}–{ent_range[1]}\n"
        f"Detection layer: {a['layer']}\n"
        f"Reason: {a['reason'][:200]}\n"
        f"{kb_line}{similar_line}{sig_line}"
        f"{web_block}\n\n"
        f"=== ENGINEER QUESTION ===\n{message}\n\n"
        "Instructions:\n"
        "- Answer in clear, detailed, conversational English. Be thorough — 3 to 6 sentences minimum.\n"
        "- You may discuss: CAN bus security, this anomaly, attack taxonomy, protocol details, "
        "CVEs, real-world incidents, investigation techniques, remediation, or general automotive cybersecurity.\n"
        "- When the web research section above is present, incorporate those findings naturally.\n"
        "- Compare observed values to the normal baseline when numbers are involved.\n"
        "- If historical cases are relevant, mention them.\n"
        "- Write as if briefing a colleague — confident, specific, no hedging.\n"
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
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str, web_ctx: str = ""
) -> dict[str, str] | None:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        prompt = _build_analyst_prompt(alert, ctx, sig_ctx)
        if web_ctx:
            prompt += f"\n\n=== RECENT WEB RESEARCH ===\n{web_ctx}\nIncorporate relevant findings above into your analysis."
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 700},
        }
        raw = _http_post(_GEMINI_URL.format(key=api_key), body, timeout=22)
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
    alert: dict[str, Any],
    ctx: dict[str, Any],
    sig_ctx: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    web_ctx: str = "",
) -> str | None:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
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
            "tools": [{"google_search_retrieval": {"dynamic_retrieval_config": {"mode": "MODE_DYNAMIC", "dynamic_threshold": 0.4}}}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 700},
        }
        raw = _http_post(_GEMINI_URL.format(key=api_key), body, timeout=22)
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
            grounding = candidates[0].get("groundingMetadata", {})
            queries = grounding.get("webSearchQueries", [])
            if queries:
                logger.info("[analyst] Gemini chat used search grounding: %s", queries)
            else:
                logger.info("[analyst] Gemini chat succeeded (no grounding needed).")
            return text
    except Exception as exc:
        logger.warning("[analyst] Gemini chat failed: %s", exc)
    return None


# ── Ollama provider ───────────────────────────────────────────────────────────

def _try_ollama(
    alert: dict[str, Any], ctx: dict[str, Any], sig_ctx: str
) -> dict[str, str] | None:
    if not _OLLAMA_AVAILABLE:
        return None
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
    if not _OLLAMA_AVAILABLE:
        return None
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

    web_note = f" Additional context from online research: {web_ctx[:300]}" if web_ctx else ""

    if kb:
        return {
            "summary": f"{kb['attack_type']} pattern detected on {can_id} — score {score:.3f} ({severity}).{comparison}{ecu_note}",
            "detail":  f"{kb['detail'][:500]}{comparison} Fusion score {score:.3f} via {layer_desc}.{sim_note}{web_note}",
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
            comparison = f" Its frequency ({a['frequency']} msg/s) is far above the expected {freq_range[0]}–{freq_range[1]} msg/s for the {a['state']} vehicle state — a hallmark of flooding attacks."
        elif "BELOW NORMAL" in freq_note:
            comparison = f" Its frequency ({a['frequency']} msg/s) dropped well below the expected {freq_range[0]}–{freq_range[1]} msg/s range, suggesting a suppression or bus-off attack."
        elif "ABOVE NORMAL" in ent_note:
            comparison = f" Its payload entropy ({a['entropy']}) is higher than the expected {ent_range[0]}–{ent_range[1]} range, indicating randomized or fuzzed byte content."
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
            f"In the '{a['state']}' driving state, the CAN bus normally runs at "
            f"{freq_range[0]}–{freq_range[1]} msg/s with entropy {ent_range[0]}–{ent_range[1]}.{notes_line} "
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

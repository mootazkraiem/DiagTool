from __future__ import annotations


def print_progress(step: str, context: str, idx: int, total: int, extra: str = "") -> None:
    if total <= 0:
        total = 1
    percent = (idx / total) * 100
    msg = f"[PROGRESS][{step.upper()}][{context}] {percent:.1f}% ({idx}/{total})"
    if extra:
        msg += f" | {extra}"
    print(msg, end="\r", flush=True)

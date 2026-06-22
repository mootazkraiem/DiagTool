from __future__ import annotations

import textwrap
from pathlib import Path


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf(lines: list[str], output: Path) -> None:
    page_width = 595
    page_height = 842
    margin_left = 48
    margin_top = 64
    line_height = 14
    max_lines_per_page = 50

    pages: list[list[str]] = []
    for i in range(0, len(lines), max_lines_per_page):
        pages.append(lines[i : i + max_lines_per_page])
    if not pages:
        pages = [["(empty report)"]]

    objects: list[str] = []

    # 1: Catalog, 2: Pages
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    kid_refs = []

    next_obj = 3
    page_objs: list[int] = []
    content_objs: list[int] = []
    font_obj_id = 3 + len(pages) * 2

    for _ in pages:
        page_obj = next_obj
        content_obj = next_obj + 1
        page_objs.append(page_obj)
        content_objs.append(content_obj)
        kid_refs.append(f"{page_obj} 0 R")
        next_obj += 2

    objects.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kid_refs)}] >>")

    for page_idx, page_lines in enumerate(pages):
        page_obj = page_objs[page_idx]
        content_obj = content_objs[page_idx]

        stream_lines = ["BT", "/F1 11 Tf"]
        y = page_height - margin_top
        for line in page_lines:
            stream_lines.append(f"1 0 0 1 {margin_left} {y} Tm ({_escape_pdf_text(line)}) Tj")
            y -= line_height
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)

        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_obj_id} 0 R >> >> /Contents {content_obj} 0 R >>"
        )
        objects.insert(page_obj - 1, page_dict)
        objects.insert(content_obj - 1, f"<< /Length {len(stream.encode('latin-1', errors='replace'))} >>\nstream\n{stream}\nendstream")

    objects.insert(font_obj_id - 1, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # Serialize PDF
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1", errors="replace"))

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("latin-1"))

    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("latin-1")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf)


def build_report_lines() -> list[str]:
    paragraphs = [
        "CAN AI Diagnostic Backend - Professional Upgrade Report",
        "",
        "1) System Architecture",
        "Pipeline: Multi-format CAN Parser -> Feature Engineering -> StandardScaler -> IsolationForest"
        " anomaly detection -> KMeans clustering -> anomaly intelligence -> LLM explanation -> FastAPI endpoints.",
        "The service is vehicle-agnostic and does not require DBC decoding.",
        "",
        "2) Why Isolation Forest",
        "Isolation Forest is unsupervised and suitable for mixed, unlabeled CAN telemetry where normal and abnormal"
        " boundaries are unknown. It isolates rare behaviors using random partitioning and scales well for high-volume logs.",
        "Random Forest is supervised; it requires labeled classes and is therefore not a fit for cold-start anomaly detection.",
        "",
        "3) Feature Engineering",
        "Core features: time_diff, message_frequency, window_frequency, byte_mean, byte_max, byte_std.",
        "Advanced features: rolling_mean_8, rolling_std_8, payload_entropy.",
        "These features capture timing behavior, bus activity intensity, and payload variability without OEM-specific decoding.",
        "",
        "4) Improvements Implemented",
        "- Parser expanded for candump, ASC Rx/Tx d lines, and generic ID#DATA fallback.",
        "- Parse quality metrics added (total/parsed/skipped lines).",
        "- Time-window frequency and rolling statistics added.",
        "- Entropy feature added for payload variability.",
        "- IsolationForest anomaly scoring converted to normalized severity (0..1).",
        "- Automatic cluster count selection (elbow-style), plus cluster profiles.",
        "- Model persistence added via joblib save/load.",
        "- FastAPI hardened with request/response schemas and typed errors.",
        "- Added /metrics endpoint for uptime, request counts, anomaly totals, and average latency.",
        "- Added caching for repeated file analysis using SHA256 fingerprints.",
        "- Added structured anomaly type classification: frequency/timing/data/pattern.",
        "- LLM prompt upgraded to include severity, type, confidence, and cluster profile.",
        "",
        "5) Limitations",
        "- No DBC decoding by design. This preserves portability but reduces semantic signal naming precision.",
        "- Statistical clusters are behavioral groups, not guaranteed OEM subsystem labels.",
        "- LLM explanations depend on API availability and key configuration.",
        "",
        "6) Example Output",
        '{"can_id":"0x1A2","severity":0.92,"type":"frequency_anomaly","cluster":2,"confidence":"high"}',
        "LLM output schema:",
        '{"causes":"...","risks":"...","recommendations":"..."}',
        "",
        "7) Real-world Relevance",
        "This backend supports fleet-scale EV diagnostics, rapid anomaly triage, and explainable maintenance workflows.",
        "It is designed for direct integration with external clients (including C# frontends) using stable API contracts.",
    ]

    wrapped: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(paragraph, width=95, break_long_words=False, replace_whitespace=False))
    return wrapped


def main() -> None:
    lines = build_report_lines()
    output = Path("docs") / "CAN_AI_Diagnostic_Report.pdf"
    _build_pdf(lines, output)
    print(f"Generated: {output}")


if __name__ == "__main__":
    main()

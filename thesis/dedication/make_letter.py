"""The dedication page: the text in a classic book italic, with the handwritten signature.

    python make_letter.py

Reads the text from dedication_draft.md (between the two lines of dashes; paragraphs
are separated by an empty line) and writes ../images/dedication_letter.pdf (A4),
which chapters/00_dedication.tex places on the whole page. The text is set in
EB Garamond Italic (SIL Open Font License, see fonts/), at the largest size that
fits on one page; the signature is signature.png.
"""
from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "images" / "dedication_letter.pdf"
TITLE = "Dedication"
INK = (0.1, 0.1, 0.1)
W_PT, H_PT = 595.28, 841.89          # A4
LEFT, RIGHT, TOP, BOTTOM = 71, W_PT - 71, 84, H_PT - 64
SIG_W = 165                          # width of the signature (pt)


def read_paragraphs() -> list[str]:
    text = (HERE / "dedication_draft.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    cuts = [i for i, l in enumerate(lines) if l.strip() == "---"]
    body = "\n".join(lines[cuts[0] + 1:cuts[1]])
    return [" ".join(p.split()) for p in body.split("\n\n") if p.strip()]


def wrap(words: list[str], font: fitz.Font, size: float, width: float) -> list[str]:
    lines, line = [], ""
    for w in words:
        trial = f"{line} {w}" if line else w
        if line and font.text_length(trial, fontsize=size) > width:
            lines.append(line)
            line = w
        else:
            line = trial
    lines.append(line)
    if len(lines) > 1 and " " not in lines[-1]:          # no word alone on the last line
        head, moved = lines[-2].rsplit(" ", 1)
        lines[-2], lines[-1] = head, f"{moved} {lines[-1]}"
    return lines


def layout(paras: list[str], font: fitz.Font, size: float) -> tuple[list[tuple[float, str]], float]:
    """Baselines of every line for one font size, and the baseline of the last line."""
    y = TOP + 34 + 2.0 * size
    out = []
    for para in paras:
        for line in wrap(para.split(), font, size, RIGHT - LEFT):
            out.append((y, line))
            y += 1.5 * size
        y += 0.75 * size
    return out, y - 2.25 * size


def main() -> None:
    paras = read_paragraphs()
    typed = fitz.Font(fontfile=str(HERE / "fonts" / "EBGaramond-Italic.ttf"))
    sig = fitz.Pixmap(str(HERE / "signature.png"))
    sig_h = SIG_W * sig.height / sig.width
    size = 13.0
    while True:
        lines, last = layout(paras, typed, size)
        if last + 18 + sig_h <= BOTTOM or size <= 8.5:
            break
        size -= 0.25
    if last + 18 + sig_h > BOTTOM:
        raise RuntimeError("the text does not fit on one page; shorten it")

    doc = fitz.open()
    page = doc.new_page(width=W_PT, height=H_PT)
    tw = fitz.TextWriter(page.rect, color=INK)
    tw.append((LEFT, TOP + 24), TITLE, font=typed, fontsize=32)
    for y, line in lines:
        tw.append((LEFT, y), line, font=typed, fontsize=size)
    tw.write_text(page)
    top = last + 18
    page.insert_image(fitz.Rect(RIGHT - SIG_W, top, RIGHT, top + sig_h), filename=str(HERE / "signature.png"))
    doc.save(OUT, garbage=3, deflate=True)
    print(f"written {OUT}: text at {size:g} pt, signature ends at {top + sig_h:.0f} pt of {H_PT:.0f}")


if __name__ == "__main__":
    main()

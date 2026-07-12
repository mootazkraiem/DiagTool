import re
import sys

FILES = [
    "chapters/00_abstract.tex",
    "chapters/00_general_introduction.tex",
    "chapters/00_general_conclusion.tex",
    "chapters/chapter1_general_framework.tex",
    "chapters/chapter2_requirements.tex",
    "chapters/chapter3_design.tex",
    "chapters/chapter4_implementation.tex",
    "chapters/chapter5_validation.tex",
    "appendices/appendixA_api_endpoints.tex",
    "appendices/appendixB_configuration.tex",
    "appendices/appendixC_datasets.tex",
    "appendices/appendixD_additional_validation.tex",
    "appendices/appendixE_data_sources.tex",
]

CMDS = ["texttt", "emph"]

def find_matching_brace(s, open_pos):
    depth = 0
    for i in range(open_pos, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1

def strip_commands(text):
    changed = 0
    for cmd in CMDS:
        pattern = "\\" + cmd + "{"
        out = []
        i = 0
        while True:
            idx = text.find(pattern, i)
            if idx == -1:
                out.append(text[i:])
                break
            out.append(text[i:idx])
            brace_open = idx + len(cmd) + 1  # position of '{'
            brace_close = find_matching_brace(text, brace_open)
            if brace_close == -1:
                out.append(text[idx:idx + len(pattern)])
                i = idx + len(pattern)
                continue
            inner = text[brace_open + 1:brace_close]
            out.append(inner)
            changed += 1
            i = brace_close + 1
        text = "".join(out)
    return text, changed

DRY_RUN = "--apply" not in sys.argv

total = 0
for f in FILES:
    with open(f, "r", encoding="utf-8") as fh:
        text = fh.read()
    new_text, n = strip_commands(text)
    print(f"{f}: {n} commands stripped")
    total += n
    if not DRY_RUN and new_text != text:
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(new_text)
print("TOTAL:", total, "(dry-run)" if DRY_RUN else "(applied)")

# Things to fill in before submission

This is the single checklist of everything left as a placeholder in the report.
There are currently no `\todofill` placeholders left anywhere in the document —
the official ESPRIT cover template only asks for the specialty (already filled
in as "INFORMATION TECHNOLOGY"), not a separate engineering-track line.

## 1. Administrative / personal information — DONE

- [x] **Student full name** — Mohamed Mootaz Ben Kraiem — `chapters/00_cover.tex`, `config.tex`.
- [x] **Academic supervisor name** — Nadia Boulifa — `chapters/00_cover.tex`.
- [x] **Company supervisor name** — Hamda Guizani — `chapters/00_cover.tex`.
- [x] **Host company name** — Capgemini Tunisia — `chapters/00_cover.tex`, `chapters/chapter1_general_framework.tex`.
- [x] **Academic year** — 2025/2026 — `chapters/00_cover.tex`.
- [x] **Capgemini department / team** — Automotive, Battery Management Systems (BMS) —
      `chapters/00_cover.tex`, `chapters/chapter1_general_framework.tex`.
- [x] **Acknowledgements text** — rewritten in `chapters/00_acknowledgements.tex`, thanking family.
- [x] **PDF metadata author** — `config.tex`, `\hypersetup{pdfauthor=...}` now set.

## 2. Screenshots — DONE

All screenshots are real captures from the running application (`thesis/images/screenshots/`),
taken against the actual 97,741-frame Kia EV6 recording used in Chapter 5.

## 3. Cover pages — DONE

Both covers now use the real, official ESPRIT artwork, extracted directly from the filled
template you provided (`Page Garde Rapport Stage(Ang).pdf`) and saved to `thesis/images/`:
`cover_front_bg.jpg`, `cover_back_bg.jpg`, `cover_capgemini_logo.jpg` (the real Capgemini
Engineering logo). The front cover (`chapters/00_cover.tex`) overlays the variable text
(year, specialty, title, author, supervisors) at the exact positions used in the original
template; the back cover (`chapters/00_backcover.tex`, wired in as the very last page in
`main.tex`) is the artwork as-is, with no overlay needed. The UNESCO/CTI/EUR-ACE/CGE
accreditation logos are already baked into the front-cover background image itself.

The signature/validation form from that same PDF (student/company/academic supervisor
sign-off) was intentionally **not** inserted anywhere in the report, per your instruction.
If you need it included later, it normally goes right after the front cover.

## 4. Styling — DONE

- [x] Removed the red accent color from body text: `\todofill` is now plain bold (no color),
      and hyperref `linkcolor`/`citecolor` (TOC, List of Figures/Tables, cross-references,
      citations) are now blue instead of red — `config.tex`. The cover page's "2025 - 2026"
      stays red because that red is baked into the real official ESPRIT artwork itself, not
      a styling choice made in this document.
- [x] Added a "Technologies used" section with a by-category table (languages, frontend,
      backend, ML, data processing, persistence, AI explanation, export, docs/diagrams,
      version control) — `chapters/chapter3_design.tex`, Section~3.2 (Table~\ref{tab:tech-used}).
- [x] Added a one-page "Data Sources Summary" appendix (dataset, vehicle/origin, source) as
      the last content page before the back cover — `appendices/appendixE_data_sources.tex`.

## 5. Diagrams — you're recreating these yourself

You mentioned you plan to recreate all the PlantUML diagrams because they look
AI-generated, even though they're accurate. No action needed from me here unless
you want help with a specific one — just let me know.

## 6. Optional / worth double-checking

- [ ] Bibliography (`references.bib`) only includes well-known, verifiable sources (ISO/SAE
      standards, Isolation Forest, K-Means, ROAD dataset, Car-Hacking/GIDS, scikit-learn,
      FastAPI, ASAM MDF). Add any course-specific or company-specific references your
      supervisor expects.

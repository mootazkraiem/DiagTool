# Things to fill in before submission

This is the single checklist of everything left as a placeholder in the report.
Everything below is marked in red in the compiled PDF as **[TO FILL: ...]**.
Search for `\todofill` in the `.tex` files to jump straight to each spot.

## 1. Administrative / personal information (blocking — needed for the cover page and Chapter 1)

No host company, student name, supervisor names, or dates were found anywhere in the
repository, so these were left as placeholders rather than invented.

- [ ] **Student full name** — `chapters/00_cover.tex`
- [ ] **Department / engineering track name** (e.g. "Computer Science Engineering") — `chapters/00_cover.tex`
- [ ] **Academic supervisor name** — `chapters/00_cover.tex`, `chapters/00_acknowledgements.tex`
- [ ] **Company supervisor name**, or "N/A" if this was an independent project — `chapters/00_cover.tex`
- [ ] **Host company name**, or "Independent project" — `chapters/00_cover.tex`, `chapters/chapter1_host_company.tex`
- [ ] **Academic year** (e.g. "2025/2026") — `chapters/00_cover.tex`
- [ ] **Company presentation** (half page: sector, size, products/services, location) — `chapters/chapter1_host_company.tex`,
      section "Presentation". If there was no host company, replace this with a short paragraph
      saying so and describing the academic framework instead.
- [ ] **Department / service / team** the project was carried out in, and its role — `chapters/chapter1_host_company.tex`
- [ ] **Acknowledgements text** — personalize `chapters/00_acknowledgements.tex` in your own words;
      it currently only has a generic skeleton.

## 2. Screenshots (8 total)

Every one of these is marked with a boxed "INSERT SCREENSHOT HERE" placeholder in the PDF,
with a caption already written describing what to capture. Locations:

- [ ] Home screen — Live Session / Offline Import choice, backend status — `chapters/chapter5_implementation.tex`
- [ ] Log Playback view during a replay — `chapters/chapter5_implementation.tex`
- [ ] Anomaly Intel view — alert list + layer bars + Chat with AI — `chapters/chapter5_implementation.tex`
- [ ] Anomaly Intel view after correction (post-fix, correctly labelled alerts) — `chapters/chapter6_validation.tex`
- [ ] Dashboard view during a completed replay — `appendices/appendixD_additional_validation.tex`
- [ ] Settings view — `appendices/appendixD_additional_validation.tex`
- [ ] Exported CSV opened in a spreadsheet — `appendices/appendixD_additional_validation.tex`
- [ ] Exported PDF report, first page — `appendices/appendixD_additional_validation.tex`

## 3. Optional / worth double-checking

- [ ] The cover page currently uses a generic ESPRIT title-page layout built from scratch
      (no official template file was provided). If ESPRIT gives you a `.docx`/`.tex` template,
      swap `chapters/00_cover.tex` for it.
- [ ] Bibliography (`references.bib`) only includes well-known, verifiable sources (ISO/SAE
      standards, Isolation Forest, K-Means, ROAD dataset, Car-Hacking/GIDS, Koscher et al.,
      Miller & Valasek, scikit-learn, FastAPI, ASAM MDF, opendbc). Add any course-specific or
      company-specific references your supervisor expects.

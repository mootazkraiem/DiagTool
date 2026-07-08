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
- [ ] **PDF metadata author** — `config.tex`, the `\hypersetup{pdfauthor=...}` line still says
      `PLACEHOLDER-STUDENT-NAME`. Purely cosmetic (shows up in the PDF's "Properties" dialog),
      but worth a 10-second fix once you have your final name.

## 2. Screenshots — DONE

All screenshots are now real captures from the running application (`thesis/images/screenshots/`),
taken against the actual 97,741-frame Kia EV6 recording used in Chapter 6: Home, Dashboard,
Telemetry, Diagnostics, Settings, Log Playback (loaded replay), Anomaly Intel (with a freshly
generated, correctly-matched AI explanation), the exported CSV (reconstructed preview — see the
new CSV-export note in Chapter 6's Limitations and Appendix D), and the exported PDF report.
Nothing left to do here unless you want to swap any of them for a different moment in the app.

## 3. Optional / worth double-checking

- [ ] The cover page currently uses a generic ESPRIT title-page layout built from scratch
      (no official template file was provided). If ESPRIT gives you a `.docx`/`.tex` template,
      swap `chapters/00_cover.tex` for it.
- [ ] Bibliography (`references.bib`) only includes well-known, verifiable sources (ISO/SAE
      standards, Isolation Forest, K-Means, ROAD dataset, Car-Hacking/GIDS, Koscher et al.,
      Miller & Valasek, scikit-learn, FastAPI, ASAM MDF, opendbc). Add any course-specific or
      company-specific references your supervisor expects.

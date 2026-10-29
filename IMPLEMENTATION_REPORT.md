# MolTel — Implementation Report

Against `MolTel_Qoder_Implementation_Spec.md`. Every claim below is tied to a
check that was actually run; what could not be checked is listed under
*Blocked items* rather than described as working.

---

## 1. What changed, section by section

### §1 Rebrand — Drug Intelligence → MolTel
Browser title, header wordmark, generated report headers, export file names and
document metadata all say MolTel. No `Drug Intelligence` string remains in
user-facing UI or in a generated file.

### §3 Dossier audit
- **§3.1** The dossier is seven numbered sections; the duplicated trial
  narrative that appeared under both "Clinical Development" and "Evidence" is
  gone, and each section states which records it describes.
- **§3.2** Evidence categories come from `services/evidence_strength.py` reading
  each record's own publication-type metadata, with the criteria shown next to
  the class. When OpenRouter synthesis fails or is unconfigured, the response is
  `ai_synthesized: false` plus an explicit banner saying which sections were not
  produced — a failed synthesis is never rendered as completed analysis.

### §4 Trial data quality
- `services/trial_taxonomy.py` is the single place a registry status or phase
  gets a meaning. Phase and status stay separate dimensions.
- `EARLY_PHASE1`, `NA`, `PHASE1/PHASE2` keep their identity: `NA` is "Not
  Applicable", never "Unknown"; a combined phase is charted as
  "Phase 1 + Phase 2".
- Unrecognised future status values are counted and displayed, not dropped.
- Trials are deduplicated by NCT ID. Overlapping categories (Ongoing ⊃
  Recruiting) are labelled as overlapping and never summed.
- **§4.4** Interventions, sponsors and lead sponsors are separate fields; a
  candidate is never inferred from a sponsor name and an unknown developer is
  left unknown.

### §5 Candidate dashboard
`services/candidate_analytics.py` extracts interventions as candidate entities
(deduplicated by normalised name) and reports trial counts, phases, statuses,
sponsors and first/last retrieval timestamps per candidate. Candidate counts are
kept visibly distinct from trial counts in every panel and export.
`components/trials/CandidateDevelopmentPanel.tsx` and `ClinicalTrialDashboard.tsx`
render them; clicking a chart segment or a class chip opens the records behind it.

### §6 Disease and subtype search
- Search mode is chosen on the landing page (`compound` / `disease` / `target`)
  and shown on the dossier. PubChem and openFDA are only queried for a compound
  name; a disease query is resolved through EMBL-OLS MONDO instead.
- Subtypes come only from a **stated** relation: a MONDO `is_a` child, or
  registry condition wording that names the parent. A MONDO *search hit* is
  never treated as a subtype. Selecting a subtype re-scopes trials, candidates,
  companies, papers and targets, and each panel says how many of the retrieved
  set carried that wording. An empty subtype result is explained as "these
  retrieved records do not name it", not as "nothing exists".

### §7 Literature discovery and ranking
`services/literature_view.py` holds every rule; the browser re-ranks by posting
the records it already holds to `POST /api/literature/views`, so no rule exists
twice and no source is re-queried when a tab changes.

| View | Ordered by |
|---|---|
| Most relevant | Query words in title (×3) and abstract, scaled by the reported design, +0.1 if published within two years |
| Latest | The publication date the source states, most recent first |
| Strongest evidence | The study design the source reports, on a fixed 13-rung ladder; ties broken by date |
| Reviews & guidelines | Date, restricted to records whose own types name a review, guideline or meta-analysis |

- **Publication date is never confused with indexing date.** `published_on`
  keeps the precision the source stated (`day`/`month`/`year`) and is displayed
  as stated — a year-only date is not padded to look exact; it sorts at the
  start of the year and says so. `indexed_on` + `indexed_field` (PubMed
  `entrez` history, Europe PMC `firstIndexDate`/`dateOfCreation`) are separate
  fields and never decide the Latest order.
- **No fabricated quality score.** The strongest-evidence view orders designs and
  states "It is not a score for how reliably this study was conducted"; a test
  asserts `relevance_score == 0.0` across that view. Europe PMC's `citedByCount`
  is deliberately not parsed.
- "Show why each record is here" prints each record's ranking reasons, quoting
  the matched query terms, the source's own publication types, its ladder
  position, its stated date and its indexing date. Every `reason.source_field`
  is asserted to be a real `EvidenceItem` field.
- Filters (published range, study scope, source, publication type, access,
  subtype wording, target wording) each report how many records they removed and
  what the removal cannot see. Facets are counted **before** filtering, so the
  dropdown counts stay meaningful while a filter is on. "Not stated" access is
  never filtered as closed access.

### §7.1 Publication deduplication
Union-find over PMID / PMCID / DOI only (`PMC1122334` and `1122334` fold to one
form). Titles and author lists are never compared. A merged publication keeps
every source link, identifier, author string and publication type from the
records it was built from, and carries `merged_records` + `merged_sources`, shown
per row. The panel reports records received → publications, records merged,
cross-database merges and records with no identifier. Corrections, editorials,
letters and retractions are labelled from the source's own types and the
retraction is selectable as a filter rather than silently merged into "review".

The merge counts cover publications only: a regulatory passage is not a
publication that was folded into one, so the dossier's counts are recovered from
the literature records' own provenance
(`evidence_normalizer.report_from_provenance`). Live check: 50 retrieved records
→ 45 publications, 5 cross-database merges — identical in the panel banner, the
CSV scope line and `POST /api/literature/views`.

### §8 Exports
Four separate actions: Download PDF, Download Word (.docx), Export Data (CSV) per
dataset, and Print. Neither download opens the print dialog. Charts are
rasterised to PNG at 2× and embedded, so they survive offline. CSV and the Word
table carry the same stated-precision dates, indexing-field labels, merge counts
and per-source links as the panel, and every dataset names its retrieval
timestamp and scope.

### §9 Dashboard quality, §10 provenance
Card grid with aligned chart cards and horizontal bars instead of rotated
labels; tooltips on counts; consistent colour semantics; keyboard-focusable
controls with `aria-pressed` on the view tabs; empty/loading/partial/failed
states per source. Source facts, normalised classifications and AI interpretation
are labelled distinctly, original values are preserved alongside normalised ones,
and each source fails independently so one outage cannot erase another's results.

---

## 2. Checks run, and results

### Automated

```
cd drug-intelligence/backend && python -m pytest -q
→ 185 passed, 1 warning in 47.38s

cd drug-intelligence/frontend && npx tsc --noEmit
→ exit 0

cd drug-intelligence/frontend && npx next build
✓ Compiled successfully   ✓ Generating static pages (6/6)
/dossier   145 kB    first-load JS 232 kB
→ exit 0
```

`185 passed` covers 12 modules; the literature work added `test_literature_view.py`
(26 tests), 13 merge/dedup tests in `test_normalizer.py`, 4 date/identifier/open-
access parser tests in `test_parsers.py` and the ranker/view rewiring in
`test_ranker.py`. No existing test was deleted or relaxed. External APIs are
mocked with `respx`; no test reads the OpenRouter key or spends AI credits.

### Live, against the real sources
A scratch backend (`uvicorn main:app`, port 8010, `OPENROUTER_API_KEY` left empty,
no `--reload`) and `next start -p 3005` were used so the user's own servers on
8000/3000 were never touched. Both were stopped afterwards and
`frontend/.env.local` was restored to `NEXT_PUBLIC_API_URL=http://localhost:8000`
before the final build.

Verified in the rendered dossier (PubMed, Europe PMC, ClinicalTrials.gov,
UniProt, PubChem, openFDA, EMBL-OLS MONDO all live):

| Check | Result |
|---|---|
| Four view tabs re-order the same held records | ✔ Most relevant → Latest → Strongest → Reviews, each via `POST /api/literature/views`, no source re-queried |
| Latest ordering uses stated publication date | ✔ 2026-10-23, 2026-10-23, 2026-10-22 … |
| Published vs indexed shown separately | ✔ `2026-10-31 indexed 2026-10-18 (entrez)` vs `(firstIndexDate)` |
| Ranking reasons | ✔ design rung with "(position 2 of 13 in this ordering)" + not-a-score disclaimer |
| Reviews view honesty | ✔ "13 of 47 shown"; "34 of the records … name no review, guideline or meta-analysis type" |
| Filters + exclusion counts | ✔ scope=clinical → "Removed — 42 by clinical studies of people"; "Clear filters" restores 47/47 |
| Merge banner + per-row provenance | ✔ "50 records merged into 45 publications (5 across both databases)"; row "3 records merged (PubMed, EuropePMC)" with 4 labelled links |
| Pagination | ✔ 15 rows → "Show 15 more of 45 publication(s)" → 30 |
| All three search modes | ✔ compound (`aspirin`), disease (`NSCLC immunotherapy`, `Alzheimer disease`), target (`TRPC5`, UniProt 3 records) |
| Subtype scoping of the literature panel | ✔ "LITERATURE CARRYING THIS WORDING — 2 OF 50 RETRIEVED" renders the full view tabs |
| Console errors | ✔ none |
| CSV (publications dataset) | ✔ 22 columns incl. `published_date_as_stated`, `published_date_precision`, `indexed_date_field`, `open_access_as_stated`, `records_merged_into_this_publication`, `all_source_links`; header notes state the ordering key is not a quality score |
| Word export | ✔ valid zip; table headers `Title / Published / Indexed / Source / Evidence type / Records merged / Link`; rows carry `(firstIndexDate)` vs `(entrez)` and "2 records (PubMed, EuropePMC)" |
| PDF export | ✔ valid `%PDF` … `%%EOF`; 7 embedded chart images; text extracted from inflated streams contains the same literature columns |
| Charts offline | ✔ 7 PNGs at 1520×368…1520×1036, valid PNG signatures |

---

## 3. Known limitations and blocked items

**Blocked — the AI synthesis path is unverified.** Every OpenRouter key supplied
so far was rejected (HTTP 402 on paid models; the remaining `:free` models
returned no parseable completion). With no working key, `ai_synthesized` is
`false` on every dossier produced, so the narrative sections, contradiction
panel and gap analysis have only been tested through their deterministic fallback
and mocked-response unit tests — not end to end. `OPENROUTER_MODEL` must be a
`:free` variant with `reasoning` disabled.

**Not claimed:**
- Literature views are verified for PubMed and Europe PMC, the two sources this
  app asks for papers. No other literature source is consulted, so "all the
  literature on a topic" is never implied — every panel says it describes the
  retrieved set.
- A paper that reviews a topic without the source labelling it a review cannot
  be detected; the reviews view reports how many records it left out instead.
- Year-only dates sort at 1 January of that year for ordering only; the UI and
  exports still display the year alone.
- Subtype detection is limited to a stated ontology relation or the registry's
  own condition wording. It will miss a subtype the sources describe only in
  prose.
- Europe PMC `citedByCount` is ignored; it is not a quality measure and using it
  would reintroduce the score the spec forbids.
- The frontend has no test runner in this stack, so UI behaviour was verified by
  driving the built app in a real browser, not by automated component tests.
- Responsive layouts were checked at desktop width in this pass; narrow-viewport
  screenshots were not taken.

---

## 4. Credentials needed to finish verification

| Credential | Where | Needed for |
|---|---|---|
| `OPENROUTER_API_KEY` with credit for `:free` models | `backend/.env` | The one AI call that produces the narrative, contradiction and gap sections. Without it the app runs fully but data-only |
| `NCBI_EMAIL` (optional) | `backend/.env` | Raises the E-utilities rate limit from 3 to 10 req/s; not required for correctness |

No other secret is read. Nothing client-side holds a key; `NEXT_PUBLIC_*` carries
only the API base URL.

---

## 5. Files

New in this work: `backend/utils/dates.py`, `backend/services/literature_view.py`,
`backend/services/candidate_analytics.py`, `backend/services/disease_analytics.py`,
`backend/services/trial_taxonomy.py`, `backend/integrations/disease_ontology.py`,
`backend/tests/test_literature_view.py`, `test_candidate_analytics.py`,
`test_disease_analytics.py`, `test_disease_ontology.py`, `test_dossier_fallback.py`,
`test_intelligence.py`, `test_text_utils.py`,
`frontend/components/disease/DiseaseDashboard.tsx`,
`frontend/components/trials/{CandidateDevelopmentPanel,CandidateTable,ClinicalTrialDashboard,ClinicalTrialTable}.tsx`,
`frontend/components/ExportControls.tsx`,
`frontend/lib/export/{csv,docx,pdf,print}.ts`,
`frontend/lib/{report,rasterize,download,trialCharts,candidateCharts,chartSvg,chartColors}.ts`.

Modified: `backend/main.py`, `backend/api/{dossier,literature,trials}.py`,
`backend/integrations/{pubmed,europepmc,clinicaltrials,openfda,uniprot,pubchem}.py`,
`backend/models/schemas.py`, `backend/services/{research_orchestrator,
evidence_normalizer,relevance_ranker,evidence_strength,dossier_generator}.py`,
`backend/utils/{text,http,evidence_types}.py`, `backend/tests/{test_parsers,
test_normalizer,test_ranker,test_orchestrator,test_trials}.py`,
`frontend/app/{layout,page}.tsx`, `frontend/app/dossier/page.tsx`,
`frontend/components/{LiteratureTable,DossierSection,DrugHeader,SearchBar,
EvidenceBadge,EvidenceStrengthPanel,RegulatoryTable,TargetTable}.tsx`,
`frontend/components/charts/BarBreakdown.tsx`, `frontend/lib/api.ts`,
`frontend/package.json` (adds `jspdf` and `docx`), `drug-intelligence/README.md`.

---

# Dossier Fix Report — 2026-10-29

Against `Qoder_MolTel_Dossier_Fix_Instructions.md`, using the semaglutide dossier
generated that day as the regression case. Nothing below is a semaglutide
correction: each rule reads the records a request retrieved, whatever the query.

## What changed, by brief section

**§1 phase and status.** The registry's own `phase` and `overall_status` now
travel on every trial, are handed to the model per trial, and are re-checked
against the narrative afterwards. A sentence that lists studies states one phase
per identifier, so the claim tested is the wording in that study's own clause,
nearest to its NCT ID — not the sentence's opener.

**§2 attribution and candidate counting.** New `services/trial_attribution.py`
sorts every retrieved trial into four mutually exclusive categories from
`armsInterventionsModule` alone: registered intervention, registered as comparator
or inside a combination name, related through a co-registered product or wording,
and not demonstrably relevant. A title mention, a procedure, or a placebo arm
labelled with the product's name never enters a "studies of this product" count,
and no drug-class table or synonym list is consulted. Each NCT ID is counted once
in every aggregate.

**§3 publication arithmetic.** Evidence categories are mutually exclusive and each
row states its denominator and the records behind it, so a narrative can be
recounted rather than trusted. Records whose source gave no recognised publication
type are reported (`DESIGN_UNSPECIFIED`) instead of folded into a tier, and a count
the retrieval cannot produce is an error.

**§4 efficacy figures.** A percentage must name a retrieved record in the same
sentence. Durations are checked against the outcome time points the registry
states for that study, so a 68-week reading cannot be rendered as six months, and
a reading cannot be placed outside the record's own start-to-completion span.

**§5–§7 safety, mechanism and gap language.** A pharmacovigilance sentence needs a
non-causal qualifier to stay; a rodent or in-vitro finding must state its human
relevance; a labelling claim must name the product and application it comes from;
an absence is bounded to what this retrieval queried, and a capped set cannot be
called comprehensive. Surrogate endpoints are separated from clinical benefit, and
a denial ("a hard clinical outcome was not assessed") is not treated as an
overclaim.

**§8 retrieval transparency.** Per-source status distinguishes error from
no-results from skipped; trial metadata carries `records_returned`,
`total_available`, `has_more` and `partial`; every panel, export and the dossier
banner show the same figures.

**§9 the gate.** `services/dossier_validator.py` runs 18 rules over the finished
narrative, the structured gap and contradiction sections and the aggregates. It
flags and blocks; it never repairs, because editing the prose would put the
pipeline's guess above the source. An error sets `blocked`, the response `status`
becomes `partial` and `publication_blocked` is true.

**§10 tests.** `backend/tests/test_dossier_regressions.py` — 36 tests plus one
opt-in live schema check — replays every defect class against three study records
captured from ClinicalTrials.gov v2 on 2026-10-29 (`backend/tests/fixtures/`), so
no test reaches the network or spends AI credits.

## Defects the tests found in the fix itself

- `_parse_outcomes` read `outcomeMeasure`; the v2 key is `measure`, so every
  outcome list parsed empty and the duration rule had nothing to check.
- The phase rule judged every identifier in a sentence by the first phase in it,
  inventing mismatches for a correctly written list.
- "Recruiting or active trials include…" claimed one state, contradicting records
  the registry files as *Active, not recruiting*.
- `attribute_trials` counted a study returned by two queries twice while reporting
  `distinct_trials` once, so the category totals did not reconcile.

## Checks run

```
cd drug-intelligence/backend && python -m pytest -q
→ 223 passed, 1 skipped in 50.28s

cd drug-intelligence/backend && MOLTEL_LIVE_TESTS=1 python -m pytest -k live_registry
→ 1 passed in 5.09s

cd drug-intelligence/frontend && npx tsc --noEmit
→ exit 0

cd drug-intelligence/frontend && npx next build
✓ Compiled successfully   ✓ Generating static pages (6/6)
/dossier   147 kB    first-load JS 235 kB
→ exit 0
```

A scratch backend on port 8077 generated one live semaglutide dossier
(`ai_synthesized: true`, 50 registry records). The gate reported 27 findings and
blocked publication; re-validating that same stored narrative after the pairing
fixes gives 4 errors and 18 warnings, and all four errors are genuine — two
completed studies the prose listed as recruiting or active, one record with an
unknown registry status described as terminated, and a labelling sentence that
names no product. No `FABRICATED_IDENTIFIER`, `COUNT_NOT_IN_RETRIEVAL` or
`NUMERIC_CLAIM_UNSOURCEDED` fired: with the registry figures and the arm lists in
its payload, the model cited real records and used the numbers it was given.

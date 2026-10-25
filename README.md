# MolTel

MolTel is a research intelligence platform for pharma and biomedical research. Search a compound, disease or biological target and receive a structured, evidence-backed dossier synthesised from public scientific databases — with clinical-development intelligence over ClinicalTrials.gov records computed deterministically, not by the model.

> **Not for clinical use.** All content is for research purposes only.

---

## Overview

The platform retrieves evidence from six public scientific APIs, normalises and ranks it deterministically, then uses a single OpenRouter LLM call to synthesise a structured dossier. The LLM is never the primary source of scientific facts — it only interprets and synthesises retrieved evidence.

Alongside the narrative sections the dossier carries four panels: an evidence-strength tally, a contradictory-findings detector, a clinical trial landscape dashboard, and a research gap finder. Evidence tiers and every trial count are computed from the retrieved records, not by the model.

**Example query:** `Clemizole and TRPC5 in Alzheimer's disease`

---

## Architecture

```
USER QUERY
    │
    ▼
NEXT.JS / REACT UI
    │ HTTPS
    ▼
FASTAPI BACKEND
    │
    ▼
RESEARCH ORCHESTRATOR (asyncio.gather)
    │
    ├── PubChem ──────── compound profile
    ├── PubMed ────────┐
    ├── Europe PMC ────┤ literature evidence
    ├── ClinicalTrials ─ trial registry
    ├── openFDA ──────── regulatory labels
    └── UniProt ──────── protein/target context
    │
    ▼
EVIDENCE NORMALISER → DEDUPLICATION → RELEVANCE RANKER
    │
    ├──► DETERMINISTIC AGGREGATION (no LLM)
    │       evidence tiers · trial status/phase taxonomy · chart analytics
    │
    ▼
OPENROUTER (one LLM call per dossier)
    │
    ▼
STRUCTURED JSON DOSSIER + AGGREGATES → FRONTEND (Recharts)
```

**Constraints:** No database, no authentication, no background workers. Fully stateless.

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- An [OpenRouter](https://openrouter.ai/) API key (free tier works)

### 1. Clone / open the project

```bash
cd drug-intelligence
```

### 2. Backend

```bash
cd backend

# Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY and optionally NCBI_EMAIL
```

### 3. Frontend

```bash
cd frontend
npm install

# Configure environment
cp .env.local.example .env.local
# Edit .env.local if your backend runs on a different port
```

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENROUTER_API_KEY` | No | — | Your OpenRouter API key. Without it every record, table, chart and export is still produced, and the dossier states that AI synthesis was unavailable |
| `OPENROUTER_MODEL` | No | `openrouter/auto` | OpenRouter model identifier. A free-tier key only accepts `:free` models — `openrouter/auto` and other paid models answer HTTP 402. A `:free` ID can also be listed by `/api/v1/models` yet 404 at its upstream provider, which silently produces a data-only dossier, so verify one real completion before relying on it |
| `FRONTEND_ORIGIN` | No | `http://localhost:3000` | Comma-separated list of allowed CORS origins. The browser calls the API directly, so an origin left out here cannot read results |
| `NCBI_EMAIL` | No | — | Email for NCBI E-utilities (recommended) |

### Frontend (`frontend/.env.local`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:8000` | Backend API URL |

`NEXT_PUBLIC_` variables are compiled into the browser bundle, so the OpenRouter
key stays on the backend and is never exposed to the client. Pointing
`NEXT_PUBLIC_API_URL` straight at the backend also avoids the ~30 second ceiling
on the Next.js dev proxy, which a full dossier call can exceed.

---

## Running the Application

### Backend

```bash
cd backend
uvicorn main:app --reload
```

The API runs at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm run dev
```

The UI runs at `http://localhost:3000`.

---

## Running Tests

```bash
cd backend
pytest
```

185 tests covering:
- PubChem / PubMed / Europe PMC / ClinicalTrials / openFDA / UniProt parsers,
  including the dates, identifiers and publication types each source states
- Evidence normalisation, deduplication on PMID/PMCID/DOI only, and the merge
  counts reported to the reader
- The four literature views and their filters: every ordering rule, exclusion
  count and ranking reason is asserted from the record fields the sources gave
- Relevance scoring components, and the rule that no numeric evidence score exists
- Clinical trial status and phase taxonomy, including unrecognised future values
- Deterministic dashboard analytics: deduplication, non-overlapping status
  counts, ongoing-by-phase, phase ordering, timeline granularity and exclusion
  of unusable dates
- The `/api/trials` endpoint, including filters and the analytics of the
  unfiltered set
- Candidate, disease-concept and subtype extraction, including the rule that a
  subtype is only ever a stated hierarchy relation or the registry's own wording
- Contradiction and research-gap parsing: uncited items are dropped, agreement
  is not reported as a conflict, labels distinguish observations from hypotheses
- Orchestrator behaviour when a source fails, returns nothing, or the LLM is
  unavailable

External APIs are mocked (`respx`) and the OpenRouter key is never read from the
developer environment — tests require no network access and consume no AI
credits.

Type-check the frontend with:

```bash
cd frontend
npx tsc --noEmit
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/dossier` | Generate research dossier |
| `GET` | `/api/compound/{name}` | Retrieve compound profile |
| `GET` | `/api/literature?query=&view=` | Retrieve publications from PubMed and Europe PMC, merged, ordered as one view |
| `POST` | `/api/literature/views` | Re-order and filter records already retrieved; queries no source |
| `GET` | `/api/trials?query=` | Retrieve clinical trials with dashboard analytics |

`/api/literature` and `/api/literature/views` both return a `LiteratureViewResult`:
the ordered records, the rule that ordered them, one ranking reason per record,
the count each filter removed, facets counted before filtering, the merge report
and the limits of the view. `view` is one of `most_relevant`, `latest`,
`strongest_evidence` or `reviews_guidelines`.

`/api/trials` also accepts `status`, `phase`, `study_type` and `condition`
filters. The returned `trials` list carries the filter; `analytics` always
describes the whole retrieval so the charts stay consistent with each other.
`analytics` is `null` when ClinicalTrials.gov could not be consulted — zero
counts would otherwise read as "no trials exist".

### POST /api/dossier

**Request:**
```json
{ "query": "Clemizole and TRPC5 in Alzheimer's disease", "search_mode": "compound" }
```

`search_mode` is `compound` (default), `disease` or `target`, and decides which
sources are asked: PubChem and openFDA answer a product name only, while a
disease query is also resolved through the disease ontology.

**Response:**
```json
{
  "query": "...",
  "status": "success | partial | error",
  "search_mode": "compound | disease | target",
  "sources": [
    { "source_name": "PubChem", "status": "success", "count": 1 },
    { "source_name": "PubMed", "status": "success", "count": 23 }
  ],
  "dossier": {
    "executive_summary": "...",
    "compound_profile": { ... },
    "mechanism": "...",
    "therapeutic_evidence": "...",
    "literature_summary": "...",
    "clinical_development": "...",
    "safety": "...",
    "evidence_gaps": "...",
    "research_opportunities": "...",
    "contradictory_findings": { "contradictions": [], "assessment": "...", "insufficient_evidence": false },
    "research_gap_analysis": [],
    "references": [...]
  },
  "ai_synthesized": true,
  "synthesis_detail": null,
  "evidence_items": [...],
  "clinical_trials": [...],
  "targets": [...],
  "evidence_strength": { "categories": [], "predominant_tier": "clinical", "interpretation": "...", "limitations": [], "unclassified_count": 0, "automated": true },
  "trial_analytics": { "total_trials": 50, "ongoing_trials": 20, "trials_by_phase": [], "trials_by_status": [], "trial_starts_by_period": [], "metadata": { ... } },
  "candidate_analytics": { "candidates": [], "companies": [], "limitations": [] },
  "disease_analytics": { "concept": { ... }, "subtypes": [], "papers_considered": 0 },
  "literature": { "view": "most_relevant", "rule": "...", "ordered_by": "...", "items": [], "exclusions": [], "facets": [], "deduplication": { ... }, "limitations": [] },
  "retrieved_at": "2026-10-12T00:00:00+00:00"
}
```

`references` is built by the server from the records that were actually fetched;
the model is asked to cite inline, not to retype the list. `trial_analytics` is
`null` when the registry could not be reached, and every count in it is computed
from the deduplicated records rather than by the model.

---

## Deployment

Two apps from one repo: the Next.js frontend on Vercel, the FastAPI backend on
Render (or Railway). The browser calls the backend directly, so the backend has
to know the frontend's exact origin — nothing else in the system holds a secret
that reaches the client.

**Order matters.** `NEXT_PUBLIC_API_URL` is baked into the browser bundle when
Vercel builds it, and `FRONTEND_ORIGIN` is read by the backend at request time.
So the backend is deployed first, its URL is given to the frontend, and the
frontend's origin is then added to the backend. Changing the backend URL later
means rebuilding the frontend — an env edit alone will not do it.

### Live deployment

| Surface | URL | Notes |
| --- | --- | --- |
| Frontend | `https://moltel.vercel.app` | Vercel project `moltel`, Root Directory `frontend` |
| Backend | `https://moltel-backend.onrender.com` | Render blueprint `moltel`, free instance |

The free Render instance **spins down when idle**, so the first request after a
quiet period can take around 50 seconds; a search may show its loading state for
that long. A request that arrives while the instance is still starting can also
return **HTTP 502** — retrying once is enough. `OPENROUTER_API_KEY` is stored in
the Render dashboard only (it is `sync: false`, so it can never come from the
repo), and the deployed site serves AI-synthesized narratives. `FRONTEND_ORIGIN`
on Render allows `https://moltel.vercel.app` and
`https://moltel-git-main-lse-ngine.vercel.app`; any other origin, including a
per-deployment Vercel preview URL, is refused.

Setting the key is not enough on its own: the model must also be one that
answers. `nvidia/nemotron-3-super-120b-a12b:free` appears in OpenRouter's
`/api/v1/models` catalogue yet its upstream provider returns HTTP 404 for every
request, and the app then takes its honest data-only fallback rather than
failing loudly. `render.yaml` now pins `nvidia/nemotron-3.5-lightning:free`.

### 1. Push the repository to GitHub

```bash
cd drug-intelligence
git init -b main
git add . && git commit -m "MolTel research intelligence platform"
# create an empty private repo on GitHub, then:
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

`backend/.env` and `frontend/.env.local` are git-ignored; only the `.example`
files are committed. Confirm with `git status --ignored` before pushing that no
`.env` appears in `git add`.

### 2. Backend — Render (blueprint is in this repo)

Render → New → Blueprint → pick the repo; `render.yaml` defines the service.

| Variable | Value |
|---|---|
| `FRONTEND_ORIGIN` | the exact frontend origin(s), comma-separated — e.g. `https://moltel.vercel.app,https://preview-xyz.moltel.vercel.app` |
| `OPENROUTER_API_KEY` | secret, set in the dashboard only |
| `OPENROUTER_MODEL` | a `:free` variant that actually answers; see the 404 note above |
| `NCBI_EMAIL` | optional; raises the E-utilities limit from 3 to 10 req/s |

Only `sync: false` keys (`OPENROUTER_API_KEY`, `NCBI_EMAIL`) are set from the
dashboard. Anything `render.yaml` declares is blueprint-managed: the Environment
page accepts typing into those rows but silently discards the value, so change
the repo file and run **Manual sync → Approve** instead.

It starts from `backend/Procfile`
(`uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`)
and health-checks `/health`.

**Railway instead:** create a service from the repo, set its **Root Directory**
to `backend`, and `backend/Procfile` + `backend/railway.json` (start command,
`/health` health check, restart-on-failure) apply. Add the same variables.

Free plans sleep after inactivity, so the first request after a quiet period also
has to warm PubChem, PubMed, Europe PMC, the registry, openFDA and UniProt at
once. Expect one slow search, not a broken one.

### 3. Frontend — Vercel

Import the repo, set **Root Directory** to `frontend`, framework Next.js.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | the backend URL from step 2, e.g. `https://moltel-backend.onrender.com` — no trailing slash |

Deploy, then add the resulting origin (including preview origins) to the
backend's `FRONTEND_ORIGIN` and restart the backend so CORS picks it up.

### Verify a deployment

```bash
curl https://<backend>/health
curl -i -X POST https://<backend>/api/dossier \
  -H 'Content-Type: application/json' -H 'Origin: https://<frontend>' \
  -d '{"query":"metformin","search_mode":"compound"}'
```

The second call must return `access-control-allow-origin: https://<frontend>` and
a `200` with `evidence_items`, `clinical_trials` and `targets` populated. In the
browser, run a query in each search mode, switch the four literature tabs, apply
a filter, and download PDF, Word and CSV. With no working OpenRouter key the
dossier is `ai_synthesized: false` and says plainly that the narrative sections
were not produced — that banner is the expected state, not a failure.

A deployment stores nothing between requests. There is no database, no queue and
no cache to provision, and no secret belongs in a `NEXT_PUBLIC_*` variable.

---

## Scientific Data Sources

| Source | API | Data |
|---|---|---|
| [PubChem](https://pubchem.ncbi.nlm.nih.gov/) | PUG REST | Compound profiles, chemical identifiers |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | NCBI E-utilities | Biomedical literature, abstracts |
| [Europe PMC](https://europepmc.org/) | REST API | Open access literature, PMC full-text |
| [ClinicalTrials.gov](https://clinicaltrials.gov/) | REST API v2 | Clinical trial registry |
| [openFDA](https://open.fda.gov/) | Drug labels API | Approved drug labelling, adverse events |
| [UniProt](https://www.uniprot.org/) | REST API | Protein/target function, sequences |

All sources are free and public. No proprietary databases are used.

---

## Dossier Panels

Four panels sit on top of the retrieved records. Each states its own limits in
the UI rather than relying on the reader to infer them.

| Panel | Computed by | What it refuses to claim |
|---|---|---|
| Evidence Strength Summary | Deterministically, from each record's publication type | No numeric "evidence score" exists. A tier with many records is not presented as a strong tier |
| Contradictory Findings | One AI synthesis call, validated against the payload | Studies measuring different outcomes, models, doses or endpoints are reported as different experimental contexts, not conflicts. Uncited claims are dropped |
| Clinical Trial Landscape | Deterministically, from deduplicated registry records | Counts never come from the model. Charts that overlap (Ongoing vs Recruiting) are shown separately and are not summed |
| Research Gap Finder | One AI synthesis call, capped at 3 gaps | A gap is described against the retrieved records only. Absence from the retrieval is not absence from the literature |

One LLM call answers both the narrative sections and the contradiction/gap
panels. If AI synthesis is unavailable, the dossier falls back to a data-only
report that restates fetched records and says the analysis was unavailable.

---

## Literature Views

`services/literature_view.py` holds every ordering and filter rule for the
publication panel. The browser re-ranks by posting the records it already holds
to `POST /api/literature/views`, so no rule is implemented twice and no source
is queried again when the reader changes a tab.

| View | Ordered by | What it refuses to claim |
|---|---|---|
| Most relevant | Query words in the title (3x) and abstract, scaled by the reported design, plus 0.1 for a record published within two years | The ordering key is not a quality score and says nothing about how reliably a study was run |
| Latest | The publication date the source states, most recent first | A database's indexing date is shown beside the record and never decides this order |
| Strongest evidence | The study design the source reports, on a fixed 13-position ladder (randomized controlled trial first, notices about a record last) | Designs are ranked, papers are not; two papers on the same rung are ordered by date |
| Reviews & guidelines | Publication date, restricted to records whose own reported types name a review, guideline or meta-analysis | A paper that reviews a topic without the source labelling it that way is not detected, and the count left out is stated |

Dates are kept at the precision the source stated them — `published_on` plus
`published_precision` of day, month or year — and are displayed as stated, never
padded to look exact. A year-only date sorts at the start of that year and says
so. `indexed_on` and `indexed_field` (PubMed's `entrez` history, Europe PMC's
`firstIndexDate` or `dateOfCreation`) are separate fields and are never
presented as publication dates.

Filters (published range, study scope, source, publication type, access, disease
subtype wording, target wording) each report how many records they removed and
what the removal could not see. Facets are counted before filtering, so the
counts stay meaningful while a filter is active.

Records are merged into publications only on a PMID, PMCID or DOI. Titles and
author lists are never compared. The panel states how many retrieved records
became how many publications, how many merges spanned both databases, and how
many records carried no identifier at all; a merged publication keeps every
source link, identifier and publication type, listed per link.

---

## Clinical Trial Classification

`services/trial_taxonomy.py` is the single place that assigns a meaning to a
registry status or phase, and every dashboard count goes through it.

| Registry status | Dashboard category |
|---|---|
| `RECRUITING`, `ENROLLING_BY_INVITATION` | Currently recruiting |
| `ACTIVE_NOT_RECRUITING` | Ongoing, not currently recruiting |
| `NOT_YET_RECRUITING` | Not yet started |
| `SUSPENDED` | Paused |
| `COMPLETED` | Completed |
| `TERMINATED`, `WITHDRAWN` | Discontinued |
| `UNKNOWN`, `AVAILABLE`, `TEMPORARILY_NOT_AVAILABLE`, unrecognised values | Other or unclear |

Unrecognised statuses are counted and displayed, never dropped and never
silently folded into a neighbouring category. *Ongoing* is the union of the
first two rows, so it is reported as an overlapping figure rather than as
another slice of the total.

Phases keep their combination: a `PHASE1/PHASE2` study is charted as
"Phase 1 + Phase 2" instead of being assigned to one phase, a missing phase
stays "Unknown / Not Reported", and an unknown future phase value is shown as
given. Start dates are used only at the precision the registry supplies —
partial dates such as `2003-01` are not padded to a fabricated day, unusable
dates are excluded and counted, and the timeline chart is omitted with an
explanation when fewer than three records carry a usable date.

---

## Evidence Classification

Evidence is classified into one of:

| Type | Description |
|---|---|
| `clinical` | Human clinical trials and studies |
| `observational` | Epidemiological / observational studies |
| `animal` | In vivo animal studies |
| `cellular` | In vitro cell studies |
| `biochemical` | Biochemical assays |
| `computational` | In silico / computational studies |
| `literature_review` | Reviews and meta-analyses |
| `regulatory` | Regulatory drug label information |
| `AI_hypothesis` | AI-generated research hypotheses |

Computational evidence is never presented as equivalent to clinical evidence.

---

## Limitations

- Evidence retrieval quality depends on API availability and query formulation.
- The relevance ranker uses deterministic heuristics, not semantic embeddings.
- OpenRouter free-tier models may return lower-quality synthesis.
- The platform does not access full-text papers, only abstracts and metadata.
- openFDA adverse event reports reflect reported associations, not proven causality.
- Evidence tiers are read from publication-type metadata, so a mislabelled source
  record is misclassified in the Evidence Strength panel.
- The literature views order only the records one search retrieved, and the
  "Strongest evidence" view ranks the design the source states, not how well any
  individual paper executed it.
- A record's publication date is shown at exactly the precision its source
  stated; a year-only date sorts at the start of that year, and Europe PMC's
  citation counts are deliberately not parsed into any ordering.
- "Open access" is only ever reported when a source states it. An unstated flag
  is shown as not stated, never as closed access.
- Trial analytics describe the records this retrieval returned. The registry holds
  more studies than one search page, and the panel says so.
- ClinicalTrials.gov distinguishes "could not be consulted" from "no trials found".
  The other sources collapse both into a single failure state, so their dash in the
  data-sources strip does not tell you which happened.
- No data is persisted between requests (stateless by design).
- The platform is not validated for clinical decision-making.

---

## Known Constraints (V1)

- No user accounts or saved queries.
- No database — all state is request-scoped.
- One LLM call per dossier (cost-optimised for free tier).
- No chart value is hardcoded in a component: every bar, card and point is bound
  to `trial_analytics` or `evidence_strength`.
- Rate limiting is handled gracefully per source but not actively enforced on the backend.

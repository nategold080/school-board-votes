# Technical Writeup: School Board Vote Tracker

## Problem Statement

There are 16,715 public school districts in the United States. Each holds regular board meetings where elected officials vote on policy decisions affecting millions of students — budgets, curriculum, personnel, facilities, and more. These votes are public record. Yet no structured, searchable database of school board voting records exists.

The data is there, scattered across thousands of district websites in formats ranging from PDF scans to JavaScript-rendered portals. The challenge is extracting, structuring, and standardizing it at scale.

## Approach

### Data Source: BoardDocs

BoardDocs (go.boarddocs.com) is the dominant platform for school board meeting management. Thousands of districts use it. This is advantageous: one platform means one set of structural conventions to learn, and one scraping strategy that generalizes across hundreds of districts.

**Discovery**: BoardDocs exposes a public SEO endpoint (`BD-GETMeetingsListForSEO`) that returns meeting lists as JSON without authentication. Meeting content, however, requires a JavaScript-rendered browser session.

**Scraping strategy**: Use the SEO endpoint for discovery (fast, no browser needed), then Playwright for content extraction (one browser context shared across all districts). This processes 69 districts in ~40 minutes.

### The Extraction Problem

The raw data from BoardDocs looks like this:

```
=== 1.OPENING OF MEETING ===
=== 2.BOARD RECOGNITION ===
=== 8.CONSENT AGENDA ===
=== 9.PERSONNEL AFFAIRS - PERSONNEL CHANGES ===
=== 17.BUSINESS AFFAIRS - AWARD OF CONTRACT ===
=== 25.APPROVE CONSENT AGENDA ===
```

The challenge: determine which items involved formal votes, classify them by policy category, and extract vote details — all without explicit vote records in most cases.

### Why Not Just Use an LLM?

The naive approach: send every document to GPT-4 and ask it to extract structured data. This works for small-scale demos but fails as an engineering solution:

1. **Cost**: At ~$0.02/document, processing 200K meetings/year costs $4,000/year with linear scaling.
2. **Speed**: API calls add seconds per document. Our rule engine processes 261 meetings in <1 second.
3. **Determinism**: LLMs can hallucinate vote counts or misclassify items. Pattern matching is predictable and testable.
4. **Technical depth**: "Call API, get JSON" is prompt engineering. Building a system that learns platform conventions and handles edge cases is software engineering.

### The Hybrid Architecture

```
                    ┌─────────────────────┐
                    │   Raw Meeting Text   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Metadata Extraction │  Parse header: district, date, type
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Section Extraction  │  Split by === headers
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Category Classifier  │  12 categories, regex scoring
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Vote Likelihood      │  VOTE_LIKELY vs NO_VOTE patterns
                    │ Assessment           │  → has_vote + confidence score
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Vote Detail          │  Counts, roll calls, motion makers
                    │ Extraction           │  Individual votes from patterns
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
        high conf        medium conf       low conf
              │                │                │
              ▼                ▼                ▼
          Database         Database        LLM Fallback
                                               │
                                               ▼
                                           Database
```

#### Category Classification

13 policy categories, each with multiple regex patterns:

```python
"consent_agenda": [r"consent\s+(agenda|calendar|items?)", ...],
"personnel":      [r"personnel", r"human\s+(capital|resources)", ...],
"budget_finance":  [r"budget", r"financ(e|ial)", r"award\s+of\s+(contract|purchase)", ...],
```

A section is classified by scoring matches across all categories and selecting the highest. This handles variations like "PERSONNEL AFFAIRS - PERSONNEL CHANGES" and "Human Resource Items" both mapping to `personnel`.

#### Vote Likelihood Assessment

Two pattern lists determine whether an item likely has a vote:

- **VOTE_LIKELY**: `consent agenda`, `approval of minutes`, `award of contract`, `board policies`, `resolution`, etc.
- **NO_VOTE**: `call to order`, `pledge of allegiance`, `superintendent's report`, `adjournment`, etc.

Items matching NO_VOTE patterns are marked `has_vote: false` with high confidence. Items matching VOTE_LIKELY patterns are marked `has_vote: true` with confidence proportional to match count.

#### Vote Detail Extraction

When explicit vote language exists in the text, the engine extracts:
- Vote counts from `N-N` patterns (e.g., "approved 5-2")
- Individual votes from roll call patterns (e.g., "Mr. Smith - Aye")
- Motion makers/seconders from "motion by" / "seconded by" patterns
- Result from "carried", "failed", "tabled" language

### Confidence Scoring

Every extraction carries a confidence score:
- **High**: Explicit vote language found (counts, roll call, "carried unanimously")
- **Medium**: Item type strongly suggests a vote (consent agenda, policy approval)
- **Low**: Ambiguous — item might or might not have a vote

The `HybridExtractor` uses confidence scores to decide when LLM fallback is needed. In practice, the rule engine handles >95% of items with medium or high confidence.

## Results

### Scale
| Metric | Count |
|--------|-------|
| Districts | 51 |
| States | 7 (NY, TX, CA, FL, VA, OH, CO) |
| Meetings | 261 |
| Agenda items | 3,685 |
| Votes extracted | 727 |
| LLM API calls | 0 |
| API cost | $0.00 |
| Extraction time | <1 second |

### Category Distribution
| Category | Votes | % of Total |
|----------|-------|-----------|
| Consent Agenda | 330 | 45.4% |
| Other | 261 | 35.9% |
| Budget/Finance | 37 | 5.1% |
| Curriculum | 32 | 4.4% |
| Policy | 28 | 3.9% |
| Personnel | 27 | 3.7% |

### State Coverage
| State | Districts | Votes |
|-------|-----------|-------|
| NY | 9 | 225 |
| OH | 6 | 153 |
| CA | 9 | 131 |
| FL | 8 | 120 |
| VA | 8 | 74 |
| TX | 4 | 24 |

### Key Finding
98.9% unanimity rate across all extracted votes. This is consistent with research on school board governance: most votes are procedural (consent agendas, minute approvals). The 1.1% of contested votes are where the interesting policy dynamics live.

## Technology Stack

- **Python 3.11+**: Core language
- **Playwright**: Headless browser for BoardDocs scraping
- **SQLAlchemy**: ORM for SQLite database
- **Pydantic**: Schema validation for extraction outputs
- **Streamlit**: Interactive web interface
- **Plotly**: Data visualization
- **OpenAI API**: LLM fallback (optional, not used in current run)

## What I'd Do Differently

1. **Template learning**: Instead of static regex patterns, build a system that learns new patterns from LLM-validated examples. Process 5 meetings with LLM, extract the patterns used, add them to the rule engine automatically.

2. **Full minutes text**: Many districts publish detailed meeting minutes (not just agendas) as PDFs. These contain actual vote counts, roll call records, and motion text. A PDF extraction pipeline would dramatically improve data quality.

3. **Continuous scraping**: Build a scheduled job that re-scrapes districts weekly and processes only new meetings. The infrastructure supports this — just needs a "last scraped" timestamp and delta processing.

4. **District fingerprinting**: Automatically detect which structural patterns a district uses and select the optimal extraction strategy. Some districts label sections differently, use sub-items, or include inline vote results.

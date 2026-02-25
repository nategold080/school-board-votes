# Technical Writeup: School Board Vote Tracker

## Problem Statement

There are 16,715 public school districts in the United States. Each holds regular board meetings where elected officials vote on policy decisions affecting millions of students — budgets, curriculum, personnel, facilities, and more. These votes are public record. Yet no structured, searchable database of school board voting records exists.

The data is there, scattered across thousands of district websites in formats ranging from PDF scans to JavaScript-rendered portals. The challenge is extracting, structuring, and standardizing it at scale.

## Approach

### Data Source: BoardDocs

BoardDocs (go.boarddocs.com) is the dominant platform for school board meeting management. Thousands of districts use it. This is advantageous: one platform means one set of structural conventions to learn, and one scraping strategy that generalizes across hundreds of districts.

**Discovery**: BoardDocs exposes a public SEO endpoint (`BD-GETMeetingsListForSEO`) that returns meeting lists as JSON without authentication. Meeting content, however, requires a JavaScript-rendered browser session.

**Scraping strategy**: Use the SEO endpoint for discovery (fast, no browser needed), then Playwright for content extraction (one browser context shared across all districts). This processes 130+ districts in ~4-6 hours.

### The Breakthrough: Minutes Capture

The single biggest technical insight: BoardDocs meetings have **two** document types.

- **Agendas** are pre-meeting documents listing planned items. They rarely contain vote results.
- **Minutes** are post-meeting approved records. They contain roll-call votes, attendance, motion makers, and individual member votes.

Most prior attempts at scraping BoardDocs only captured agendas. Our scraper detects the "View Minutes" link for each meeting, clicks it, waits for the AJAX content to load, and captures the full minutes text alongside the agenda.

This is what unlocks individual vote records — transforming the system from a catalog of agenda items into a genuine voting database.

**Implementation details:**
1. After loading a meeting page, the scraper looks for a minutes link: `a:has-text("Minutes"):not(:has-text("Approval")):not(:has-text("Approve"))`
2. If found, it clicks the link and waits 4 seconds for AJAX responses
3. It intercepts any `BD-GetMinutes` API calls
4. The minutes body text is appended to the output file under a `MINUTES TEXT:` marker

About 55% of scraped districts have minutes published on BoardDocs. Each district with minutes yields 5-9 individual vote records per motion, creating the core of the voting record database.

### The Extraction Problem

Raw BoardDocs data looks like this:

```
=== 1.OPENING OF MEETING ===
=== 2.BOARD RECOGNITION ===
=== 8.CONSENT AGENDA ===
=== 9.PERSONNEL AFFAIRS - PERSONNEL CHANGES ===
=== 17.BUSINESS AFFAIRS - AWARD OF CONTRACT ===

MINUTES TEXT:
Motion made by Smith, seconded by Jones:
Roll Call Vote: Aye: Smith, Jones, Williams, Brown, Davis
               Nay: Taylor
               Absent: Wilson
Motion carried 5-1.
```

The extraction challenge is multi-layered:
1. Identify which items involved formal votes
2. Classify each by policy category
3. Extract vote details (result, counts, motion makers)
4. Parse individual roll-call votes from minutes text
5. Match minutes vote data to the correct agenda items
6. Handle 100+ format variations across districts

### Why Not Just Use an LLM?

The naive approach: send every document to GPT-4 and ask it to extract structured data. This works for small-scale demos but fails as an engineering solution:

1. **Cost**: At ~$0.02-0.05/document, processing 200K meetings/year costs $4,000-10,000/year with linear scaling. Our rule engine: $0.00.
2. **Speed**: API calls add seconds per document. Our rule engine processes 1,600+ meetings in under 2 seconds.
3. **Determinism**: LLMs can hallucinate vote counts or misclassify items. Pattern matching is predictable and testable.
4. **Scalability**: Adding a new BoardDocs district costs nothing — the same patterns apply.

An optional LLM fallback exists for genuinely ambiguous cases but has not been needed in production runs.

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
                    └──────────┬──────────┘  (boundary-aware: stops at MINUTES TEXT)
                               │
                    ┌──────────▼──────────┐
                    │ Category Classifier  │  15 categories, 200+ regex patterns
                    └──────────┬──────────┘  prefix stripping, scoring
                               │
                    ┌──────────▼──────────┐
                    │ Vote Likelihood      │  VOTE_LIKELY vs NO_VOTE patterns
                    │ Assessment           │  → has_vote + confidence score
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Minutes Parser       │  Roll calls, motions, attendance
                    │ (_extract_minutes)   │  Merges with agenda items
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Post-Processing      │  Recalculate unanimity from
                    │ Validation           │  actual individual vote data
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

15 policy categories, each with multiple regex patterns:

```python
"consent_agenda":        [r"consent\s+(agenda|calendar|items?)", ...]
"personnel":             [r"personnel", r"human\s+(capital|resources)", ...]
"budget_finance":        [r"budget", r"financ(e|ial)", r"contract\s+approv", ...]
"procedural":            [r"approv(e|al)\s+of\s+(the\s+)?(agenda|minutes)", ...]
"admin_operations":      [r"superintendent.?s?\s+report", r"presentation", ...]
"curriculum_instruction": [r"curriculum", r"textbook", r"field\s+trip", ...]
```

The classifier strips common prefixes ("A.", "B.", "Consent - ") and suffixes ("*(PUBLIC CANNOT...)") before matching, then scores each category and selects the highest. This handles variations like "PERSONNEL AFFAIRS - PERSONNEL CHANGES" and "Human Resource Items" both mapping to `personnel`.

The "other" category — items that don't match any pattern — has been driven to 11.6% through iterative pattern expansion. Generic section headers ("ACTION ITEMS", "UNFINISHED BUSINESS") are detected and classified as procedural or admin rather than polluting the "other" bucket.

#### Minutes Vote Parsing

The minutes parser (`_extract_minutes_sections()`) handles two major roll-call formats:

**Format 1 — Individual lines:**
```
Mr. Smith - Aye
Ms. Jones - Aye
Dr. Brown - Nay
```

**Format 2 — Aggregated lists:**
```
Aye: Smith, Jones, Williams, Davis
Nay: Brown
Absent: Wilson
```

It also extracts motion blocks using patterns like:
```
Motion made by Smith, seconded by Jones
```

These are matched to their closest agenda item by position in the text. When minutes data overlaps with agenda-inferred data, the minutes version wins (higher confidence).

### Confidence Scoring and Validation

Every extraction carries a confidence score:
- **High**: Explicit vote language found (counts, roll call, "carried unanimously")
- **Medium**: Item type strongly suggests a vote (consent agenda, policy approval)
- **Low**: Ambiguous — item might or might not have a vote

A critical post-processing step recalculates `is_unanimous` from actual individual vote data:
```python
for item in meeting.agenda_items:
    if item.individual_votes:
        no_count = sum(1 for v in item.individual_votes if v["member_vote"] == "no")
        item.is_unanimous = no_count == 0
```

This catches edge cases where agenda text says "unanimous" but minutes reveal dissent — a subtle but important data quality issue.

## Results

### Scale

| Metric | Count |
|--------|-------|
| Active districts | 130 |
| States | 20 (AZ, CA, CO, CT, FL, GA, IA, ID, IL, IN, KS, MI, NC, NY, OH, PA, TX, VA, WA, WI) |
| Meetings | 1,634 |
| Agenda items | 20,506 |
| Votes extracted | 5,790 |
| Individual vote records | 11,366 |
| Board members identified | 414 |
| Contested (non-unanimous) votes | 181 |
| LLM API calls | 0 |
| API cost | $0.00 |
| Extraction time | <2 seconds for full dataset |

### Key Findings

1. **High unanimity rate**: ~95%+ of school board votes are unanimous. This is consistent with governance research — most votes are procedural (consent agendas, minute approvals).

2. **Contested votes are rare and revealing**: The ~5% of non-unanimous votes are where policy dynamics become visible. They tend to cluster in specific categories (personnel, budget, policy) rather than being evenly distributed.

3. **Minutes availability varies**: ~55% of active BoardDocs districts have minutes published. These districts disproportionately contribute the most valuable data (individual vote records).

4. **Category distribution**: After pattern optimization, the "other" bucket is 11.6%. The largest categories are admin/operations (~26%), consent agenda (~24%), procedural (~16%), budget/finance (~7%), and personnel (~5%).

## Technology Stack

- **Python 3.11+**: Core language with async/await
- **Playwright**: Headless browser for BoardDocs scraping
- **SQLAlchemy**: ORM for SQLite with WAL mode
- **Pydantic**: Schema validation for extraction outputs
- **Streamlit**: Interactive web interface (6 pages)
- **Plotly**: Data visualization
- **BeautifulSoup**: HTML parsing of minutes content
- **OpenAI API**: Optional LLM fallback (unused in production)

## What I'd Do Next

1. **Template learning**: Instead of static regex patterns, build a system that learns new patterns from LLM-validated examples. Process 5 meetings with LLM, extract the patterns used, add them to the rule engine automatically. This creates a feedback loop that improves coverage without increasing marginal cost.

2. **PDF minutes pipeline**: Many non-BoardDocs districts publish detailed meeting minutes as PDFs. These contain the richest vote data. A PDF extraction pipeline (OCR + structured parsing) would significantly expand coverage.

3. **Continuous scraping**: A scheduled job that re-scrapes districts weekly and processes only new meetings. The infrastructure supports this — just needs a "last scraped" timestamp and delta processing.

4. **District fingerprinting**: Automatically detect which structural patterns a district uses and select the optimal extraction strategy. Some districts label sections differently, use sub-items, or include inline vote results.

5. **API layer**: REST API for programmatic access to the vote database. Enable researchers, journalists, and civic tech organizations to query the data directly.

6. **Civic engagement**: Automated alerts when specific policy categories come up for a vote, legislator scorecards based on voting history, and cross-district policy comparison tools.

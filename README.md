# School Board Vote Tracker

**The first structured database of school board voting records in the United States.**

This system scrapes, parses, and structures school board meeting data from public BoardDocs portals, capturing both agenda items and approved meeting minutes. It extracts individual roll-call votes, categorizes policy decisions, and identifies contested votes — all without LLM API costs.

## The Problem

There are 16,715 public school districts in the United States. Each holds regular board meetings where elected officials vote on decisions affecting over 50 million students: budgets, personnel, curriculum, facilities, and policy. These votes are public record. Yet no structured, searchable database of school board voting records exists.

The data is trapped in JavaScript-rendered portals, scattered across thousands of district websites, with no standard format. Extracting it requires navigating platform-specific conventions, parsing unstructured text, and handling hundreds of format variations.

## Current Scale

| Metric | Count |
|--------|-------|
| Active districts | 130 |
| States | 20 |
| Meetings analyzed | 1,634 |
| Agenda items | 20,506 |
| Votes extracted | 5,790 |
| Individual roll-call records | 11,366 |
| Contested (non-unanimous) votes | 181 |
| Board members identified | 414 |
| LLM API cost | $0.00 |

## Architecture

### Data Pipeline

```
BoardDocs Portal (go.boarddocs.com)
        |
        v
  [Playwright Scraper]  ── headless browser, session reuse
        |                   captures agenda AND minutes views
        |                   intercepts AJAX responses
        v
  Raw text files (per meeting)
        |
        v
  [Rule-Based Extractor]  ── 15 category patterns, vote detection
        |                      minutes-specific parsers
        |                      zero marginal cost
        |
        |─── agenda sections ──> Category + vote likelihood
        |
        |─── minutes text ────> Roll calls, attendance,
        |                       motion makers, individual votes
        v
  SQLite Database (6 normalized tables)
        |
        v
  [Streamlit Interface]  ── 6 interactive pages
                             search, filter, analyze
```

### Key Technical Innovation: Minutes Capture

BoardDocs meetings have two document types: **Agendas** (pre-meeting plans) and **Minutes** (post-meeting approved records). Most scrapers only capture agendas, which rarely contain vote results.

Our scraper detects and clicks the "View Minutes" link for each meeting, then:
1. Waits for the minutes content to load (AJAX-rendered)
2. Intercepts the BD-GetMinutes API response
3. Extracts the full minutes body text
4. Appends it as a separate section in the raw output

The rule engine then parses minutes-specific patterns that don't appear in agendas:
- **Roll call votes**: "Mr. Smith - Aye, Ms. Jones - No"
- **Aye/Nay lists**: "Ayes: Smith, Jones, Williams; Nays: Brown"
- **Motion blocks**: "Motion by Smith, seconded by Jones"
- **Attendance**: "Members Present: ..., Members Absent: ..."
- **Vote tallies**: "Motion carried 5-2", "Motion failed"

This is what unlocks individual vote records — the single most valuable data point for governance analysis.

### Why Not Just Use an LLM?

The naive approach — send every document to GPT-4 and ask it to extract structured data — works for demos but fails as an engineering solution:

| | Rule Engine | LLM-Only |
|---|---|---|
| **Cost per meeting** | $0.00 | ~$0.02-0.05 |
| **Annual cost at 200K meetings** | $0.00 | $4,000-10,000 |
| **Processing speed** | <1 sec total | Minutes |
| **Determinism** | 100% reproducible | Variable |
| **Scaling cost** | $0 marginal | Linear |

Our rule engine handles 95%+ of documents at zero marginal cost. An optional LLM fallback exists for genuinely ambiguous cases but has not been needed in production runs.

The engine works because BoardDocs districts share structural conventions: section headers follow `=== N.TITLE ===` patterns, item types (consent agenda, personnel, budget) are consistently named, and vote language ("carried unanimously", "motion by X, seconded by Y") follows predictable formats.

### Category Classification

15 policy categories with 200+ regex patterns:

| Category | Examples |
|----------|----------|
| Personnel | Hiring, termination, salary schedules, coaching appointments |
| Budget & Finance | Budget adoption, purchase orders, contracts, audit reports |
| Curriculum & Instruction | Textbook adoption, field trips, professional development |
| Facilities | Construction, maintenance, facility naming, architect services |
| Policy | Board policy review, regulation amendments, governance |
| Student Affairs | Discipline, attendance, school calendar, dress code |
| Consent Agenda | Bundled routine approvals |
| Procedural | Call to order, adjournment, approval of agenda/minutes |
| Admin & Operations | Superintendent reports, presentations, board business |
| Community Relations | Public hearings, citizen comments, partnerships |
| + 5 more | Technology, Safety, DEI, Special Ed, Other |

Items are classified by scoring regex matches across all categories. The classifier strips common prefixes ("A.", "Consent - ") before matching to handle format variations.

### Confidence Scoring

Every extraction carries a confidence level:
- **High**: Explicit vote language found (roll call, vote counts, "carried unanimously")
- **Medium**: Item type strongly suggests a vote (consent agenda, policy approval)
- **Low**: Ambiguous — may or may not involve a formal vote

A post-processing step recalculates unanimity from actual individual vote data, catching edge cases where agenda text says "unanimous" but minutes reveal dissent.

## System Components

```
school-board-votes/
  config/            Settings, district list (130 active districts in districts.json)
  database/          SQLAlchemy models (6 tables), CRUD operations, analytics queries
  scraper/           Playwright BoardDocs scraper + PDF/HTML scrapers
  extraction/        Rule engine (15 categories, minutes parser, vote detection)
  analytics/         Aggregation queries + Plotly visualizations
  interface/         Streamlit web app (6 pages)
  scripts/           CLI tools: scrape_all.py, run_extraction.py, run_analytics.py
  data/              Raw minutes, extracted JSON, SQLite database
  tests/             Unit tests
```

## Database Schema

```sql
districts         -- 130 active districts, NCES IDs, state, enrollment, platform
meetings          -- 1,634 meetings, dates, attendance, raw text
agenda_items      -- 20,506 items, categorized into 15 policy categories
votes             -- 5,790 formal votes, results, counts, confidence
individual_votes  -- 11,366 per-member roll-call records
board_members     -- 414 board member names, roles, first/last seen dates
```

## Setup

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure (optional — only needed for LLM fallback)
cp .env.example .env

# Scrape all districts
python3 scripts/scrape_all.py --max-meetings 12 --months-back 24

# Extract structured data
python3 scripts/run_extraction.py --no-llm

# Launch web interface
streamlit run interface/app.py
```

## Web Interface

Six interactive pages:

- **Dashboard**: Key metrics, state coverage map, category breakdowns, top dissenters
- **Contested Votes**: Non-unanimous votes with roll-call details, filterable by state and category
- **District Browser**: Drill into any district's meetings, agenda items, and votes
- **Vote Search**: Full-text search across all districts and policy categories
- **Member Profiles**: Individual board member voting records with dissent analysis
- **Trends**: Monthly patterns, district comparisons, category-level analytics

## Validation

### Data Quality Checks
- **Unanimity recalculation**: Post-processing verifies `is_unanimous` against actual individual vote records
- **Cross-reference**: Roll-call tallies are compared to extracted vote counts
- **Category audit**: Regular sampling of "other" bucket to identify missing patterns
- **Duplicate detection**: Individual vote deduplication within each motion (NO/ABSTAIN takes priority over YES when overlapping text regions produce conflicting entries)
- **Context boundaries**: Minutes parser bounds each motion's context window by adjacent vote blocks to prevent cross-contamination

### Known Limitations
- **Minutes availability**: ~55% of active districts have minutes published on BoardDocs (others are agenda-only)
- **Format variations**: Some districts use non-standard vote formatting that current patterns don't capture
- **"Other" category**: ~12% of voted items remain uncategorized (mostly "Motion by [Name]" items from minutes with uninformative titles)
- **Unanimity definition**: Abstentions (e.g., 8-0-1) are treated as unanimous since no opposition was recorded
- **Snapshot data**: Point-in-time scrape, not continuously updated (though the infrastructure supports scheduling)

## Technology Stack

- **Python 3.11+** with async/await for concurrent scraping
- **Playwright** for headless browser automation (BoardDocs is a JavaScript SPA)
- **SQLAlchemy** ORM with SQLite (WAL mode for write performance)
- **Streamlit** for the interactive web interface
- **Plotly** for data visualization
- **BeautifulSoup** for HTML parsing of minutes content
- **OpenAI API** (optional, unused in production — reserved for LLM fallback)

## Updating Data

The system supports incremental updates. To refresh data for new meetings:

```bash
# Re-scrape all districts (only fetches meetings not already saved)
python3 scripts/scrape_all.py --max-meetings 12 --months-back 6

# Re-scrape a specific state
python3 scripts/run_scraper.py --state NY

# Re-run extraction on newly scraped meetings
python3 scripts/run_extraction.py --no-llm

# Re-run extraction for a specific state
python3 scripts/run_extraction.py --state CA --no-llm
```

**How incremental works:** The scraper saves raw text files per meeting (one file per meeting date per district). The extraction pipeline processes all raw text files for each district. To avoid duplicate database entries, clear existing meeting data before re-extracting, or check for existing meetings by date before inserting.

**Recommended schedule:** Monthly re-scrape captures most regular board meetings (held monthly or biweekly). The full pipeline (scrape + extract for all districts) takes approximately 2-3 hours due to Playwright browser automation delays.

## Next Steps

1. **Expand district coverage**: Target 300+ districts across all 50 states
2. **PDF minutes pipeline**: Many non-BoardDocs districts publish minutes as PDFs with rich vote data
3. **Continuous scraping**: Scheduled jobs to re-scrape weekly and process only new meetings
4. **Pattern learning**: Use LLM to identify new extraction patterns from unmatched text, then add them to the rule engine automatically
5. **API layer**: REST API for programmatic access to the vote database
6. **Civic engagement tools**: Alerts when specific policy categories come up for a vote, legislator scorecards, cross-district policy comparison

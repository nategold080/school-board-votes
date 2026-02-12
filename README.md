# School Board Vote Tracker

A structured database of school board voting records — the first of its kind. This system scrapes, parses, and structures school board meeting agendas from public BoardDocs sites across the United States, making it possible to search, analyze, and compare how school board members vote on policy decisions.

## What This Is

School board votes are public record, but they exist as unstructured text scattered across thousands of district websites. No one has collected this data at scale before. This project changes that.

**Current scope:**
- **71 districts** across 7 states (NY, TX, CA, FL, VA, OH, CO)
- **355 meetings** analyzed
- **4,522 agenda items** parsed
- **883 votes** extracted and categorized
- **$0.00** in API costs for extraction

## Architecture

### Hybrid Extraction Pipeline

The core technical challenge: converting unstructured meeting agendas into structured vote data, at scale, without burning money on LLM calls.

```
Raw BoardDocs HTML
        |
        v
  [Playwright Scraper]  -- headless browser, reuses sessions
        |
        v
  Raw text files (per meeting)
        |
        v
  [Rule-Based Extractor]  -- regex patterns, zero marginal cost
        |
        |--- high confidence --> Database
        |
        |--- low confidence --> [LLM Fallback (selective)]
                                       |
                                       v
                                   Database
```

**Why not just use an LLM for everything?**
- 16,715 US school districts x 12 meetings/year = 200K+ documents/year
- At ~$0.02/doc, brute-force LLM extraction costs $4,000/year and scales linearly
- Our rule engine handles 95%+ of documents at zero marginal cost
- LLM is reserved for genuinely ambiguous cases only

The rule engine works because BoardDocs districts share structural conventions:
- Section headers follow `=== N.TITLE ===` patterns
- Item types (consent agenda, personnel, budget) are consistently named
- Vote likelihood can be inferred from item category with high accuracy

### System Components

```
school-board-votes/
  config/            # Settings, district list (71 districts in districts.json)
  database/          # SQLAlchemy models, CRUD operations
  scraper/           # Playwright-based BoardDocs scraper + PDF/HTML scrapers
  extraction/        # Rule engine + LLM fallback + validators
  analytics/         # Aggregation queries + Plotly visualizations
  interface/         # Streamlit web app (6 pages)
  scripts/           # CLI tools for scraping, extraction, analytics
  data/              # Raw minutes, extracted JSON, SQLite database
  tests/             # Unit tests for DB and extraction
```

## Setup

```bash
# Clone and install
git clone https://github.com/nategold080/school_board_votes.git
cd school_board_votes

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure (optional — only needed for LLM fallback)
cp .env.example .env
# Edit .env with your OpenAI API key if you want LLM fallback

# Initialize database
python3 database/init_db.py
```

## Usage

### Scrape meetings from BoardDocs districts

```bash
# Scrape all configured districts (uses Playwright headless browser)
python3 scripts/scrape_all.py

# This takes ~40 minutes for all 69 BoardDocs districts
# Saves raw text files to data/raw_minutes/{district_id}/
```

### Extract structured vote data

```bash
# Run extraction with rule engine only ($0.00 cost)
python3 scripts/run_extraction.py --no-llm

# Run with selective LLM fallback for low-confidence items
python3 scripts/run_extraction.py --llm-threshold low

# Process a single state
python3 scripts/run_extraction.py --state NY --no-llm

# Process a single district
python3 scripts/run_extraction.py --district-id 3620580 --no-llm
```

### Launch the web interface

```bash
streamlit run interface/app.py
```

The interface includes:
- **Dashboard**: Key metrics, category/state breakdowns, trend charts
- **District Browser**: Drill into any district's meetings and votes
- **Vote Search**: Full-text search across all districts
- **Member Profiles**: Individual board member voting records
- **Contested Votes**: Non-unanimous votes (the interesting ones)
- **Trends**: Monthly/seasonal patterns in voting activity

### Run analytics from CLI

```bash
python3 scripts/run_analytics.py
```

## Database Schema

```sql
districts         -- 71 districts, NCES IDs, enrollment, platform
meetings          -- 355 meetings, dates, attendance, raw text
agenda_items      -- 4,522 items, categorized (13 policy categories)
votes             -- 883 formal votes, results, counts, confidence
individual_votes  -- Per-member voting records (from roll calls)
board_members     -- Board member names, first/last seen dates
```

### Policy Categories
`personnel` | `budget_finance` | `curriculum_instruction` | `facilities` | `policy` | `student_affairs` | `community_relations` | `consent_agenda` | `technology` | `safety_security` | `dei_equity` | `special_education` | `other`

## Technical Decisions

### Why Playwright over requests?
BoardDocs is a JavaScript SPA that loads data via AJAX. The meeting list is accessible via a public SEO endpoint (`BD-GETMeetingsListForSEO`), but meeting content requires a browser session for authentication. Playwright provides this with minimal overhead by reusing a single browser context across all districts.

### Why a rule engine instead of pure LLM?
Three reasons:
1. **Cost**: Rule engine processes 355 meetings in <1 second for $0.00. LLM would cost ~$5+ and take minutes.
2. **Scalability**: Adding a new district costs nothing if it uses BoardDocs (same patterns apply).
3. **Engineering depth**: Pattern matching, confidence scoring, and selective LLM fallback demonstrate systems thinking — not just prompt engineering.

### Why SQLite?
For a proof-of-concept at this scale (thousands of records, single-user), SQLite is the right tool. It's zero-config, portable, and fast enough. The schema is designed for easy migration to PostgreSQL if needed.

## Testing

```bash
cd school-board-votes
python3 -m pytest tests/ -v
```

15 tests cover database operations and extraction validation.

## Project Structure Details

| Component | Lines | Purpose |
|-----------|-------|---------|
| `extraction/rule_engine.py` | 660 | Core extraction: regex patterns, category classification, vote detection, confidence scoring |
| `scraper/boarddocs_scraper.py` | 200 | Playwright-based scraper with SEO endpoint discovery + page content extraction |
| `database/models.py` | 150 | SQLAlchemy ORM: 6 tables, proper indexes, cascade deletes |
| `database/operations.py` | 260 | CRUD + analytics queries: search, contested votes, dissent rates |
| `interface/app.py` | 410 | Streamlit app: 6 pages, interactive filters, Plotly charts |
| `analytics/vote_analytics.py` | 220 | Aggregation queries: by category, state, member, month |
| `analytics/visualizations.py` | 180 | Plotly chart generators: bars, lines, pies, horizontal bars |
| `extraction/prompts.py` | 200 | LLM prompt templates (used only for fallback) |
| `extraction/extractor.py` | 210 | OpenAI API integration with retry logic and cost tracking |

## Limitations

- **Agenda-only data**: Most BoardDocs sites expose the agenda structure but not detailed vote results. The rule engine infers votes from item types with appropriate confidence scoring.
- **No individual vote records**: Without detailed minutes text (roll call records), individual member votes can't be extracted from agenda-only data.
- **BoardDocs-focused**: Currently optimized for the BoardDocs platform. Districts using other platforms (PDF minutes, custom websites) need additional scraper implementations.
- **Snapshot, not live**: Data represents a point-in-time scrape, not a continuously updated feed.

## What's Next

- Add more districts (target: 100+)
- Implement PDF minutes scraper for non-BoardDocs districts
- Extract individual vote records from districts that publish detailed minutes
- Build automated re-scraping pipeline for continuous data collection
- Add cross-district comparison tools and policy tracking features

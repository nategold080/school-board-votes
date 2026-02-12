"""CLI script to run the hybrid extraction pipeline on scraped minutes.

Uses the rule-based engine for all documents (zero marginal cost),
with optional LLM fallback for low-confidence extractions only.
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import date, datetime
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import RAW_MINUTES_DIR, EXTRACTED_DIR, DATABASE_PATH
from extraction.rule_engine import HybridExtractor, RuleBasedExtractor, ExtractedMeeting
from database.models import init_database, get_session
from database.operations import DatabaseOperations
from scraper.district_discovery import load_districts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("extraction.log"),
    ]
)
logger = logging.getLogger(__name__)


def load_raw_minutes(district_id: str) -> list[dict]:
    """Load all raw minutes files for a district."""
    district_dir = RAW_MINUTES_DIR / district_id
    if not district_dir.exists():
        return []

    minutes = []
    for file_path in sorted(district_dir.glob("*.txt")):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        # Extract date from filename (format: DistrictName_YYYY-MM-DD.txt)
        name = file_path.stem
        date_str = name.split("_")[-1]
        minutes.append({
            "file_path": str(file_path),
            "text": text,
            "date_str": date_str,
            "district_id": district_id,
        })
    return minutes


def save_meeting_to_db(db_ops: DatabaseOperations, district_id: str,
                       meeting: ExtractedMeeting, raw_text: str,
                       date_str: str) -> int:
    """Save an extracted meeting to the database. Returns vote count."""
    # Parse date
    try:
        parts = date_str.split("-")
        if len(parts) == 3:
            meeting_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        else:
            meeting_date = meeting.meeting_date or date.today()
    except (ValueError, IndexError):
        meeting_date = meeting.meeting_date or date.today()

    # Save meeting
    db_meeting = db_ops.add_meeting(
        district_id=district_id,
        meeting_date=meeting_date,
        meeting_type=meeting.meeting_type,
        source_url=None,
        raw_text=raw_text[:10000],
        members_present=meeting.members_present,
        members_absent=meeting.members_absent,
        extraction_confidence=meeting.extraction_confidence,
    )

    # Update board members
    for member in meeting.members_present:
        db_ops.upsert_board_member(district_id, member, seen_date=meeting_date)
    for member in meeting.members_absent:
        db_ops.upsert_board_member(district_id, member, seen_date=meeting_date)

    # Save agenda items and votes
    vote_count = 0
    for item in meeting.agenda_items:
        db_item = db_ops.add_agenda_item(
            meeting_id=db_meeting.meeting_id,
            item_title=item.item_title,
            item_number=item.item_number,
            item_description=item.item_description,
            item_category=item.item_category,
            has_vote=item.has_vote,
        )

        if item.has_vote:
            vote = db_ops.add_vote(
                item_id=db_item.item_id,
                motion_text=item.motion_text,
                vote_type=item.vote_type,
                result=item.result,
                votes_for=item.votes_for,
                votes_against=item.votes_against,
                votes_abstain=getattr(item, 'votes_abstain', None),
                is_unanimous=item.is_unanimous,
                confidence=item.confidence,
            )

            for iv in item.individual_votes:
                db_ops.add_individual_vote(
                    vote_id=vote.vote_id,
                    member_name=iv["member_name"],
                    member_vote=iv["member_vote"],
                )

            vote_count += 1

    return vote_count


def run_extraction(districts: list[dict], db_ops: DatabaseOperations,
                   extractor: HybridExtractor):
    """Run extraction on all districts."""
    total_votes = 0
    total_meetings = 0
    total_items = 0

    for i, district in enumerate(districts, 1):
        district_id = district["district_id"]
        name = district["district_name"]
        logger.info(f"\n[{i}/{len(districts)}] Extracting: {name}")

        # Ensure district exists in DB
        db_ops.upsert_district(
            district_id=district_id,
            district_name=name,
            state=district["state"],
            enrollment=district.get("enrollment"),
            county=district.get("county"),
            minutes_url=district.get("minutes_url"),
            platform=district.get("platform"),
        )

        # Load raw minutes
        raw_minutes = load_raw_minutes(district_id)
        if not raw_minutes:
            logger.warning(f"  No raw minutes found for {name}")
            continue

        district_votes = 0
        for j, minutes_data in enumerate(raw_minutes, 1):
            logger.info(f"  [{j}/{len(raw_minutes)}] {minutes_data['date_str']}")

            try:
                # Run hybrid extraction (rule engine + selective LLM)
                meeting = extractor.extract(
                    minutes_data["text"],
                    district_id=district_id,
                )

                if not meeting.agenda_items:
                    logger.warning(f"    No agenda items found")
                    continue

                # Save to database
                vote_count = save_meeting_to_db(
                    db_ops, district_id, meeting,
                    minutes_data["text"], minutes_data["date_str"]
                )

                total_votes += vote_count
                total_meetings += 1
                total_items += len(meeting.agenda_items)
                district_votes += vote_count
                db_ops.commit()

                # Save extraction JSON
                extraction_file = EXTRACTED_DIR / f"{district_id}_{minutes_data['date_str']}.json"
                with open(extraction_file, "w") as f:
                    json.dump(asdict(meeting), f, indent=2, default=str)

                item_count = len(meeting.agenda_items)
                logger.info(f"    -> {item_count} items, {vote_count} votes [{meeting.extraction_method}]")

            except Exception as e:
                logger.error(f"    Failed: {e}", exc_info=True)
                db_ops.rollback()
                continue

        logger.info(f"  District total: {district_votes} votes from {len(raw_minutes)} meetings")

    return total_meetings, total_votes, total_items


def main():
    parser = argparse.ArgumentParser(description="Run hybrid extraction pipeline")
    parser.add_argument("--state", type=str, help="Only process districts in this state")
    parser.add_argument("--district-id", type=str, help="Process a specific district")
    parser.add_argument("--limit", type=int, help="Max districts to process")
    parser.add_argument("--no-llm", action="store_true",
                        help="Disable LLM fallback (rule engine only)")
    parser.add_argument("--llm-threshold", type=str, default="low",
                        choices=["none", "low", "medium"],
                        help="Confidence threshold for LLM fallback")
    args = parser.parse_args()

    # Initialize database
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_database(str(DATABASE_PATH))
    session = get_session(str(DATABASE_PATH))
    db_ops = DatabaseOperations(session)

    # Initialize hybrid extractor
    llm_extractor = None
    if not args.no_llm:
        try:
            from extraction.extractor import ExtractionPipeline
            llm_extractor = ExtractionPipeline()
            logger.info("LLM fallback enabled (selective use for low-confidence extractions)")
        except Exception as e:
            logger.warning(f"LLM fallback unavailable: {e}")

    threshold = "none" if args.no_llm else args.llm_threshold
    extractor = HybridExtractor(
        llm_extractor=llm_extractor,
        confidence_threshold=threshold,
    )

    # Load districts
    districts = load_districts()
    if args.state:
        districts = [d for d in districts if d["state"] == args.state.upper()]
    if args.district_id:
        districts = [d for d in districts if d["district_id"] == args.district_id]
    if args.limit:
        districts = districts[:args.limit]

    logger.info(f"Processing {len(districts)} districts (LLM threshold: {threshold})")

    total_meetings, total_votes, total_items = run_extraction(districts, db_ops, extractor)

    stats = extractor.get_stats()
    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Districts processed: {len(districts)}")
    print(f"Meetings processed: {total_meetings}")
    print(f"Agenda items found: {total_items}")
    print(f"Votes extracted: {total_votes}")
    print(f"{'='*60}")
    print(f"Rule engine only: {stats['rule_only']}")
    print(f"LLM fallback calls: {stats['llm_calls']}")
    print(f"LLM call rate: {stats['llm_rate']:.1%}")
    print(f"API cost: $0.00 (rule-engine)" if stats['llm_calls'] == 0
          else f"API cost: ~${stats['llm_calls'] * 0.02:.2f} (estimated)")
    print(f"{'='*60}")

    session.close()


if __name__ == "__main__":
    main()

"""Script to help manually validate a sample of extracted votes."""

import sys
import json
import random
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DATABASE_PATH
from database.models import get_session, Vote, AgendaItem, Meeting, District, IndividualVote
from database.operations import DatabaseOperations

logging.basicConfig(level=logging.INFO)


def main():
    session = get_session(str(DATABASE_PATH))

    # Get a random sample of votes
    all_votes = (
        session.query(Vote, AgendaItem, Meeting, District)
        .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
        .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
        .join(District, Meeting.district_id == District.district_id)
        .all()
    )

    if len(all_votes) == 0:
        print("No votes in database to validate.")
        return

    sample_size = min(30, len(all_votes))
    sample = random.sample(all_votes, sample_size)

    print(f"\n{'='*70}")
    print(f"VALIDATION SAMPLE: {sample_size} votes from {len(all_votes)} total")
    print(f"{'='*70}\n")

    validation_results = []

    for i, (vote, item, meeting, district) in enumerate(sample, 1):
        print(f"\n--- Vote {i}/{sample_size} ---")
        print(f"District: {district.district_name} ({district.state})")
        print(f"Date: {meeting.meeting_date}")
        print(f"Item: {item.item_title}")
        print(f"Category: {item.item_category}")
        print(f"Motion: {vote.motion_text or 'N/A'}")
        print(f"Result: {vote.result} ({'Unanimous' if vote.is_unanimous else 'Contested'})")
        print(f"Votes: {vote.votes_for}-{vote.votes_against}-{vote.votes_abstain}")
        print(f"Confidence: {vote.confidence}")

        # Get individual votes
        ind_votes = session.query(IndividualVote).filter(
            IndividualVote.vote_id == vote.vote_id).all()
        if ind_votes:
            print(f"Individual votes: {', '.join(f'{iv.member_name}={iv.member_vote}' for iv in ind_votes)}")

        print(f"Source: {meeting.source_url or 'N/A'}")

        validation_results.append({
            "vote_id": vote.vote_id,
            "district": district.district_name,
            "state": district.state,
            "date": str(meeting.meeting_date),
            "item_title": item.item_title,
            "category": item.item_category,
            "result": vote.result,
            "is_unanimous": vote.is_unanimous,
            "confidence": vote.confidence,
            "has_individual_votes": len(ind_votes) > 0,
            "num_individual_votes": len(ind_votes),
        })

    # Save validation sample
    output_path = Path("validation_sample.json")
    with open(output_path, "w") as f:
        json.dump(validation_results, f, indent=2)

    print(f"\n\nValidation sample saved to {output_path}")
    print(f"\nSummary:")
    print(f"  Total votes sampled: {sample_size}")
    print(f"  With individual votes: {sum(1 for v in validation_results if v['has_individual_votes'])}")
    print(f"  High confidence: {sum(1 for v in validation_results if v['confidence'] == 'high')}")
    print(f"  Medium confidence: {sum(1 for v in validation_results if v['confidence'] == 'medium')}")
    print(f"  Low confidence: {sum(1 for v in validation_results if v['confidence'] == 'low')}")

    session.close()


if __name__ == "__main__":
    main()

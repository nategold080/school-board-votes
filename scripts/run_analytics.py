"""CLI script to compute analytics from extracted data."""

import sys
import json
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DATABASE_PATH
from database.models import init_database, get_session
from database.operations import DatabaseOperations
from analytics.vote_analytics import VoteAnalytics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    session = get_session(str(DATABASE_PATH))
    db_ops = DatabaseOperations(session)
    analytics = VoteAnalytics(session)

    print("=" * 60)
    print("SCHOOL BOARD VOTE ANALYTICS")
    print("=" * 60)

    # Basic stats
    stats = db_ops.get_vote_statistics()
    print(f"\nOverview:")
    print(f"  Districts: {stats['total_districts']}")
    print(f"  Meetings: {stats['total_meetings']}")
    print(f"  Total votes: {stats['total_votes']}")
    print(f"  Unanimous: {stats['unanimous_votes']} ({stats['unanimity_rate']:.1%})")
    print(f"  Contested: {stats['contested_votes']}")
    print(f"  Individual vote records: {stats['total_individual_votes']}")

    # Category breakdown
    print(f"\nVotes by Category:")
    categories = analytics.votes_by_category()
    for cat in categories:
        print(f"  {cat['category']:25s} {cat['total_votes']:4d} votes  "
              f"({cat['contested_pct']:.0f}% contested)")

    # Top dissenters
    print(f"\nTop Dissenters (members who vote 'no' most often):")
    dissenters = analytics.top_dissenters(limit=15)
    for d in dissenters:
        print(f"  {d['member_name']:30s} {d['no_votes']:3d}/{d['total_votes']:3d} "
              f"no votes ({d['dissent_rate']:.1%})")

    # State comparison
    print(f"\nVotes by State:")
    states = analytics.votes_by_state()
    for s in states:
        print(f"  {s['state']:5s} {s['total_votes']:4d} votes, "
              f"{s['districts']:2d} districts, "
              f"{s['contested_pct']:.0f}% contested")

    # Most contested topics
    print(f"\nMost Contested Topics (highest dissent rate):")
    contested = analytics.most_contested_categories()
    for c in contested:
        print(f"  {c['category']:25s} {c['contested_pct']:.0f}% contested "
              f"({c['contested_votes']}/{c['total_votes']})")

    session.close()


if __name__ == "__main__":
    main()

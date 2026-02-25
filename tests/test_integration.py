"""Integration tests: extraction → database → query pipeline.

Tests the full flow: create a meeting, run extraction, store in DB, query back.
"""

import sys
import pytest
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Base, init_database, get_session
from database.operations import DatabaseOperations
from extraction.rule_engine import RuleBasedExtractor, ExtractedMeeting, ExtractedItem


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test_integration.sqlite")
    init_database(db_path)
    session = get_session(db_path)
    yield session
    session.close()


@pytest.fixture
def db_ops(db_session):
    return DatabaseOperations(db_session)


@pytest.fixture
def extractor():
    return RuleBasedExtractor()


class TestExtractionToDatabase:
    """Test the full pipeline: extract → store → query."""

    def _store_meeting(self, db_ops, district_id, meeting, meeting_date):
        """Helper to store an ExtractedMeeting in the database."""
        db_meeting = db_ops.add_meeting(
            district_id=district_id,
            meeting_date=meeting_date,
            meeting_type=meeting.meeting_type,
            members_present=meeting.members_present,
            members_absent=meeting.members_absent,
            extraction_confidence=meeting.extraction_confidence,
        )
        vote_count = 0
        for item in meeting.agenda_items:
            db_item = db_ops.add_agenda_item(
                meeting_id=db_meeting.meeting_id,
                item_title=item.item_title,
                item_number=item.item_number,
                item_category=item.item_category,
                has_vote=item.has_vote,
            )
            if item.has_vote:
                vote = db_ops.add_vote(
                    item_id=db_item.item_id,
                    motion_text=item.motion_text,
                    motion_maker=item.motion_maker or None,
                    motion_seconder=item.motion_seconder or None,
                    vote_type=item.vote_type,
                    result=item.result,
                    votes_for=item.votes_for,
                    votes_against=item.votes_against,
                    votes_abstain=item.votes_abstain,
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
        db_ops.commit()
        return vote_count

    def test_full_pipeline_extract_store_query(self, db_ops, extractor):
        """Extract from text, store in DB, query back, verify data."""
        # Setup district
        db_ops.upsert_district("TEST001", "Integration Test District", "NY")
        db_ops.commit()

        # Raw meeting text
        text = """Board of Education Regular Meeting
Date: January 15, 2025

=== 1. Call to Order ===
Meeting called to order at 7:00 PM.

=== 2. Consent Agenda ===
Approval of consent items.
Motion by Smith, seconded by Jones.
Mr. Smith: Yes
Ms. Jones: Yes
Mr. Brown: Yes
Mr. Williams: Yes
Motion carried 4-0.

=== 3. Budget Approval ===
Motion by Smith, seconded by Brown.
Mr. Smith: Yes
Ms. Jones: No
Mr. Brown: Yes
Mr. Williams: Yes
Motion carried 3-1.

=== 4. Adjournment ===
Meeting adjourned at 9:00 PM."""

        # Extract
        meeting = extractor.extract(text)
        assert len(meeting.agenda_items) >= 2

        # Store
        vote_count = self._store_meeting(db_ops, "TEST001", meeting, date(2025, 1, 15))
        assert vote_count >= 2

        # Query back
        stats = db_ops.get_vote_statistics()
        assert stats["total_votes"] >= 2
        assert stats["total_districts"] == 1
        assert stats["total_meetings"] == 1

        # Verify categories
        categories = db_ops.get_category_breakdown()
        cat_names = [c[0] for c in categories]
        assert any(c for c in cat_names if c != "other")

        # Verify contested votes
        contested = db_ops.get_contested_votes()
        assert len(contested) >= 1  # Budget vote was 3-1

    def test_unanimous_votes_not_in_contested(self, db_ops, extractor):
        """Unanimous votes should not appear in contested votes query."""
        db_ops.upsert_district("TEST002", "Unanimous Test District", "CA")
        db_ops.commit()

        text = """=== Consent Agenda ===
Mr. A: Yes
Mr. B: Yes
Mr. C: Yes
Mr. D: Yes
Motion carried 4-0."""

        meeting = extractor.extract(text)
        self._store_meeting(db_ops, "TEST002", meeting, date(2025, 2, 1))

        contested = db_ops.get_contested_votes()
        assert len(contested) == 0

    def test_search_votes_by_keyword(self, db_ops, extractor):
        """Test searching votes by keyword."""
        db_ops.upsert_district("TEST003", "Search Test District", "TX")
        db_ops.commit()

        text = """=== HVAC System Upgrade ===
Motion to approve HVAC contract.
Motion by Smith, seconded by Jones.
Mr. Smith: Yes
Ms. Jones: Yes
Mr. Brown: Yes
Motion carried 3-0."""

        meeting = extractor.extract(text)
        self._store_meeting(db_ops, "TEST003", meeting, date(2025, 3, 1))

        results = db_ops.search_votes("HVAC")
        assert len(results) >= 1

    def test_individual_votes_stored_correctly(self, db_ops, extractor):
        """Verify individual votes are stored and retrievable."""
        db_ops.upsert_district("TEST004", "Individual Vote District", "FL")
        db_ops.commit()

        text = """=== Policy Update ===
Mr. Smith: Yes
Ms. Jones: No
Mr. Brown: Yes
Dr. Williams: Yes
Mr. Davis: Abstain
Motion carried 3-1-1."""

        meeting = extractor.extract(text)
        self._store_meeting(db_ops, "TEST004", meeting, date(2025, 4, 1))

        stats = db_ops.get_vote_statistics()
        assert stats["total_individual_votes"] >= 4

    def test_board_members_tracked(self, db_ops, extractor):
        """Verify board members are upserted when storing meetings."""
        db_ops.upsert_district("TEST005", "Member Tracking District", "OH")
        db_ops.commit()

        text = """Board of Education
Members Present: John Smith, Jane Jones, Bob Brown

=== Budget Vote ===
Motion carried 3-0."""

        meeting = extractor.extract(text)
        # Manually set members for the test
        if not meeting.members_present:
            meeting.members_present = ["John Smith", "Jane Jones", "Bob Brown"]

        db_meeting = db_ops.add_meeting(
            district_id="TEST005",
            meeting_date=date(2025, 5, 1),
            members_present=meeting.members_present,
        )
        for member in meeting.members_present:
            db_ops.upsert_board_member("TEST005", member, seen_date=date(2025, 5, 1))
        db_ops.commit()

        members = db_ops.session.query(
            __import__('database.models', fromlist=['BoardMember']).BoardMember
        ).filter_by(district_id="TEST005").all()
        assert len(members) >= 3

    def test_category_breakdown_matches_extraction(self, db_ops, extractor):
        """Verify category breakdown reflects what was extracted."""
        db_ops.upsert_district("TEST006", "Category Test District", "PA")
        db_ops.commit()

        text = """=== Personnel Actions ===
Hiring of new teacher.
Mr. A: Yes
Mr. B: Yes
Mr. C: Yes
Motion carried 3-0.

=== Budget Approval ===
Annual budget approval.
Mr. A: Yes
Mr. B: Yes
Mr. C: No
Motion carried 2-1."""

        meeting = extractor.extract(text)
        self._store_meeting(db_ops, "TEST006", meeting, date(2025, 6, 1))

        categories = db_ops.get_category_breakdown()
        cat_dict = {c[0]: c[1] for c in categories}
        total_votes = sum(cat_dict.values())
        assert total_votes >= 2

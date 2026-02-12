"""Tests for database operations."""

import sys
import pytest
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Base, init_database, get_session
from database.operations import DatabaseOperations


@pytest.fixture
def db_session(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.sqlite")
    init_database(db_path)
    session = get_session(db_path)
    yield session
    session.close()


@pytest.fixture
def db_ops(db_session):
    return DatabaseOperations(db_session)


class TestDistrictOperations:
    def test_upsert_district(self, db_ops):
        d = db_ops.upsert_district("1234567", "Test District", "NY", enrollment=5000)
        db_ops.commit()
        assert d.district_id == "1234567"
        assert d.district_name == "Test District"
        assert d.state == "NY"
        assert d.enrollment == 5000

    def test_upsert_district_update(self, db_ops):
        db_ops.upsert_district("1234567", "Test District", "NY", enrollment=5000)
        d = db_ops.upsert_district("1234567", "Test District Updated", "NY", enrollment=6000)
        db_ops.commit()
        assert d.district_name == "Test District Updated"
        assert d.enrollment == 6000

    def test_get_all_districts(self, db_ops):
        db_ops.upsert_district("001", "District A", "NY")
        db_ops.upsert_district("002", "District B", "TX")
        db_ops.commit()
        districts = db_ops.get_all_districts()
        assert len(districts) == 2


class TestMeetingOperations:
    def test_add_meeting(self, db_ops):
        db_ops.upsert_district("001", "Test District", "NY")
        m = db_ops.add_meeting(
            district_id="001",
            meeting_date=date(2025, 1, 15),
            meeting_type="regular",
            members_present=["Smith", "Jones"],
        )
        db_ops.commit()
        assert m.meeting_id is not None
        assert m.district_id == "001"


class TestVoteOperations:
    def test_full_vote_chain(self, db_ops):
        db_ops.upsert_district("001", "Test District", "NY")
        meeting = db_ops.add_meeting("001", date(2025, 1, 15))
        item = db_ops.add_agenda_item(meeting.meeting_id, "Budget Approval",
                                       item_category="budget_finance", has_vote=True)
        vote = db_ops.add_vote(item.item_id, motion_text="Approve budget",
                                result="passed", votes_for=5, votes_against=2,
                                is_unanimous=False)
        iv1 = db_ops.add_individual_vote(vote.vote_id, "Smith", "yes")
        iv2 = db_ops.add_individual_vote(vote.vote_id, "Jones", "no")
        db_ops.commit()

        assert vote.vote_id is not None
        assert iv1.individual_vote_id is not None

    def test_search_votes(self, db_ops):
        db_ops.upsert_district("001", "Test District", "NY")
        meeting = db_ops.add_meeting("001", date(2025, 1, 15))
        item = db_ops.add_agenda_item(meeting.meeting_id, "HVAC System Upgrade",
                                       item_category="facilities", has_vote=True)
        db_ops.add_vote(item.item_id, motion_text="Approve HVAC contract",
                         result="passed", is_unanimous=True)
        db_ops.commit()

        results = db_ops.search_votes("HVAC")
        assert len(results) == 1

    def test_contested_votes(self, db_ops):
        db_ops.upsert_district("001", "Test District", "NY")
        meeting = db_ops.add_meeting("001", date(2025, 1, 15))

        # Unanimous vote
        item1 = db_ops.add_agenda_item(meeting.meeting_id, "Item 1", has_vote=True)
        db_ops.add_vote(item1.item_id, result="passed", is_unanimous=True)

        # Contested vote
        item2 = db_ops.add_agenda_item(meeting.meeting_id, "Item 2", has_vote=True)
        db_ops.add_vote(item2.item_id, result="passed", is_unanimous=False,
                         votes_for=4, votes_against=3)
        db_ops.commit()

        contested = db_ops.get_contested_votes()
        assert len(contested) == 1

    def test_vote_statistics(self, db_ops):
        db_ops.upsert_district("001", "Test District", "NY")
        meeting = db_ops.add_meeting("001", date(2025, 1, 15))
        item = db_ops.add_agenda_item(meeting.meeting_id, "Test", has_vote=True)
        db_ops.add_vote(item.item_id, result="passed", is_unanimous=True)
        db_ops.commit()

        stats = db_ops.get_vote_statistics()
        assert stats["total_votes"] == 1
        assert stats["total_districts"] == 1

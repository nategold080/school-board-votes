"""Tests for extraction validation and schema handling."""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from extraction.validator import validate_vote, validate_extraction
from extraction.schemas import MeetingExtractionData, VoteData


class TestVoteValidation:
    def test_valid_vote(self):
        vote = {
            "motion_text": "Approve the budget",
            "vote_type": "roll_call",
            "result": "passed",
            "votes_for": 5,
            "votes_against": 2,
            "is_unanimous": False,
            "individual_votes": [
                {"member_name": "Smith", "member_vote": "yes"},
                {"member_name": "Jones", "member_vote": "no"},
            ],
            "confidence": "high",
        }
        result = validate_vote(vote)
        assert result["vote_type"] == "roll_call"
        assert result["result"] == "passed"
        assert len(result["individual_votes"]) == 2

    def test_normalize_result_variants(self):
        for input_val, expected in [
            ("approved", "passed"),
            ("carried", "passed"),
            ("defeated", "failed"),
            ("denied", "failed"),
            ("tabled for discussion", "tabled"),
            ("withdrawn by maker", "withdrawn"),
            ("amended and approved", "amended_and_passed"),
        ]:
            vote = {"result": input_val}
            result = validate_vote(vote)
            assert result["result"] == expected, f"'{input_val}' should become '{expected}'"

    def test_normalize_member_votes(self):
        vote = {
            "individual_votes": [
                {"member_name": "Smith", "member_vote": "aye"},
                {"member_name": "Jones", "member_vote": "nay"},
                {"member_name": "Brown", "member_vote": "for"},
            ]
        }
        result = validate_vote(vote)
        votes = {v["member_name"]: v["member_vote"] for v in result["individual_votes"]}
        assert votes["Smith"] == "yes"
        assert votes["Jones"] == "no"
        assert votes["Brown"] == "yes"

    def test_invalid_vote_type_defaults(self):
        vote = {"vote_type": "hand_raise"}
        result = validate_vote(vote)
        assert result["vote_type"] == "voice"

    def test_numeric_field_cleanup(self):
        vote = {"votes_for": "5", "votes_against": "2", "votes_abstain": None}
        result = validate_vote(vote)
        assert result["votes_for"] == 5
        assert result["votes_against"] == 2
        assert result["votes_abstain"] is None


class TestExtractionValidation:
    def test_full_extraction(self):
        raw = {
            "meeting_type": "regular",
            "members_present": ["Smith", "Jones", "Brown"],
            "members_absent": ["White"],
            "agenda_items": [
                {
                    "item_number": "1",
                    "item_title": "Call to Order",
                    "has_vote": False,
                    "item_category": "other",
                },
                {
                    "item_number": "2",
                    "item_title": "Budget Approval",
                    "has_vote": True,
                    "item_category": "budget_finance",
                    "vote": {
                        "motion_text": "Approve the 2025 budget",
                        "vote_type": "roll_call",
                        "result": "passed",
                        "votes_for": 3,
                        "votes_against": 0,
                        "is_unanimous": True,
                        "individual_votes": [
                            {"member_name": "Smith", "member_vote": "yes"},
                            {"member_name": "Jones", "member_vote": "yes"},
                            {"member_name": "Brown", "member_vote": "yes"},
                        ],
                        "confidence": "high",
                    },
                },
            ],
            "extraction_confidence": "high",
        }
        result = validate_extraction(raw)
        assert isinstance(result, MeetingExtractionData)
        assert len(result.agenda_items) == 2
        assert result.agenda_items[1].has_vote is True
        assert result.agenda_items[1].vote.result == "passed"

    def test_extraction_with_no_votes(self):
        raw = {
            "meeting_type": "work_session",
            "members_present": ["Smith"],
            "members_absent": [],
            "agenda_items": [
                {"item_title": "Discussion Item", "has_vote": False},
            ],
        }
        result = validate_extraction(raw)
        assert len(result.agenda_items) == 1
        assert result.agenda_items[0].vote is None

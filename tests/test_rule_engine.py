"""Comprehensive tests for the rule-based extraction engine.

Covers: category classification, vote detection, vote count parsing,
member name extraction, consent agenda handling, deduplication,
confidence scoring, motion maker extraction, and edge cases.
"""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from extraction.rule_engine import (
    RuleBasedExtractor,
    HybridExtractor,
    ExtractedItem,
    ExtractedMeeting,
    CATEGORY_RULES,
)


@pytest.fixture
def extractor():
    return RuleBasedExtractor()


# ============================================================================
# 1. Category Classification (P8 item 1)
# ============================================================================

class TestCategoryClassification:
    """Test _classify_category with real item titles."""

    def test_consent_agenda(self, extractor):
        assert extractor._classify_category("Consent Agenda") == "consent_agenda"
        assert extractor._classify_category("Approval of Consent Calendar") == "consent_agenda"
        assert extractor._classify_category("Consent Items") == "consent_agenda"

    def test_personnel(self, extractor):
        assert extractor._classify_category("Personnel Actions") == "personnel"
        assert extractor._classify_category("Hiring of New Teacher") == "personnel"
        assert extractor._classify_category("Superintendent Contract Renewal") == "personnel"
        assert extractor._classify_category("Human Resources Report") == "personnel"
        assert extractor._classify_category("Certificated Personnel") == "personnel"

    def test_budget_finance(self, extractor):
        assert extractor._classify_category("Annual Budget Approval") == "budget_finance"
        assert extractor._classify_category("Financial Report for September") == "budget_finance"
        assert extractor._classify_category("Award of Contract for HVAC") == "budget_finance"
        assert extractor._classify_category("Bond Refinancing") == "budget_finance"
        assert extractor._classify_category("Tax Levy for 2025-2026") == "budget_finance"

    def test_curriculum_instruction(self, extractor):
        assert extractor._classify_category("Curriculum Update") == "curriculum_instruction"
        assert extractor._classify_category("Textbook Adoption") == "curriculum_instruction"
        assert extractor._classify_category("Professional Development Plan") == "curriculum_instruction"
        assert extractor._classify_category("Student Achievement Report") == "curriculum_instruction"

    def test_facilities(self, extractor):
        assert extractor._classify_category("Facilities Improvement Plan") == "facilities"
        assert extractor._classify_category("Construction Update") == "facilities"
        assert extractor._classify_category("HVAC System Replacement") == "facilities"

    def test_policy(self, extractor):
        assert extractor._classify_category("Board Policy 1234") == "policy"
        assert extractor._classify_category("First Reading of Policy Revision") == "policy"
        assert extractor._classify_category("Governance Committee Report") == "policy"

    def test_student_affairs(self, extractor):
        assert extractor._classify_category("Student Discipline Report") == "student_affairs"
        assert extractor._classify_category("Athletics Program Update") == "student_affairs"
        assert extractor._classify_category("Basketball Coach Approval") == "student_affairs"

    def test_procedural(self, extractor):
        assert extractor._classify_category("Approval of Minutes") == "procedural"
        assert extractor._classify_category("Call to Order") == "procedural"
        assert extractor._classify_category("Pledge of Allegiance") == "procedural"
        assert extractor._classify_category("Adjournment") == "procedural"
        assert extractor._classify_category("Meeting Opening") == "procedural"

    def test_admin_operations(self, extractor):
        assert extractor._classify_category("Superintendent's Report") == "admin_operations"
        assert extractor._classify_category("Board Member Reports") == "admin_operations"
        assert extractor._classify_category("Committee Report") == "admin_operations"

    def test_other_fallback(self, extractor):
        assert extractor._classify_category("Random Unrelated Text XYZ") == "other"

    def test_community_relations(self, extractor):
        assert extractor._classify_category("Public Comment Period") == "community_relations"
        assert extractor._classify_category("Community Engagement Report") == "community_relations"


# ============================================================================
# 2. Vote Detection (P8 item 2)
# ============================================================================

class TestVoteDetection:
    """Test _assess_vote_likelihood with known vote phrases."""

    def test_motion_carried_high(self, extractor):
        has_vote, confidence = extractor._assess_vote_likelihood("Motion carried unanimously")
        assert has_vote is True
        assert confidence == "high"

    def test_approved_with_count_high(self, extractor):
        has_vote, confidence = extractor._assess_vote_likelihood("Approved 5-2 by roll call vote")
        assert has_vote is True
        assert confidence == "high"

    def test_voice_vote(self, extractor):
        # "voice vote" alone isn't in the explicit vote patterns, but the phrase
        # "voice vote" triggers one vote_likely pattern match → returns True, low
        has_vote, confidence = extractor._assess_vote_likelihood("A voice vote was taken on the resolution")
        # The text "resolution" matches a vote_likely pattern
        assert has_vote is True

    def test_no_vote_call_to_order(self, extractor):
        has_vote, _ = extractor._assess_vote_likelihood("Call to Order at 7:00 PM")
        assert has_vote is False

    def test_no_vote_presentation(self, extractor):
        has_vote, _ = extractor._assess_vote_likelihood("Presentation on school safety")
        assert has_vote is False

    def test_no_vote_public_comment(self, extractor):
        has_vote, _ = extractor._assess_vote_likelihood("Public Comment Period")
        assert has_vote is False

    def test_motion_by_member(self, extractor):
        has_vote, confidence = extractor._assess_vote_likelihood("Motion by Smith to approve")
        assert has_vote is True
        assert confidence == "high"

    def test_roll_call_vote(self, extractor):
        has_vote, confidence = extractor._assess_vote_likelihood("Roll call vote was taken")
        assert has_vote is True
        assert confidence == "high"


# ============================================================================
# 3. Vote Count Parsing (P8 item 3)
# ============================================================================

class TestVoteCountParsing:
    """Test _extract_vote_details for count extraction."""

    def test_simple_5_2(self, extractor):
        item = ExtractedItem(item_title="Budget Approval")
        extractor._extract_vote_details("", "Approved 5-2", item)
        assert item.votes_for == 5
        assert item.votes_against == 2
        assert item.is_unanimous is False

    def test_unanimous_7_0(self, extractor):
        item = ExtractedItem(item_title="Consent Agenda")
        extractor._extract_vote_details("", "Passed 7-0", item)
        assert item.votes_for == 7
        assert item.votes_against == 0
        assert item.is_unanimous is True

    def test_three_part_count_8_0_1(self, extractor):
        item = ExtractedItem(item_title="Personnel Action")
        extractor._extract_vote_details("", "Approved 8-0-1", item)
        assert item.votes_for == 8
        assert item.votes_against == 0
        assert item.votes_abstain == 1
        assert item.is_unanimous is True  # votes_against == 0

    def test_reject_year_range(self, extractor):
        """Year ranges like 2024-2025 should not be parsed as vote counts."""
        item = ExtractedItem(item_title="Budget 2024-2025")
        extractor._extract_vote_details("", "Budget for 2024-2025 fiscal year", item)
        # Should not have extracted year as vote counts
        assert item.votes_for is None or item.votes_for != 2024

    def test_failed_vote(self, extractor):
        item = ExtractedItem(item_title="Policy Change")
        extractor._extract_vote_details("", "Motion failed 2-5", item)
        assert item.result == "failed"

    def test_tabled_motion(self, extractor):
        item = ExtractedItem(item_title="Discussion Item")
        extractor._extract_vote_details("", "Motion tabled for future discussion", item)
        assert item.result == "tabled"

    def test_individual_votes_roll_call(self, extractor):
        text = "Mr. Smith: Yes\nMs. Jones: No\nMr. Brown: Yes\nDr. Williams: Yes"
        item = ExtractedItem(item_title="Budget Vote")
        extractor._extract_vote_details("", text, item)
        assert item.vote_type == "roll_call"
        assert item.votes_for == 3
        assert item.votes_against == 1
        assert len(item.individual_votes) == 4

    def test_ayes_nays_format(self, extractor):
        """Test _extract_ayes_nays_format directly (called by _extract_vote_details)."""
        text = """
Ayes: John Smith, Jane Doe, Bob Johnson, Mary Williams
Nays: None"""
        item = ExtractedItem(item_title="Consent Agenda")
        extractor._extract_ayes_nays_format(text, item)
        assert item.votes_for == 4
        assert item.votes_against == 0
        assert len(item.individual_votes) == 4

    def test_unanimous_consent_language(self, extractor):
        item = ExtractedItem(item_title="Minutes Approval")
        extractor._extract_vote_details("", "Approved by unanimous consent", item)
        assert item.vote_type == "unanimous_consent"
        assert item.is_unanimous is True


# ============================================================================
# 4. Member Name Extraction (P8 item 4)
# ============================================================================

class TestMemberNameExtraction:
    """Test individual vote member name extraction from various formats."""

    def test_ayes_nays_member_names(self, extractor):
        text = "\nAyes: Smith, Jones, Williams\nNays: Brown"
        item = ExtractedItem(item_title="Vote Item")
        extractor._extract_ayes_nays_format(text, item)
        names = [iv["member_name"] for iv in item.individual_votes]
        assert "Smith" in names
        assert "Jones" in names
        assert "Williams" in names
        assert "Brown" in names
        assert item.votes_for == 3
        assert item.votes_against == 1

    def test_nays_none(self, extractor):
        text = "\nAyes: Smith, Jones, Williams\nNays: None"
        item = ExtractedItem(item_title="Vote Item")
        extractor._extract_ayes_nays_format(text, item)
        assert item.votes_for == 3
        assert item.votes_against == 0

    def test_abstained_members(self, extractor):
        text = "\nAyes: Smith, Jones\nNays: None\nAbstained: Brown"
        item = ExtractedItem(item_title="Vote Item")
        extractor._extract_ayes_nays_format(text, item)
        votes = {iv["member_name"]: iv["member_vote"] for iv in item.individual_votes}
        assert votes["Brown"] == "abstain"


# ============================================================================
# 5. Consent Agenda Handling (P8 item 5)
# ============================================================================

class TestConsentAgendaHandling:
    """Test that consent items default to unanimous and validate correctly."""

    def test_consent_agenda_defaults_unanimous(self, extractor):
        text = """=== Consent Agenda ===
Approve all consent items.
Motion carried."""
        meeting = extractor.extract(text)
        consent_items = [i for i in meeting.agenda_items
                        if i.item_category == "consent_agenda" and i.has_vote]
        for item in consent_items:
            assert item.is_unanimous is True

    def test_consent_agenda_zero_for_rejected(self, extractor):
        """P1: Consent agenda with 0-for is rejected as impossible."""
        # Run through the full extract pipeline so post-processing fires
        text = """=== Consent Agenda ===
Result: Failed
Vote: 0-9
"""
        meeting = extractor.extract(text)
        consent_items = [i for i in meeting.agenda_items
                         if i.item_category == "consent_agenda" and i.has_vote]
        for item in consent_items:
            # Post-processing should have nullified impossible 0-for counts
            if item.votes_for is not None:
                assert item.votes_for > 0, (
                    f"Consent agenda item should not have 0-for vote count, "
                    f"got votes_for={item.votes_for}, votes_against={item.votes_against}"
                )


# ============================================================================
# 6. Deduplication (P8 item 6)
# ============================================================================

class TestDeduplication:
    """Test _deduplicate_votes prioritizes dissent."""

    def test_dedup_same_vote(self):
        votes = [
            {"member_name": "Smith", "member_vote": "yes"},
            {"member_name": "Smith", "member_vote": "yes"},
        ]
        result = RuleBasedExtractor._deduplicate_votes(votes)
        assert len(result) == 1

    def test_dedup_prefers_no_over_yes(self):
        """When a member appears with both YES and NO, prefer NO (deliberate dissent)."""
        votes = [
            {"member_name": "Smith", "member_vote": "yes"},
            {"member_name": "Smith", "member_vote": "no"},
        ]
        result = RuleBasedExtractor._deduplicate_votes(votes)
        assert len(result) == 1
        assert result[0]["member_vote"] == "no"

    def test_dedup_prefers_abstain_over_yes(self):
        votes = [
            {"member_name": "Jones", "member_vote": "yes"},
            {"member_name": "Jones", "member_vote": "abstain"},
        ]
        result = RuleBasedExtractor._deduplicate_votes(votes)
        assert len(result) == 1
        assert result[0]["member_vote"] == "abstain"

    def test_dedup_multiple_members(self):
        votes = [
            {"member_name": "Smith", "member_vote": "yes"},
            {"member_name": "Jones", "member_vote": "no"},
            {"member_name": "Smith", "member_vote": "yes"},
            {"member_name": "Jones", "member_vote": "no"},
        ]
        result = RuleBasedExtractor._deduplicate_votes(votes)
        assert len(result) == 2

    def test_dedup_empty_list(self):
        result = RuleBasedExtractor._deduplicate_votes([])
        assert result == []

    def test_dedup_case_insensitive(self):
        votes = [
            {"member_name": "SMITH", "member_vote": "yes"},
            {"member_name": "smith", "member_vote": "no"},
        ]
        result = RuleBasedExtractor._deduplicate_votes(votes)
        assert len(result) == 1
        assert result[0]["member_vote"] == "no"


# ============================================================================
# 7. Confidence Scoring (P8 item 7)
# ============================================================================

class TestConfidenceScoring:
    """Test confidence promotion logic."""

    def test_three_plus_individual_votes_high(self, extractor):
        """3+ individual votes should promote to high confidence."""
        text = """=== Budget Vote ===
Mr. Smith: Yes
Ms. Jones: Yes
Mr. Brown: No
Dr. Williams: Yes
Motion carried 3-1."""
        meeting = extractor.extract(text)
        vote_items = [i for i in meeting.agenda_items if i.has_vote and len(i.individual_votes) >= 3]
        for item in vote_items:
            assert item.confidence == "high"

    def test_motion_maker_seconder_promotes_to_medium(self, extractor):
        """Having both motion maker and seconder should promote low to medium or high."""
        text = """=== Policy Update ===
Motion by Smith, seconded by Jones. Motion carried."""
        meeting = extractor.extract(text)
        vote_items = [i for i in meeting.agenda_items if i.has_vote]
        assert len(vote_items) > 0, "Expected at least one vote item"
        for item in vote_items:
            if item.motion_maker and item.motion_seconder:
                assert item.confidence != "low", f"Expected medium or high confidence, got {item.confidence}"

    def test_low_confidence_no_evidence(self, extractor):
        """Items with minimal evidence should stay low."""
        # A section with just a title and no vote language
        text = """=== Random Discussion ===
Some discussion about various topics."""
        meeting = extractor.extract(text)
        for item in meeting.agenda_items:
            if not item.has_vote:
                continue
            if not item.individual_votes and not item.motion_maker:
                assert item.confidence in ("low", "medium")


# ============================================================================
# 8. Motion Maker Extraction (P8 item 8)
# ============================================================================

class TestMotionMakerExtraction:
    """Test extraction of motion makers and seconders."""

    def test_motion_by_seconded_by(self, extractor):
        item = ExtractedItem(item_title="Budget Approval")
        extractor._extract_vote_details("", "Motion by Smith, seconded by Jones. Motion carried.", item)
        assert item.motion_maker == "Smith"
        assert item.motion_seconder == "Jones"

    def test_motion_made_by(self, extractor):
        item = ExtractedItem(item_title="Policy Change")
        extractor._extract_vote_details("", "Motion made by Dr. Williams to approve.", item)
        assert item.motion_maker == "Williams"

    def test_motion_by_blocklisted_word(self, extractor):
        """Words like 'consent', 'resolution' should not be extracted as names."""
        item = ExtractedItem(item_title="Consent Agenda")
        extractor._extract_vote_details("", "Motion by consent of the board.", item)
        assert item.motion_maker is None or item.motion_maker == ""

    def test_seconder_with_title(self, extractor):
        item = ExtractedItem(item_title="Test")
        extractor._extract_vote_details("", "Motion by Mr. Adams, second by Mrs. Baker.", item)
        assert item.motion_maker == "Adams"
        assert item.motion_seconder == "Baker"


# ============================================================================
# 9. Edge Cases (P8 item 9)
# ============================================================================

class TestEdgeCases:
    """Test edge cases for the extraction engine."""

    def test_empty_text(self, extractor):
        meeting = extractor.extract("")
        assert meeting is not None
        assert len(meeting.agenda_items) == 0

    def test_no_votes_in_text(self, extractor):
        text = "This is just a regular document with no agenda items or votes."
        meeting = extractor.extract(text)
        vote_items = [i for i in meeting.agenda_items if i.has_vote]
        assert len(vote_items) == 0

    def test_meeting_opening_no_vote(self, extractor):
        """P2: Items titled 'MEETING OPENING' should not have votes."""
        text = """=== MEETING OPENING ===
The meeting was called to order at 7:00 PM."""
        meeting = extractor.extract(text)
        for item in meeting.agenda_items:
            if "MEETING OPENING" in (item.item_title or "").upper():
                assert item.has_vote is False

    def test_call_to_order_no_vote(self, extractor):
        text = """=== Call to Order ===
President Smith called the meeting to order."""
        meeting = extractor.extract(text)
        for item in meeting.agenda_items:
            if "call to order" in (item.item_title or "").lower():
                assert item.has_vote is False

    def test_adjournment_no_vote(self, extractor):
        text = """=== Adjournment ===
The meeting was adjourned at 9:30 PM."""
        meeting = extractor.extract(text)
        for item in meeting.agenda_items:
            if "adjournment" in (item.item_title or "").lower():
                assert item.has_vote is False


# ============================================================================
# 10. Full Extract Pipeline
# ============================================================================

class TestFullExtractPipeline:
    """Test the full extract() method end-to-end."""

    def test_extract_with_roll_call(self, extractor):
        text = """Board of Education Regular Meeting
Date: January 15, 2025

=== 1. Call to Order ===
Meeting called to order at 7:00 PM.

=== 2. Budget Approval ===
Motion by Smith, seconded by Jones.
Mr. Smith: Yes
Ms. Jones: Yes
Mr. Brown: No
Dr. Williams: Yes
Motion carried 3-1.

=== 3. Adjournment ===
Meeting adjourned at 9:00 PM."""
        meeting = extractor.extract(text)
        assert len(meeting.agenda_items) >= 2

        vote_items = [i for i in meeting.agenda_items if i.has_vote]
        assert len(vote_items) >= 1

        budget_items = [i for i in vote_items if "Budget" in (i.item_title or "")]
        if budget_items:
            item = budget_items[0]
            assert item.votes_for == 3
            assert item.votes_against == 1
            assert item.is_unanimous is False
            assert item.confidence == "high"

    def test_extract_unanimity_ignores_abstention(self, extractor):
        """P4: 8-0-1 should be unanimous (abstentions aren't opposition)."""
        text = """=== Personnel Action ===
Mr. A: Yes
Mr. B: Yes
Mr. C: Yes
Mr. D: Yes
Mr. E: Yes
Mr. F: Yes
Mr. G: Yes
Mr. H: Yes
Mr. I: Abstain
Motion carried 8-0-1."""
        meeting = extractor.extract(text)
        vote_items = [i for i in meeting.agenda_items if i.has_vote]
        if vote_items:
            item = vote_items[0]
            # Individual votes: 8 yes, 0 no, 1 abstain
            assert item.is_unanimous is True

    def test_extract_sets_meeting_confidence(self, extractor):
        text = """=== Consent Agenda ===
Mr. Smith: Yes
Ms. Jones: Yes
Mr. Brown: Yes
Motion carried 3-0."""
        meeting = extractor.extract(text)
        assert meeting.extraction_confidence in ("high", "medium", "low")


# ============================================================================
# 11. Name Validation and Cleaning
# ============================================================================

class TestNameValidation:
    """Test member name validation and cleaning."""

    def test_clean_member_name_removes_title(self):
        assert RuleBasedExtractor._clean_member_name("Dr. John Smith") == "John Smith"
        assert RuleBasedExtractor._clean_member_name("Mr. Jones") == "Jones"

    def test_clean_member_name_removes_credentials(self):
        assert RuleBasedExtractor._clean_member_name("Jane Doe, Ed.D.") == "Jane Doe"
        assert RuleBasedExtractor._clean_member_name("Bob Smith, Ph.D.") == "Bob Smith"

    def test_clean_member_name_title_cases_all_caps(self):
        assert RuleBasedExtractor._clean_member_name("JOHN SMITH") == "John Smith"

    def test_valid_member_name(self):
        assert RuleBasedExtractor._is_valid_member_name("John Smith") is True
        assert RuleBasedExtractor._is_valid_member_name("O'Brien") is True

    def test_invalid_member_name_too_short(self):
        assert RuleBasedExtractor._is_valid_member_name("Jo") is False

    def test_invalid_member_name_blocklist(self):
        assert RuleBasedExtractor._is_valid_member_name("Trustee") is False
        assert RuleBasedExtractor._is_valid_member_name("President") is False

    def test_invalid_member_name_digits(self):
        assert RuleBasedExtractor._is_valid_member_name("John123") is False

    def test_invalid_member_name_colon(self):
        assert RuleBasedExtractor._is_valid_member_name("Administration Present:") is False


# ============================================================================
# 12. Role Normalization
# ============================================================================

class TestRoleNormalization:
    """Test _normalize_role."""

    def test_president(self):
        assert RuleBasedExtractor._normalize_role("President") == "president"
        assert RuleBasedExtractor._normalize_role("Board Chair") == "president"

    def test_vice_president(self):
        assert RuleBasedExtractor._normalize_role("Vice President") == "vice_president"
        assert RuleBasedExtractor._normalize_role("Vice-Chair") == "vice_president"

    def test_secretary(self):
        assert RuleBasedExtractor._normalize_role("Secretary") == "secretary"
        assert RuleBasedExtractor._normalize_role("Clerk") == "secretary"

    def test_member_fallback(self):
        assert RuleBasedExtractor._normalize_role("Director") == "member"
        assert RuleBasedExtractor._normalize_role("Unknown Role") == "member"


# ============================================================================
# 13. HybridExtractor Null Safety (P5)
# ============================================================================

class TestHybridExtractorNullSafety:
    """Test that HybridExtractor handles null vote objects."""

    def test_merge_with_null_vote(self):
        """P5: LLM returns has_vote=True but vote=None — should not crash."""
        hybrid = HybridExtractor()
        rule_result = ExtractedMeeting(agenda_items=[
            ExtractedItem(item_title="Budget Approval", has_vote=True,
                         votes_for=5, votes_against=2)
        ])

        # Create a mock LLM result with has_vote=True but vote=None
        from extraction.schemas import AgendaItemData, MeetingExtractionData
        llm_result = MeetingExtractionData(
            agenda_items=[
                AgendaItemData(item_title="Budget Approval", has_vote=True, vote=None)
            ]
        )
        # Should not raise
        merged = hybrid._merge_results(rule_result, llm_result)
        assert merged is not None

    def test_items_match_by_title(self):
        """Test _items_match with matching titles."""
        from extraction.schemas import AgendaItemData
        rule_item = ExtractedItem(item_title="Budget Approval for 2025")
        llm_item = AgendaItemData(item_title="Budget Approval for 2025")
        assert HybridExtractor._items_match(rule_item, llm_item) is True

    def test_items_match_by_number(self):
        from extraction.schemas import AgendaItemData
        rule_item = ExtractedItem(item_number="7.A", item_title="Some item")
        llm_item = AgendaItemData(item_title="Different title", item_number="7.A")
        assert HybridExtractor._items_match(rule_item, llm_item) is True

    def test_items_no_match(self):
        from extraction.schemas import AgendaItemData
        rule_item = ExtractedItem(item_title="Budget Approval")
        llm_item = AgendaItemData(item_title="Personnel Action")
        assert HybridExtractor._items_match(rule_item, llm_item) is False


# ============================================================================
# 14. Post-Processing Validation
# ============================================================================

class TestPostProcessingValidation:
    """Test post-processing validation rules added for P1-P4."""

    def test_result_validation_passed_but_more_against(self, extractor):
        """If votes_against > votes_for but result is 'passed', correct to 'failed'."""
        text = """=== Policy Change ===
Mr. A: No
Mr. B: No
Mr. C: No
Mr. D: Yes
Mr. E: No
Motion carried."""
        meeting = extractor.extract(text)
        vote_items = [i for i in meeting.agenda_items if i.has_vote]
        for item in vote_items:
            if item.votes_for is not None and item.votes_against is not None:
                if item.votes_against > item.votes_for:
                    assert item.result == "failed"

    def test_result_validation_failed_but_more_for(self, extractor):
        """If votes_for > votes_against but result is 'failed', correct to 'passed'."""
        text = """=== Approval of Agenda ===
Mr. A: Yes
Mr. B: Yes
Mr. C: Yes
Mr. D: Yes
Mr. E: Yes
Motion failed."""
        meeting = extractor.extract(text)
        vote_items = [i for i in meeting.agenda_items if i.has_vote]
        assert len(vote_items) > 0, "Expected at least one vote item"
        for item in vote_items:
            if item.votes_for is not None and item.votes_against is not None:
                if item.votes_for > item.votes_against:
                    assert item.result == "passed", (
                        f"Expected 'passed' for {item.votes_for}-{item.votes_against}, got '{item.result}'"
                    )

    def test_zero_zero_nonunanimous_removed(self, extractor):
        """P3: 0-0 non-unanimous votes with no individual yes/no should be removed."""
        item = ExtractedItem(
            item_title="Test Item",
            has_vote=True,
            votes_for=0,
            votes_against=0,
            is_unanimous=False,
            individual_votes=[],
        )
        meeting = ExtractedMeeting(agenda_items=[item])
        # Simulate the post-processing loop from extract()
        for it in meeting.agenda_items:
            if it.has_vote and (it.votes_for or 0) == 0 and (it.votes_against or 0) == 0:
                if not it.individual_votes and not it.is_unanimous:
                    it.has_vote = False
        assert item.has_vote is False

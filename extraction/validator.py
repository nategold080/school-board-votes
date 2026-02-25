"""Validation for extraction outputs."""

import logging
from .schemas import MeetingExtractionData, VoteData, AgendaItemData

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    "personnel", "budget_finance", "curriculum_instruction", "facilities",
    "policy", "student_affairs", "community_relations", "consent_agenda",
    "technology", "safety_security", "dei_equity", "special_education",
    "procedural", "admin_operations", "other"
}

VALID_VOTE_TYPES = {"roll_call", "voice", "unanimous_consent", "show_of_hands"}
VALID_RESULTS = {"passed", "failed", "tabled", "withdrawn", "amended_and_passed"}
VALID_MEMBER_VOTES = {"yes", "no", "abstain", "absent", "recused"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def validate_vote(vote_data: dict) -> dict:
    """Validate and clean vote data."""
    if not vote_data:
        return vote_data

    # Normalize vote_type
    vt = vote_data.get("vote_type", "voice")
    if vt not in VALID_VOTE_TYPES:
        vote_data["vote_type"] = "voice"

    # Normalize result
    result = vote_data.get("result", "passed")
    if result not in VALID_RESULTS:
        result_lower = result.lower().strip()
        if "amend" in result_lower:
            vote_data["result"] = "amended_and_passed"
        elif "table" in result_lower:
            vote_data["result"] = "tabled"
        elif "withdraw" in result_lower:
            vote_data["result"] = "withdrawn"
        elif "fail" in result_lower or "defeat" in result_lower or "denied" in result_lower:
            vote_data["result"] = "failed"
        elif "pass" in result_lower or "approv" in result_lower or "carri" in result_lower:
            vote_data["result"] = "passed"
        else:
            vote_data["result"] = "passed"

    # Normalize category
    cat = vote_data.get("item_category", "other")
    if cat not in VALID_CATEGORIES:
        vote_data["item_category"] = "other"

    # Normalize confidence
    conf = vote_data.get("confidence", "medium")
    if conf not in VALID_CONFIDENCE:
        vote_data["confidence"] = "medium"

    # Validate individual votes
    ind_votes = vote_data.get("individual_votes", [])
    cleaned_votes = []
    for iv in ind_votes:
        if isinstance(iv, dict) and "member_name" in iv:
            mv = iv.get("member_vote", "yes").lower().strip()
            if mv not in VALID_MEMBER_VOTES:
                if mv in ("aye", "yea", "for"):
                    mv = "yes"
                elif mv in ("nay", "against", "opposed"):
                    mv = "no"
                else:
                    mv = "yes"
            cleaned_votes.append({
                "member_name": iv["member_name"].strip(),
                "member_vote": mv,
            })
    vote_data["individual_votes"] = cleaned_votes

    # Ensure numeric fields are integers or None
    for field in ["votes_for", "votes_against", "votes_abstain"]:
        val = vote_data.get(field)
        if val is not None:
            try:
                vote_data[field] = int(val)
            except (ValueError, TypeError):
                vote_data[field] = None

    # Ensure is_unanimous is boolean
    vote_data["is_unanimous"] = bool(vote_data.get("is_unanimous", False))

    return vote_data


def validate_extraction(raw_data: dict) -> MeetingExtractionData:
    """Validate and convert raw extraction dict to MeetingExtractionData."""
    agenda_items = []
    for item in raw_data.get("agenda_items", []):
        vote = None
        if item.get("has_vote") and item.get("vote"):
            vote_raw = validate_vote(item["vote"])
            # Separate item_category
            cat = vote_raw.pop("item_category", "other")
            try:
                vote = VoteData(**vote_raw)
            except Exception as e:
                logger.warning(f"Invalid vote data: {e}")
                vote = None
        else:
            cat = item.get("item_category", "other")

        if cat not in VALID_CATEGORIES:
            cat = "other"

        agenda_items.append(AgendaItemData(
            item_number=item.get("item_number"),
            item_title=item.get("item_title", "Untitled"),
            item_description=item.get("item_description") or item.get("brief_description"),
            item_category=cat,
            has_vote=bool(item.get("has_vote", False)),
            vote=vote,
        ))

    return MeetingExtractionData(
        meeting_type=raw_data.get("meeting_type", "regular"),
        members_present=raw_data.get("members_present", []),
        members_absent=raw_data.get("members_absent", []),
        agenda_items=agenda_items,
        extraction_confidence=raw_data.get("extraction_confidence", "medium"),
    )

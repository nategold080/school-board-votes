"""Pydantic models for extraction output validation."""

from pydantic import BaseModel, Field
from typing import Optional


class IndividualVoteData(BaseModel):
    member_name: str
    member_vote: str = Field(description="One of: yes, no, abstain, absent, recused")


class VoteData(BaseModel):
    motion_text: Optional[str] = None
    motion_maker: Optional[str] = None
    motion_seconder: Optional[str] = None
    vote_type: str = Field(default="voice", description="roll_call, voice, unanimous_consent, show_of_hands")
    result: str = Field(description="passed, failed, tabled, withdrawn, amended_and_passed")
    votes_for: Optional[int] = None
    votes_against: Optional[int] = None
    votes_abstain: Optional[int] = None
    is_unanimous: bool = False
    individual_votes: list[IndividualVoteData] = Field(default_factory=list)
    confidence: str = Field(default="medium", description="high, medium, low")


class AgendaItemData(BaseModel):
    item_number: Optional[str] = None
    item_title: str
    item_description: Optional[str] = None
    item_category: str = Field(default="other")
    has_vote: bool = False
    vote: Optional[VoteData] = None


class MeetingExtractionData(BaseModel):
    meeting_type: str = Field(default="regular")
    members_present: list[str] = Field(default_factory=list)
    members_absent: list[str] = Field(default_factory=list)
    agenda_items: list[AgendaItemData] = Field(default_factory=list)
    extraction_confidence: str = Field(default="medium", description="high, medium, low")


class Stage1Output(BaseModel):
    """Output from Stage 1 classification."""
    meeting_type: str = Field(default="regular")
    members_present: list[str] = Field(default_factory=list)
    members_absent: list[str] = Field(default_factory=list)
    agenda_items: list[dict] = Field(default_factory=list,
        description="List of {item_number, item_title, has_vote, brief_description}")
    confidence: str = Field(default="medium")

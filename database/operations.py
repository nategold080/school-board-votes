"""CRUD operations for the School Board Votes database."""

import json
from datetime import date, datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, Integer
from .models import District, Meeting, AgendaItem, Vote, IndividualVote, BoardMember


class DatabaseOperations:
    """Database operations wrapper."""

    def __init__(self, session: Session):
        self.session = session

    # --- District Operations ---

    def upsert_district(self, district_id: str, district_name: str, state: str,
                        enrollment: int = None, county: str = None,
                        minutes_url: str = None, platform: str = None) -> District:
        district = self.session.get(District, district_id)
        if district:
            district.district_name = district_name
            district.state = state
            if enrollment is not None:
                district.enrollment = enrollment
            if county is not None:
                district.county = county
            if minutes_url is not None:
                district.minutes_url = minutes_url
            if platform is not None:
                district.platform = platform
        else:
            district = District(
                district_id=district_id, district_name=district_name,
                state=state, enrollment=enrollment, county=county,
                minutes_url=minutes_url, platform=platform
            )
            self.session.add(district)
        self.session.flush()
        return district

    def get_districts_by_state(self, state: str) -> list[District]:
        return self.session.query(District).filter(District.state == state).all()

    def get_all_districts(self) -> list[District]:
        return self.session.query(District).order_by(District.state, District.district_name).all()

    # --- Meeting Operations ---

    def add_meeting(self, district_id: str, meeting_date: date, meeting_type: str = "regular",
                    source_url: str = None, raw_text: str = None,
                    members_present: list = None, members_absent: list = None,
                    extraction_confidence: str = None) -> Meeting:
        meeting = Meeting(
            district_id=district_id,
            meeting_date=meeting_date,
            meeting_type=meeting_type,
            source_url=source_url,
            raw_text=raw_text,
            members_present=json.dumps(members_present) if members_present else None,
            members_absent=json.dumps(members_absent) if members_absent else None,
            extraction_confidence=extraction_confidence,
        )
        self.session.add(meeting)
        self.session.flush()
        return meeting

    def get_meetings_for_district(self, district_id: str) -> list[Meeting]:
        return (self.session.query(Meeting)
                .filter(Meeting.district_id == district_id)
                .order_by(Meeting.meeting_date.desc())
                .all())

    # --- Agenda Item Operations ---

    def add_agenda_item(self, meeting_id: int, item_title: str,
                        item_number: str = None, item_description: str = None,
                        item_category: str = "other", has_vote: bool = False) -> AgendaItem:
        item = AgendaItem(
            meeting_id=meeting_id, item_number=item_number,
            item_title=item_title, item_description=item_description,
            item_category=item_category, has_vote=has_vote
        )
        self.session.add(item)
        self.session.flush()
        return item

    # --- Vote Operations ---

    def add_vote(self, item_id: int, motion_text: str = None,
                 motion_maker: str = None, motion_seconder: str = None,
                 vote_type: str = None, result: str = None,
                 votes_for: int = None, votes_against: int = None,
                 votes_abstain: int = None, is_unanimous: bool = False,
                 confidence: str = None) -> Vote:
        vote = Vote(
            item_id=item_id, motion_text=motion_text,
            motion_maker=motion_maker, motion_seconder=motion_seconder,
            vote_type=vote_type, result=result,
            votes_for=votes_for, votes_against=votes_against,
            votes_abstain=votes_abstain, is_unanimous=is_unanimous,
            confidence=confidence
        )
        self.session.add(vote)
        self.session.flush()
        return vote

    def add_individual_vote(self, vote_id: int, member_name: str,
                            member_vote: str) -> IndividualVote:
        iv = IndividualVote(
            vote_id=vote_id, member_name=member_name, member_vote=member_vote
        )
        self.session.add(iv)
        self.session.flush()
        return iv

    # --- Board Member Operations ---

    def upsert_board_member(self, district_id: str, member_name: str,
                            role: str = None, seen_date: date = None) -> BoardMember:
        member = (self.session.query(BoardMember)
                  .filter(and_(BoardMember.district_id == district_id,
                               BoardMember.member_name == member_name))
                  .first())
        if member:
            if role:
                member.role = role
            if seen_date:
                if member.first_seen_date is None or seen_date < member.first_seen_date:
                    member.first_seen_date = seen_date
                if member.last_seen_date is None or seen_date > member.last_seen_date:
                    member.last_seen_date = seen_date
        else:
            member = BoardMember(
                district_id=district_id, member_name=member_name,
                role=role, first_seen_date=seen_date, last_seen_date=seen_date
            )
            self.session.add(member)
        self.session.flush()
        return member

    # --- Query Operations ---

    def search_votes(self, keyword: str, state: str = None,
                     category: str = None, limit: int = 100) -> list:
        """Search votes by keyword across all districts."""
        query = (self.session.query(Vote, AgendaItem, Meeting, District)
                 .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
                 .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
                 .join(District, Meeting.district_id == District.district_id))

        if keyword:
            kw = f"%{keyword}%"
            query = query.filter(
                (Vote.motion_text.ilike(kw)) |
                (AgendaItem.item_title.ilike(kw)) |
                (AgendaItem.item_description.ilike(kw))
            )
        if state:
            query = query.filter(District.state == state)
        if category:
            query = query.filter(AgendaItem.item_category == category)

        return query.order_by(Meeting.meeting_date.desc()).limit(limit).all()

    def get_contested_votes(self, state: str = None, category: str = None,
                            limit: int = 100) -> list:
        """Get non-unanimous votes."""
        query = (self.session.query(Vote, AgendaItem, Meeting, District)
                 .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
                 .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
                 .join(District, Meeting.district_id == District.district_id)
                 .filter(Vote.is_unanimous == False))

        if state:
            query = query.filter(District.state == state)
        if category:
            query = query.filter(AgendaItem.item_category == category)

        return query.order_by(Meeting.meeting_date.desc()).limit(limit).all()

    def get_member_voting_record(self, member_name: str) -> list:
        """Get all votes for a specific board member."""
        return (self.session.query(IndividualVote, Vote, AgendaItem, Meeting)
                .join(Vote, IndividualVote.vote_id == Vote.vote_id)
                .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
                .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
                .filter(IndividualVote.member_name == member_name)
                .order_by(Meeting.meeting_date.desc())
                .all())

    def get_vote_statistics(self) -> dict:
        """Get overall vote statistics."""
        total_votes = self.session.query(func.count(Vote.vote_id)).scalar()
        unanimous = self.session.query(func.count(Vote.vote_id)).filter(Vote.is_unanimous == True).scalar()
        contested = total_votes - unanimous

        total_districts = self.session.query(func.count(District.district_id)).scalar()
        total_meetings = self.session.query(func.count(Meeting.meeting_id)).scalar()
        total_individual = self.session.query(func.count(IndividualVote.individual_vote_id)).scalar()

        return {
            "total_votes": total_votes,
            "unanimous_votes": unanimous,
            "contested_votes": contested,
            "total_districts": total_districts,
            "total_meetings": total_meetings,
            "total_individual_votes": total_individual,
            "unanimity_rate": unanimous / total_votes if total_votes > 0 else 0,
        }

    def get_category_breakdown(self) -> list:
        """Get vote counts by category."""
        return (self.session.query(
                    AgendaItem.item_category,
                    func.count(Vote.vote_id).label("total_votes"),
                    func.sum(func.cast(Vote.is_unanimous, Integer)).label("unanimous_count")
                )
                .join(Vote, AgendaItem.item_id == Vote.item_id)
                .group_by(AgendaItem.item_category)
                .order_by(func.count(Vote.vote_id).desc())
                .all())

    def get_dissent_by_member(self, district_id: str = None) -> list:
        """Get dissent rates by board member."""
        query = (self.session.query(
                    IndividualVote.member_name,
                    func.count(IndividualVote.individual_vote_id).label("total_votes"),
                    func.sum(func.case(
                        (IndividualVote.member_vote == "no", 1), else_=0
                    )).label("no_votes"),
                    func.sum(func.case(
                        (IndividualVote.member_vote == "abstain", 1), else_=0
                    )).label("abstain_votes"),
                )
                .join(Vote, IndividualVote.vote_id == Vote.vote_id)
                .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
                .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id))

        if district_id:
            query = query.filter(Meeting.district_id == district_id)

        return (query.group_by(IndividualVote.member_name)
                .having(func.count(IndividualVote.individual_vote_id) >= 3)
                .order_by(func.sum(func.case(
                    (IndividualVote.member_vote == "no", 1), else_=0
                )).desc())
                .all())

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

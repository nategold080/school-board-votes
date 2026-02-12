"""Analytics and aggregation queries for vote data."""

from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, Integer, Float
from database.models import District, Meeting, AgendaItem, Vote, IndividualVote, BoardMember


class VoteAnalytics:
    """Pre-computed analytics and aggregations for the vote database."""

    def __init__(self, session: Session):
        self.session = session

    def votes_by_category(self) -> list[dict]:
        """Get vote breakdown by policy category."""
        results = (
            self.session.query(
                AgendaItem.item_category,
                func.count(Vote.vote_id).label("total_votes"),
                func.sum(case((Vote.is_unanimous == True, 1), else_=0)).label("unanimous"),
                func.sum(case((Vote.is_unanimous == False, 1), else_=0)).label("contested"),
            )
            .join(Vote, AgendaItem.item_id == Vote.item_id)
            .group_by(AgendaItem.item_category)
            .order_by(func.count(Vote.vote_id).desc())
            .all()
        )
        return [
            {
                "category": r[0] or "other",
                "total_votes": r[1],
                "unanimous": r[2],
                "contested": r[3],
                "contested_pct": (r[3] / r[1] * 100) if r[1] > 0 else 0,
            }
            for r in results
        ]

    def votes_by_state(self) -> list[dict]:
        """Get vote breakdown by state."""
        results = (
            self.session.query(
                District.state,
                func.count(Vote.vote_id).label("total_votes"),
                func.count(func.distinct(District.district_id)).label("districts"),
                func.sum(case((Vote.is_unanimous == False, 1), else_=0)).label("contested"),
            )
            .join(Meeting, District.district_id == Meeting.district_id)
            .join(AgendaItem, Meeting.meeting_id == AgendaItem.meeting_id)
            .join(Vote, AgendaItem.item_id == Vote.item_id)
            .group_by(District.state)
            .order_by(func.count(Vote.vote_id).desc())
            .all()
        )
        return [
            {
                "state": r[0],
                "total_votes": r[1],
                "districts": r[2],
                "contested": r[3],
                "contested_pct": (r[3] / r[1] * 100) if r[1] > 0 else 0,
            }
            for r in results
        ]

    def top_dissenters(self, limit: int = 20, min_votes: int = 3) -> list[dict]:
        """Get board members who dissent most often."""
        results = (
            self.session.query(
                IndividualVote.member_name,
                func.count(IndividualVote.individual_vote_id).label("total_votes"),
                func.sum(case((IndividualVote.member_vote == "no", 1), else_=0)).label("no_votes"),
                func.sum(case((IndividualVote.member_vote == "abstain", 1), else_=0)).label("abstain_votes"),
            )
            .group_by(IndividualVote.member_name)
            .having(func.count(IndividualVote.individual_vote_id) >= min_votes)
            .order_by(func.sum(case((IndividualVote.member_vote == "no", 1), else_=0)).desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "member_name": r[0],
                "total_votes": r[1],
                "no_votes": r[2],
                "abstain_votes": r[3],
                "dissent_rate": r[2] / r[1] if r[1] > 0 else 0,
            }
            for r in results
        ]

    def most_contested_categories(self, min_votes: int = 5) -> list[dict]:
        """Get categories with highest rate of contested votes."""
        results = (
            self.session.query(
                AgendaItem.item_category,
                func.count(Vote.vote_id).label("total_votes"),
                func.sum(case((Vote.is_unanimous == False, 1), else_=0)).label("contested_votes"),
            )
            .join(Vote, AgendaItem.item_id == Vote.item_id)
            .group_by(AgendaItem.item_category)
            .having(func.count(Vote.vote_id) >= min_votes)
            .order_by(
                (func.sum(case((Vote.is_unanimous == False, 1), else_=0)) * 100.0
                 / func.count(Vote.vote_id)).desc()
            )
            .all()
        )
        return [
            {
                "category": r[0] or "other",
                "total_votes": r[1],
                "contested_votes": r[2],
                "contested_pct": (r[2] / r[1] * 100) if r[1] > 0 else 0,
            }
            for r in results
        ]

    def district_dissent_rates(self) -> list[dict]:
        """Get dissent rate by district."""
        results = (
            self.session.query(
                District.district_id,
                District.district_name,
                District.state,
                func.count(Vote.vote_id).label("total_votes"),
                func.sum(case((Vote.is_unanimous == False, 1), else_=0)).label("contested"),
            )
            .join(Meeting, District.district_id == Meeting.district_id)
            .join(AgendaItem, Meeting.meeting_id == AgendaItem.meeting_id)
            .join(Vote, AgendaItem.item_id == Vote.item_id)
            .group_by(District.district_id, District.district_name, District.state)
            .order_by(
                (func.sum(case((Vote.is_unanimous == False, 1), else_=0)) * 100.0
                 / func.count(Vote.vote_id)).desc()
            )
            .all()
        )
        return [
            {
                "district_id": r[0],
                "district_name": r[1],
                "state": r[2],
                "total_votes": r[3],
                "contested": r[4],
                "contested_pct": (r[4] / r[3] * 100) if r[3] > 0 else 0,
            }
            for r in results
        ]

    def vote_trends_by_month(self) -> list[dict]:
        """Get monthly vote trends."""
        results = (
            self.session.query(
                func.strftime("%Y-%m", Meeting.meeting_date).label("month"),
                func.count(Vote.vote_id).label("total_votes"),
                func.sum(case((Vote.is_unanimous == False, 1), else_=0)).label("contested"),
            )
            .join(AgendaItem, Meeting.meeting_id == AgendaItem.meeting_id)
            .join(Vote, AgendaItem.item_id == Vote.item_id)
            .group_by(func.strftime("%Y-%m", Meeting.meeting_date))
            .order_by(func.strftime("%Y-%m", Meeting.meeting_date))
            .all()
        )
        return [
            {
                "month": r[0],
                "total_votes": r[1],
                "contested": r[2],
                "contested_pct": (r[2] / r[1] * 100) if r[1] > 0 else 0,
            }
            for r in results
        ]

    def member_profile(self, member_name: str) -> dict:
        """Get a comprehensive voting profile for a board member."""
        # Get basic stats
        votes = (
            self.session.query(IndividualVote)
            .filter(IndividualVote.member_name == member_name)
            .all()
        )

        if not votes:
            return {"member_name": member_name, "total_votes": 0}

        total = len(votes)
        yes_count = sum(1 for v in votes if v.member_vote == "yes")
        no_count = sum(1 for v in votes if v.member_vote == "no")
        abstain_count = sum(1 for v in votes if v.member_vote == "abstain")

        # Get category breakdown of dissent
        dissent_by_category = (
            self.session.query(
                AgendaItem.item_category,
                func.count(IndividualVote.individual_vote_id).label("total"),
                func.sum(case((IndividualVote.member_vote == "no", 1), else_=0)).label("no_votes"),
            )
            .join(Vote, IndividualVote.vote_id == Vote.vote_id)
            .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
            .filter(IndividualVote.member_name == member_name)
            .group_by(AgendaItem.item_category)
            .all()
        )

        return {
            "member_name": member_name,
            "total_votes": total,
            "yes_votes": yes_count,
            "no_votes": no_count,
            "abstain_votes": abstain_count,
            "dissent_rate": no_count / total if total > 0 else 0,
            "categories": [
                {
                    "category": r[0],
                    "total": r[1],
                    "no_votes": r[2],
                }
                for r in dissent_by_category
            ],
        }

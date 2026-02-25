"""SQLAlchemy models for the School Board Votes database."""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date, DateTime, Float,
    ForeignKey, create_engine, Index
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime, timezone

Base = declarative_base()


class District(Base):
    __tablename__ = "districts"

    district_id = Column(String, primary_key=True)  # NCES ID
    district_name = Column(String, nullable=False)
    state = Column(String(2), nullable=False)
    enrollment = Column(Integer)
    county = Column(String)
    minutes_url = Column(String)
    platform = Column(String)  # boarddocs, pdf, html, etc.
    status = Column(String, default="active")  # active/inactive

    meetings = relationship("Meeting", back_populates="district", cascade="all, delete-orphan")
    board_members = relationship("BoardMember", back_populates="district", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_district_state", "state"),
    )


class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.district_id"), nullable=False)
    meeting_date = Column(Date, nullable=False)
    meeting_type = Column(String, default="regular")  # regular/special/emergency/work_session
    source_url = Column(String)
    raw_text = Column(Text)
    members_present = Column(Text)  # JSON list
    members_absent = Column(Text)   # JSON list
    extraction_confidence = Column(String)  # high/medium/low
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    district = relationship("District", back_populates="meetings")
    agenda_items = relationship("AgendaItem", back_populates="meeting", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_meeting_district", "district_id"),
        Index("idx_meeting_date", "meeting_date"),
    )


class AgendaItem(Base):
    __tablename__ = "agenda_items"

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.meeting_id"), nullable=False)
    item_number = Column(String)  # e.g., "7.A" or "Item 12"
    item_title = Column(String)
    item_description = Column(Text)
    item_category = Column(String)  # personnel, budget_finance, etc.
    has_vote = Column(Boolean, default=False)

    meeting = relationship("Meeting", back_populates="agenda_items")
    vote = relationship("Vote", back_populates="agenda_item", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_item_meeting", "meeting_id"),
        Index("idx_item_category", "item_category"),
    )


class Vote(Base):
    __tablename__ = "votes"

    vote_id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, ForeignKey("agenda_items.item_id"), nullable=False)
    motion_text = Column(Text)
    motion_maker = Column(String)
    motion_seconder = Column(String)
    vote_type = Column(String)  # roll_call/voice/unanimous_consent/show_of_hands
    result = Column(String)  # passed/failed/tabled/withdrawn/amended_and_passed
    votes_for = Column(Integer)
    votes_against = Column(Integer)
    votes_abstain = Column(Integer)
    is_unanimous = Column(Boolean, default=False)
    confidence = Column(String)  # high/medium/low

    agenda_item = relationship("AgendaItem", back_populates="vote")
    individual_votes = relationship("IndividualVote", back_populates="vote", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_vote_item", "item_id"),
        Index("idx_vote_result", "result"),
    )


class IndividualVote(Base):
    __tablename__ = "individual_votes"

    individual_vote_id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(Integer, ForeignKey("votes.vote_id"), nullable=False)
    member_name = Column(String, nullable=False)
    member_vote = Column(String, nullable=False)  # yes/no/abstain/absent/recused

    vote = relationship("Vote", back_populates="individual_votes")

    __table_args__ = (
        Index("idx_indvote_vote", "vote_id"),
        Index("idx_indvote_member", "member_name"),
    )


class BoardMember(Base):
    __tablename__ = "board_members"

    member_id = Column(Integer, primary_key=True, autoincrement=True)
    district_id = Column(String, ForeignKey("districts.district_id"), nullable=False)
    member_name = Column(String, nullable=False)
    role = Column(String)  # president/chair/vice_president/secretary/trustee/member
    first_seen_date = Column(Date)
    last_seen_date = Column(Date)

    district = relationship("District", back_populates="board_members")

    __table_args__ = (
        Index("idx_member_district", "district_id"),
        Index("idx_member_name", "member_name"),
    )


def get_engine(db_path="data/database.sqlite"):
    """Create and return a database engine with WAL mode for better write performance."""
    from sqlalchemy import event as sa_event

    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    @sa_event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def get_session(db_path="data/database.sqlite"):
    """Create and return a database session."""
    engine = get_engine(db_path)
    Session = sessionmaker(bind=engine)
    return Session()


def init_database(db_path="data/database.sqlite"):
    """Initialize the database, creating all tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine

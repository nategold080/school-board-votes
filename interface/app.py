"""Streamlit web interface for School Board Vote Tracker."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import json
from datetime import date
from sqlalchemy import func

from config.settings import DATABASE_PATH
from database.models import init_database, get_session, District, Meeting, AgendaItem, Vote, IndividualVote, BoardMember
from database.operations import DatabaseOperations
from analytics.vote_analytics import VoteAnalytics
from analytics.visualizations import (
    category_vote_chart, state_comparison_chart, dissent_rate_chart,
    monthly_trend_chart, member_vote_pie, district_contested_chart,
)

# Page config
st.set_page_config(
    page_title="School Board Vote Tracker",
    page_icon="🏫",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1a1a2e;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-top: 0;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        color: white;
    }
    .stMetric > div {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #e9ecef;
    }
    .vote-passed { color: #2ecc71; font-weight: bold; }
    .vote-failed { color: #e74c3c; font-weight: bold; }
    .vote-contested { background-color: #fff3cd; padding: 0.2rem 0.5rem; border-radius: 0.25rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    """Get database session (cached)."""
    init_database(str(DATABASE_PATH))
    session = get_session(str(DATABASE_PATH))
    return session


def main():
    session = get_db()
    db_ops = DatabaseOperations(session)
    analytics = VoteAnalytics(session)

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to",
        ["Dashboard", "District Browser", "Vote Search",
         "Member Profiles", "Contested Votes", "Trends"],
        index=0,
    )

    if page == "Dashboard":
        render_dashboard(db_ops, analytics)
    elif page == "District Browser":
        render_district_browser(db_ops, session)
    elif page == "Vote Search":
        render_vote_search(db_ops)
    elif page == "Member Profiles":
        render_member_profiles(analytics, session)
    elif page == "Contested Votes":
        render_contested_votes(db_ops)
    elif page == "Trends":
        render_trends(analytics)


def render_dashboard(db_ops, analytics):
    """Render the main dashboard."""
    st.markdown('<p class="main-header">School Board Vote Tracker</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Structured data on how school board members vote on policy decisions — the first database of its kind.</p>', unsafe_allow_html=True)

    stats = db_ops.get_vote_statistics()

    # Key metrics
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Districts", f"{stats['total_districts']}")
    with col2:
        st.metric("Meetings", f"{stats['total_meetings']}")
    with col3:
        st.metric("Votes Tracked", f"{stats['total_votes']}")
    with col4:
        st.metric("Unanimity Rate", f"{stats['unanimity_rate']:.0%}")
    with col5:
        st.metric("Individual Records", f"{stats['total_individual_votes']}")

    st.divider()

    # Charts row
    col1, col2 = st.columns(2)

    with col1:
        categories = analytics.votes_by_category()
        if categories:
            st.plotly_chart(category_vote_chart(categories), use_container_width=True)

    with col2:
        states = analytics.votes_by_state()
        if states:
            st.plotly_chart(state_comparison_chart(states), use_container_width=True)

    # Second row
    col1, col2 = st.columns(2)

    with col1:
        contested_cats = analytics.most_contested_categories()
        if contested_cats:
            st.plotly_chart(dissent_rate_chart(contested_cats), use_container_width=True)

    with col2:
        trends = analytics.vote_trends_by_month()
        if trends:
            st.plotly_chart(monthly_trend_chart(trends), use_container_width=True)

    # Top dissenters
    st.subheader("Top Dissenting Board Members")
    dissenters = analytics.top_dissenters(limit=10)
    if dissenters:
        df = pd.DataFrame(dissenters)
        df["dissent_rate"] = df["dissent_rate"].apply(lambda x: f"{x:.1%}")
        st.dataframe(df, use_container_width=True, hide_index=True,
                     column_config={
                         "member_name": "Board Member",
                         "total_votes": "Total Votes",
                         "no_votes": "No Votes",
                         "abstain_votes": "Abstentions",
                         "dissent_rate": "Dissent Rate",
                     })


def render_district_browser(db_ops, session):
    """Render district browser page."""
    st.header("District Browser")

    districts = db_ops.get_all_districts()
    if not districts:
        st.warning("No districts in database yet.")
        return

    # State filter
    states = sorted(set(d.state for d in districts))
    selected_state = st.selectbox("Filter by State", ["All"] + states)

    if selected_state != "All":
        districts = [d for d in districts if d.state == selected_state]

    # District selector
    district_names = {d.district_name: d for d in districts}
    selected_name = st.selectbox("Select District", sorted(district_names.keys()))

    if selected_name:
        district = district_names[selected_name]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("State", district.state)
        with col2:
            st.metric("Enrollment", f"{district.enrollment:,}" if district.enrollment else "N/A")
        with col3:
            st.metric("Platform", district.platform or "N/A")

        # Show meetings
        meetings = db_ops.get_meetings_for_district(district.district_id)
        st.subheader(f"Meetings ({len(meetings)})")

        for meeting in meetings:
            with st.expander(f"{meeting.meeting_date} — {meeting.meeting_type.replace('_', ' ').title()}"):
                if meeting.members_present:
                    try:
                        present = json.loads(meeting.members_present)
                        st.write(f"**Present:** {', '.join(present)}")
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Show agenda items and votes
                items = (session.query(AgendaItem)
                        .filter(AgendaItem.meeting_id == meeting.meeting_id)
                        .all())

                for item in items:
                    vote_indicator = " ✅" if item.has_vote else ""
                    st.markdown(f"**{item.item_number or '•'} {item.item_title}** "
                              f"*({item.item_category})*{vote_indicator}")

                    if item.vote:
                        vote = item.vote
                        result_color = "green" if vote.result == "passed" else "red"
                        st.markdown(f"  - Motion: {vote.motion_text or 'N/A'}")
                        st.markdown(f"  - Result: :{result_color}[**{vote.result.upper()}**] "
                                  f"({'Unanimous' if vote.is_unanimous else f'{vote.votes_for}-{vote.votes_against}'})")

                        if vote.individual_votes:
                            vote_strs = []
                            for iv in vote.individual_votes:
                                emoji = "👍" if iv.member_vote == "yes" else "👎" if iv.member_vote == "no" else "⚪"
                                vote_strs.append(f"{emoji} {iv.member_name}")
                            st.markdown("  - " + " | ".join(vote_strs))


def render_vote_search(db_ops):
    """Render vote search page."""
    st.header("Vote Search")
    st.write("Search across all districts for specific policy topics.")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        keyword = st.text_input("Search keyword", placeholder="e.g., superintendent, budget, textbook, HVAC")
    with col2:
        state_filter = st.text_input("State (optional)", placeholder="e.g., NY")
    with col3:
        category_filter = st.selectbox("Category", ["All", "personnel", "budget_finance",
            "curriculum_instruction", "facilities", "policy", "student_affairs",
            "consent_agenda", "technology", "safety_security", "dei_equity",
            "special_education", "other"])

    if keyword:
        results = db_ops.search_votes(
            keyword,
            state=state_filter.upper() if state_filter else None,
            category=category_filter if category_filter != "All" else None,
        )

        st.write(f"Found **{len(results)}** votes matching '{keyword}'")

        for vote, item, meeting, district in results:
            with st.expander(
                f"{district.district_name} ({district.state}) — {meeting.meeting_date} — "
                f"{item.item_title}"
            ):
                st.write(f"**Category:** {item.item_category}")
                st.write(f"**Motion:** {vote.motion_text or 'N/A'}")

                result_color = "green" if vote.result == "passed" else "red"
                unanimous = "Unanimous" if vote.is_unanimous else f"{vote.votes_for}-{vote.votes_against}"
                st.markdown(f"**Result:** :{result_color}[{vote.result.upper()}] ({unanimous})")

                if vote.individual_votes:
                    st.write("**Individual Votes:**")
                    for iv in vote.individual_votes:
                        emoji = "👍" if iv.member_vote == "yes" else "👎" if iv.member_vote == "no" else "⚪"
                        st.write(f"  {emoji} {iv.member_name}: {iv.member_vote}")


def render_member_profiles(analytics, session):
    """Render member voting profiles."""
    st.header("Board Member Voting Profiles")

    # Get all members with votes
    members = (session.query(IndividualVote.member_name)
               .group_by(IndividualVote.member_name)
               .having(func.count(IndividualVote.individual_vote_id) >= 3)
               .order_by(IndividualVote.member_name)
               .all())

    if not members:
        st.warning("No member voting records available yet.")
        return

    member_names = [m[0] for m in members]
    selected = st.selectbox("Select Board Member", member_names)

    if selected:
        profile = analytics.member_profile(selected)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Votes", profile["total_votes"])
        with col2:
            st.metric("Yes Votes", profile["yes_votes"])
        with col3:
            st.metric("No Votes", profile["no_votes"])
        with col4:
            st.metric("Dissent Rate", f"{profile['dissent_rate']:.1%}")

        col1, col2 = st.columns(2)
        with col1:
            fig = member_vote_pie(profile)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            if profile.get("categories"):
                st.subheader("Dissent by Category")
                df = pd.DataFrame(profile["categories"])
                df["dissent_rate"] = df.apply(
                    lambda r: f"{r['no_votes']/r['total']*100:.0f}%" if r["total"] > 0 else "0%",
                    axis=1
                )
                st.dataframe(df, use_container_width=True, hide_index=True)


def render_contested_votes(db_ops):
    """Render contested (non-unanimous) votes view."""
    st.header("Contested Votes")
    st.write("Non-unanimous votes reveal the most interesting political dynamics.")

    col1, col2 = st.columns(2)
    with col1:
        state_filter = st.text_input("Filter by State", placeholder="e.g., TX")
    with col2:
        category_filter = st.selectbox("Filter by Category", ["All", "personnel",
            "budget_finance", "curriculum_instruction", "facilities", "policy",
            "student_affairs", "technology", "safety_security", "dei_equity",
            "special_education", "other"])

    results = db_ops.get_contested_votes(
        state=state_filter.upper() if state_filter else None,
        category=category_filter if category_filter != "All" else None,
    )

    st.write(f"**{len(results)}** contested votes found")

    for vote, item, meeting, district in results:
        margin = ""
        if vote.votes_for is not None and vote.votes_against is not None:
            margin = f" ({vote.votes_for}-{vote.votes_against})"

        with st.expander(
            f"{'🔴' if vote.result == 'failed' else '🟡'} "
            f"{district.district_name} ({district.state}) — {meeting.meeting_date} — "
            f"{item.item_title}{margin}"
        ):
            st.write(f"**Category:** {item.item_category}")
            st.write(f"**Motion:** {vote.motion_text or 'N/A'}")
            st.write(f"**Result:** {vote.result.upper()}{margin}")
            st.write(f"**Maker/Seconder:** {vote.motion_maker or '?'} / {vote.motion_seconder or '?'}")

            if vote.individual_votes:
                yes_votes = [iv for iv in vote.individual_votes if iv.member_vote == "yes"]
                no_votes = [iv for iv in vote.individual_votes if iv.member_vote == "no"]
                abstains = [iv for iv in vote.individual_votes if iv.member_vote == "abstain"]

                cols = st.columns(3)
                with cols[0]:
                    st.write("**Yes:**")
                    for iv in yes_votes:
                        st.write(f"  👍 {iv.member_name}")
                with cols[1]:
                    st.write("**No:**")
                    for iv in no_votes:
                        st.write(f"  👎 {iv.member_name}")
                with cols[2]:
                    st.write("**Abstain:**")
                    for iv in abstains:
                        st.write(f"  ⚪ {iv.member_name}")


def render_trends(analytics):
    """Render trend dashboard."""
    st.header("Trend Dashboard")

    # Monthly trends
    trends = analytics.vote_trends_by_month()
    if trends:
        st.plotly_chart(monthly_trend_chart(trends), use_container_width=True)

    col1, col2 = st.columns(2)

    with col1:
        # Category breakdown
        categories = analytics.votes_by_category()
        if categories:
            st.plotly_chart(category_vote_chart(categories), use_container_width=True)

    with col2:
        # Most contested
        contested = analytics.most_contested_categories()
        if contested:
            st.plotly_chart(dissent_rate_chart(contested), use_container_width=True)

    # District comparison
    st.subheader("District Comparison")
    district_rates = analytics.district_dissent_rates()
    if district_rates:
        st.plotly_chart(district_contested_chart(district_rates), use_container_width=True)


if __name__ == "__main__":
    main()

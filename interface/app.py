"""Streamlit web interface for School Board Vote Tracker."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import json
from datetime import date
from sqlalchemy import func, case

from config.settings import DATABASE_PATH
from database.models import init_database, get_session, District, Meeting, AgendaItem, Vote, IndividualVote, BoardMember
from database.operations import DatabaseOperations
from analytics.vote_analytics import VoteAnalytics
from analytics.visualizations import (
    category_vote_chart, state_comparison_chart, dissent_rate_chart,
    monthly_trend_chart, member_vote_pie, district_contested_chart,
)

# Human-readable category labels
CATEGORY_LABELS = {
    "personnel": "Personnel",
    "budget_finance": "Budget & Finance",
    "curriculum_instruction": "Curriculum & Instruction",
    "facilities": "Facilities",
    "policy": "Policy",
    "student_affairs": "Student Affairs",
    "community_relations": "Community Relations",
    "consent_agenda": "Consent Agenda",
    "technology": "Technology",
    "safety_security": "Safety & Security",
    "dei_equity": "DEI & Equity",
    "special_education": "Special Education",
    "procedural": "Procedural",
    "admin_operations": "Admin & Operations",
    "other": "Other",
}

ALL_CATEGORIES = list(CATEGORY_LABELS.keys())


def format_category(cat: str) -> str:
    """Convert internal category key to display label."""
    return CATEGORY_LABELS.get(cat, cat.replace("_", " ").title() if cat else "Other")


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
        color: #555;
        margin-top: 0;
        margin-bottom: 2rem;
        line-height: 1.6;
    }
    .stMetric > div {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #e9ecef;
    }
    .highlight-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        color: white;
        text-align: center;
        margin-bottom: 1rem;
    }
    .highlight-box h2 { color: white; margin: 0; font-size: 2rem; }
    .highlight-box p { color: rgba(255,255,255,0.85); margin: 0.25rem 0 0 0; }
    .coverage-badge {
        display: inline-block;
        background: #e8f4f8;
        border: 1px solid #bee5eb;
        border-radius: 0.5rem;
        padding: 0.4rem 0.8rem;
        margin: 0.2rem;
        font-size: 0.9rem;
    }
    div[data-testid="stExpander"] details summary p {
        font-size: 0.95rem;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_db():
    """Get database session (cached)."""
    init_database(str(DATABASE_PATH))
    session = get_session(str(DATABASE_PATH))
    return session


def category_selectbox(label="Category", key=None, include_all=True):
    """Reusable category filter dropdown with human-readable labels."""
    options = (["All"] if include_all else []) + ALL_CATEGORIES
    display = (["All"] if include_all else []) + [CATEGORY_LABELS[c] for c in ALL_CATEGORIES]
    idx = st.selectbox(label, range(len(options)), format_func=lambda i: display[i], key=key)
    val = options[idx]
    return val if val != "All" else None


def main():
    session = get_db()
    db_ops = DatabaseOperations(session)
    analytics = VoteAnalytics(session)

    # Sidebar navigation
    st.sidebar.title("School Board Vote Tracker")
    st.sidebar.caption("Structured data on school board governance decisions across the United States.")
    st.sidebar.divider()
    page = st.sidebar.radio(
        "Navigate",
        ["Contested Votes", "Dashboard", "District Browser",
         "Vote Search", "Member Profiles", "Trends"],
        index=0,
    )

    if page == "Dashboard":
        render_dashboard(db_ops, analytics, session)
    elif page == "Contested Votes":
        render_contested_votes(db_ops, session)
    elif page == "District Browser":
        render_district_browser(db_ops, session)
    elif page == "Vote Search":
        render_vote_search(db_ops)
    elif page == "Member Profiles":
        render_member_profiles(analytics, session)
    elif page == "Trends":
        render_trends(analytics)


def render_dashboard(db_ops, analytics, session):
    """Render the main dashboard with impact stats."""
    st.markdown('<p class="main-header">School Board Vote Tracker</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-header">'
        'The first structured database of school board voting records. '
        'Tracking how elected board members vote on personnel, budgets, curriculum, '
        'and policy decisions across hundreds of districts nationwide.'
        '</p>',
        unsafe_allow_html=True,
    )

    stats = db_ops.get_vote_statistics()
    states = analytics.votes_by_state()
    state_count = len(set(s["state"] for s in states)) if states else 0

    # Summary banner
    st.markdown(
        f'<div class="highlight-box">'
        f'<h2>{stats["total_districts"]:,} districts | {state_count} states | '
        f'{stats["total_votes"]:,} votes tracked | {stats["contested_votes"]:,} contested votes</h2>'
        f'<p>Structured voting data extracted from public BoardDocs minutes using a zero-cost rule engine</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Hero metrics row
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Districts", f"{stats['total_districts']:,}")
    with col2:
        st.metric("Meetings Analyzed", f"{stats['total_meetings']:,}")
    with col3:
        st.metric("Votes Tracked", f"{stats['total_votes']:,}")
    with col4:
        contested = stats["contested_votes"]
        st.metric("Contested Votes", f"{contested:,}")
    with col5:
        st.metric("Individual Vote Records", f"{stats['total_individual_votes']:,}")

    st.divider()

    # Data coverage summary (states already fetched above for banner)
    if states:
        state_list = sorted(set(s["state"] for s in states))
        st.subheader(f"Data Coverage: {len(state_list)} States")
        badges = " ".join(
            f'<span class="coverage-badge">{s["state"]} ({s["districts"]} districts, {s["total_votes"]} votes)</span>'
            for s in sorted(states, key=lambda x: x["state"])
        )
        st.markdown(badges, unsafe_allow_html=True)
        st.write("")

    # Charts row 1
    col1, col2 = st.columns(2)
    with col1:
        categories = analytics.votes_by_category()
        if categories:
            for c in categories:
                c["category"] = format_category(c["category"])
            st.plotly_chart(category_vote_chart(categories), use_container_width=True)
    with col2:
        if states:
            st.plotly_chart(state_comparison_chart(states), use_container_width=True)

    # Charts row 2
    col1, col2 = st.columns(2)
    with col1:
        contested_cats = analytics.most_contested_categories()
        if contested_cats:
            for c in contested_cats:
                c["category"] = format_category(c["category"])
            st.plotly_chart(dissent_rate_chart(contested_cats), use_container_width=True)
    with col2:
        trends = analytics.vote_trends_by_month()
        if trends:
            st.plotly_chart(monthly_trend_chart(trends), use_container_width=True)

    # Top dissenters table
    st.subheader("Most Frequent Dissenters")
    st.caption("Board members who most often vote 'No' on motions (minimum 3 recorded votes).")
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
    else:
        st.info("Individual vote records are needed to compute dissent rates.")

    # Data Quality section
    st.divider()
    st.subheader("Data Quality")
    confidence_counts = (
        session.query(Vote.confidence, func.count(Vote.vote_id))
        .group_by(Vote.confidence)
        .all()
    )
    if confidence_counts:
        conf_data = {r[0] or "unknown": r[1] for r in confidence_counts}
        conf_df = pd.DataFrame([
            {"Confidence": level.title(), "Votes": conf_data.get(level, 0)}
            for level in ["high", "medium", "low"]
            if conf_data.get(level, 0) > 0
        ])
        col1, col2 = st.columns([1, 2])
        with col1:
            for _, row in conf_df.iterrows():
                total = sum(conf_data.values())
                pct = row["Votes"] / total * 100 if total else 0
                st.metric(f"{row['Confidence']} Confidence", f"{row['Votes']:,} ({pct:.1f}%)")
        with col2:
            import plotly.graph_objects as go
            colors = {"High": "#2ecc71", "Medium": "#f39c12", "Low": "#e74c3c"}
            fig = go.Figure(go.Bar(
                x=conf_df["Confidence"],
                y=conf_df["Votes"],
                marker_color=[colors.get(c, "#999") for c in conf_df["Confidence"]],
                text=conf_df["Votes"],
                textposition="outside",
            ))
            fig.update_layout(
                title="Vote Confidence Distribution",
                xaxis_title="Confidence Level",
                yaxis_title="Number of Votes",
                height=350,
                template="plotly_white",
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "**High** confidence votes have explicit roll-call language or structured BoardDocs vote blocks. "
            "**Medium** confidence votes match multiple vote-indicating patterns. "
            "**Low** confidence votes are inferred from agenda item type with a single pattern match."
        )


def render_contested_votes(db_ops, session):
    """Render contested (non-unanimous) votes - the highlight page."""
    st.header("Contested Votes")
    st.markdown(
        "Non-unanimous votes are where governance gets interesting. "
        "These are the decisions where at least one board member disagreed."
    )

    # Summary stats at top
    total_contested = session.query(func.count(Vote.vote_id)).filter(Vote.is_unanimous == False).scalar() or 0
    total_with_iv = (
        session.query(func.count(Vote.vote_id.distinct()))
        .join(IndividualVote, Vote.vote_id == IndividualVote.vote_id)
        .filter(Vote.is_unanimous == False)
        .scalar() or 0
    )
    failed_count = session.query(func.count(Vote.vote_id)).filter(Vote.result == "failed").scalar() or 0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Contested Votes", f"{total_contested:,}")
    with col2:
        st.metric("With Named Roll Calls", f"{total_with_iv:,}")
    with col3:
        st.metric("Motions That Failed", f"{failed_count:,}")

    st.divider()

    # Filters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        state_filter = st.text_input("Filter by State", placeholder="e.g., TX, FL, NY", key="cv_state")
    with col2:
        cat_val = category_selectbox("Filter by Category", key="cv_cat")
    with col3:
        confidence_filter = st.selectbox(
            "Confidence Level",
            ["All", "High Only", "High + Medium"],
            index=0,
            key="cv_conf",
        )
    with col4:
        sort_by = st.selectbox("Sort by", ["Most Recent", "Closest Margin"])

    results = db_ops.get_contested_votes(
        state=state_filter.upper().strip() if state_filter else None,
        category=cat_val,
    )

    # Apply confidence filter
    if confidence_filter == "High Only":
        results = [(v, i, m, d) for v, i, m, d in results if v.confidence == "high"]
    elif confidence_filter == "High + Medium":
        results = [(v, i, m, d) for v, i, m, d in results if v.confidence in ("high", "medium")]

    # Sort
    if sort_by == "Closest Margin":
        def margin_key(r):
            v = r[0]
            if v.votes_for is not None and v.votes_against is not None:
                return abs(v.votes_for - v.votes_against)
            return 999
        results = sorted(results, key=margin_key)

    st.write(f"**{len(results)}** contested votes found")

    for vote, item, meeting, district in results:
        margin = ""
        if vote.votes_for is not None and vote.votes_against is not None:
            margin = f" ({vote.votes_for}-{vote.votes_against})"

        icon = "🔴" if vote.result == "failed" else "🟡"
        cat_label = format_category(item.item_category)

        with st.expander(
            f"{icon} {district.district_name} ({district.state}) | "
            f"{meeting.meeting_date} | {item.item_title}{margin}"
        ):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.write(f"**Category:** {cat_label}")
                st.write(f"**Motion:** {vote.motion_text or 'N/A'}")
                st.write(f"**Result:** {vote.result.upper()}{margin}")
                if vote.motion_maker or vote.motion_seconder:
                    st.write(f"**Moved by:** {vote.motion_maker or '?'} / **Seconded by:** {vote.motion_seconder or '?'}")

            with col2:
                if vote.individual_votes:
                    yes_votes = [iv for iv in vote.individual_votes if iv.member_vote == "yes"]
                    no_votes = [iv for iv in vote.individual_votes if iv.member_vote == "no"]
                    abstains = [iv for iv in vote.individual_votes if iv.member_vote == "abstain"]

                    if yes_votes:
                        st.markdown("**Yes:** " + ", ".join(iv.member_name for iv in yes_votes))
                    if no_votes:
                        st.markdown("**No:** " + ", ".join(f"**{iv.member_name}**" for iv in no_votes))
                    if abstains:
                        st.markdown("**Abstain:** " + ", ".join(iv.member_name for iv in abstains))
                else:
                    st.caption("No individual vote records available for this motion.")


def render_district_browser(db_ops, session):
    """Render district browser page."""
    st.header("District Browser")
    st.caption("Explore meeting data and vote records for individual school districts.")

    districts = db_ops.get_all_districts()
    if not districts:
        st.warning("No districts in database yet. Run the extraction pipeline first.")
        return

    # Filters
    col1, col2 = st.columns([1, 3])
    with col1:
        states = sorted(set(d.state for d in districts))
        selected_state = st.selectbox("Filter by State", ["All"] + states)

    filtered = districts if selected_state == "All" else [d for d in districts if d.state == selected_state]

    with col2:
        district_names = {d.district_name: d for d in filtered}
        selected_name = st.selectbox("Select District", sorted(district_names.keys()))

    if not selected_name:
        return

    district = district_names[selected_name]

    # District stats
    meeting_count = session.query(func.count(Meeting.meeting_id)).filter(Meeting.district_id == district.district_id).scalar()
    vote_count = (
        session.query(func.count(Vote.vote_id))
        .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
        .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
        .filter(Meeting.district_id == district.district_id)
        .scalar()
    )
    iv_count = (
        session.query(func.count(IndividualVote.individual_vote_id))
        .join(Vote, IndividualVote.vote_id == Vote.vote_id)
        .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
        .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
        .filter(Meeting.district_id == district.district_id)
        .scalar()
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("State", district.state)
    with col2:
        st.metric("Meetings", meeting_count)
    with col3:
        st.metric("Votes", vote_count)
    with col4:
        st.metric("Individual Records", iv_count)

    # Show meetings
    meetings = db_ops.get_meetings_for_district(district.district_id)
    st.subheader(f"Meetings ({len(meetings)})")

    for meeting in meetings:
        with st.expander(f"{meeting.meeting_date} | {meeting.meeting_type.replace('_', ' ').title()}"):
            if meeting.members_present:
                try:
                    present = json.loads(meeting.members_present)
                    if present:
                        st.write(f"**Present:** {', '.join(present)}")
                except (json.JSONDecodeError, TypeError):
                    pass
            if meeting.members_absent:
                try:
                    absent = json.loads(meeting.members_absent)
                    if absent:
                        st.write(f"**Absent:** {', '.join(absent)}")
                except (json.JSONDecodeError, TypeError):
                    pass

            items = (session.query(AgendaItem)
                    .filter(AgendaItem.meeting_id == meeting.meeting_id)
                    .all())

            for item in items:
                cat_label = format_category(item.item_category)
                has_vote_marker = " [VOTE]" if item.has_vote else ""
                st.markdown(
                    f"**{item.item_number or '-'}** {item.item_title} "
                    f"*({cat_label})*{has_vote_marker}"
                )

                if item.vote:
                    vote = item.vote
                    result_color = "green" if vote.result == "passed" else "red"
                    unanimous_label = "Unanimous" if vote.is_unanimous else f"{vote.votes_for}-{vote.votes_against}"
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;Result: :{result_color}[**{vote.result.upper()}**] "
                        f"({unanimous_label})"
                    )

                    if vote.individual_votes:
                        vote_strs = []
                        for iv in vote.individual_votes:
                            if iv.member_vote == "yes":
                                vote_strs.append(f"**{iv.member_name}**: Yes")
                            elif iv.member_vote == "no":
                                vote_strs.append(f"**{iv.member_name}**: **No**")
                            else:
                                vote_strs.append(f"**{iv.member_name}**: {iv.member_vote}")
                        st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;" + " | ".join(vote_strs))


def render_vote_search(db_ops):
    """Render vote search page."""
    st.header("Vote Search")
    st.caption("Search across all districts for specific policy topics, keywords, or motion text.")

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        keyword = st.text_input("Search keyword", placeholder="e.g., superintendent, budget, textbook, HVAC")
    with col2:
        state_filter = st.text_input("State (optional)", placeholder="e.g., NY")
    with col3:
        cat_val = category_selectbox("Category", key="vs_cat")

    if keyword:
        results = db_ops.search_votes(
            keyword,
            state=state_filter.upper().strip() if state_filter else None,
            category=cat_val,
        )

        st.write(f"Found **{len(results)}** votes matching '{keyword}'")

        for vote, item, meeting, district in results:
            cat_label = format_category(item.item_category)
            conf_badge = {"high": "[HIGH]", "medium": "[MED]", "low": "[LOW]"}.get(
                vote.confidence or "low", "[?]"
            )
            with st.expander(
                f"{district.district_name} ({district.state}) | {meeting.meeting_date} | "
                f"{item.item_title} {conf_badge}"
            ):
                st.write(f"**Category:** {cat_label}")
                st.write(f"**Confidence:** {(vote.confidence or 'unknown').title()}")
                st.write(f"**Motion:** {vote.motion_text or 'N/A'}")

                result_color = "green" if vote.result == "passed" else "red"
                unanimous = "Unanimous" if vote.is_unanimous else f"{vote.votes_for}-{vote.votes_against}"
                st.markdown(f"**Result:** :{result_color}[{vote.result.upper()}] ({unanimous})")

                if vote.individual_votes:
                    st.write("**Individual Votes:**")
                    for iv in vote.individual_votes:
                        marker = "Yes" if iv.member_vote == "yes" else f"**{iv.member_vote.upper()}**"
                        st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;{iv.member_name}: {marker}")
    else:
        st.info("Enter a keyword to search across all vote records.")


def render_member_profiles(analytics, session):
    """Render member voting profiles with detailed records."""
    st.header("Board Member Profiles")
    st.caption("Explore individual board members and their voting records where available.")

    # Get all known board members
    board_members = (session.query(BoardMember, District.district_name, District.state)
                     .join(District, BoardMember.district_id == District.district_id)
                     .order_by(District.state, District.district_name, BoardMember.member_name)
                     .all())

    if not board_members:
        st.warning("No board member records available yet.")
        return

    # Summary metrics
    total_members = len(board_members)
    districts_with_members = len(set(bm.BoardMember.district_id for bm in board_members))
    states_with_members = len(set(bm.state for bm in board_members))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Board Members Identified", total_members)
    with col2:
        st.metric("Across Districts", districts_with_members)
    with col3:
        st.metric("In States", states_with_members)

    # Filter and display table
    role_map = {
        "president": "President/Chair", "vice_president": "Vice President/Vice Chair",
        "secretary": "Secretary/Clerk", "treasurer": "Treasurer",
        "trustee": "Trustee", "member": "Member",
    }

    member_data = []
    for bm in board_members:
        member = bm.BoardMember
        role_display = role_map.get(member.role, member.role or "Member")
        member_data.append({
            "Name": member.member_name,
            "Role": role_display,
            "District": bm.district_name,
            "State": bm.state,
            "First Seen": str(member.first_seen_date) if member.first_seen_date else "",
            "Last Seen": str(member.last_seen_date) if member.last_seen_date else "",
        })

    df = pd.DataFrame(member_data)
    states = sorted(df["State"].unique())
    selected_state = st.selectbox("Filter by State", ["All"] + states, key="mp_state")
    if selected_state != "All":
        df = df[df["State"] == selected_state]

    st.dataframe(df, use_container_width=True, hide_index=True)

    # Detailed voting record section
    st.divider()
    st.subheader("Individual Voting Records")
    st.caption("Select a board member with 3+ recorded roll-call votes to see their detailed record.")

    members_with_votes = (session.query(
            IndividualVote.member_name,
            func.count(IndividualVote.individual_vote_id).label("cnt"),
        )
        .group_by(IndividualVote.member_name)
        .having(func.count(IndividualVote.individual_vote_id) >= 3)
        .order_by(func.count(IndividualVote.individual_vote_id).desc())
        .all())

    if not members_with_votes:
        st.info("No members have 3+ individual vote records yet.")
        return

    member_options = [f"{m[0]} ({m[1]} votes)" for m in members_with_votes]
    selected_idx = st.selectbox("Select Board Member", range(len(member_options)),
                                format_func=lambda i: member_options[i])
    selected_name = members_with_votes[selected_idx][0]

    profile = analytics.member_profile(selected_name)

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
            st.write("**Voting by Category:**")
            cat_df = pd.DataFrame(profile["categories"])
            cat_df["category"] = cat_df["category"].apply(format_category)
            cat_df["dissent_rate"] = cat_df.apply(
                lambda r: f"{r['no_votes']/r['total']*100:.0f}%" if r["total"] > 0 else "0%",
                axis=1,
            )
            st.dataframe(cat_df, use_container_width=True, hide_index=True,
                         column_config={
                             "category": "Category",
                             "total": "Total Votes",
                             "no_votes": "No Votes",
                             "dissent_rate": "Dissent Rate",
                         })

    # Voting history detail table
    st.subheader("Voting History")
    records = (
        session.query(IndividualVote, Vote, AgendaItem, Meeting, District)
        .join(Vote, IndividualVote.vote_id == Vote.vote_id)
        .join(AgendaItem, Vote.item_id == AgendaItem.item_id)
        .join(Meeting, AgendaItem.meeting_id == Meeting.meeting_id)
        .join(District, Meeting.district_id == District.district_id)
        .filter(IndividualVote.member_name == selected_name)
        .order_by(Meeting.meeting_date.desc())
        .limit(50)
        .all()
    )

    if records:
        history_data = []
        for iv, vote, item, meeting, district in records:
            history_data.append({
                "Date": str(meeting.meeting_date),
                "District": district.district_name,
                "Item": item.item_title[:80] + ("..." if len(item.item_title or "") > 80 else ""),
                "Category": format_category(item.item_category),
                "Vote": iv.member_vote.upper(),
                "Result": (vote.result or "").upper(),
                "Unanimous": "Yes" if vote.is_unanimous else "No",
            })
        hist_df = pd.DataFrame(history_data)
        st.dataframe(hist_df, use_container_width=True, hide_index=True)


def render_trends(analytics):
    """Render trend dashboard."""
    st.header("Trends & Analytics")
    st.caption("Patterns in school board voting across time, geography, and policy areas.")

    # Monthly trends (full width)
    trends = analytics.vote_trends_by_month()
    if trends:
        st.plotly_chart(monthly_trend_chart(trends), use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        categories = analytics.votes_by_category()
        if categories:
            for c in categories:
                c["category"] = format_category(c["category"])
            st.plotly_chart(category_vote_chart(categories), use_container_width=True)
    with col2:
        contested = analytics.most_contested_categories()
        if contested:
            for c in contested:
                c["category"] = format_category(c["category"])
            st.plotly_chart(dissent_rate_chart(contested), use_container_width=True)

    # District comparison
    st.subheader("District Comparison: Contested Vote Rates")
    st.caption("Districts with the highest proportion of non-unanimous votes.")
    district_rates = analytics.district_dissent_rates()
    if district_rates:
        st.plotly_chart(district_contested_chart(district_rates), use_container_width=True)


if __name__ == "__main__":
    main()

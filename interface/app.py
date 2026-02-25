"""Streamlit dashboard for the School Board Vote Tracker.

Polished, client-facing dashboard for demos and outreach.

Run: streamlit run interface/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import func

from config.settings import DATABASE_PATH
from database.models import (
    init_database, get_session,
    District, Meeting, AgendaItem, Vote, IndividualVote, BoardMember,
)
from database.operations import DatabaseOperations
from analytics.vote_analytics import VoteAnalytics
from analytics.visualizations import (
    category_vote_chart, state_comparison_chart, dissent_rate_chart,
    monthly_trend_chart, member_vote_pie, district_contested_chart,
)

# ── Constants ─────────────────────────────────────────────────────────────

ACCENT_BLUE = "#0984E3"
PALETTE = [
    "#0984E3", "#6C5CE7", "#00B894", "#E17055", "#FDCB6E",
    "#74B9FF", "#A29BFE", "#55EFC4", "#FF7675", "#DFE6E9",
]

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
    return CATEGORY_LABELS.get(cat, cat.replace("_", " ").title() if cat else "Other")


def section_header(text):
    st.markdown(
        f'<p class="section-header">{text}</p>',
        unsafe_allow_html=True,
    )


def category_selectbox(label="Category", key=None, include_all=True):
    options = (["All"] if include_all else []) + ALL_CATEGORIES
    display = (["All"] if include_all else []) + [CATEGORY_LABELS[c] for c in ALL_CATEGORIES]
    idx = st.selectbox(label, range(len(options)), format_func=lambda i: display[i], key=key)
    val = options[idx]
    return val if val != "All" else None


# ── Page config & CSS ─────────────────────────────────────────────────────

_favicon = Path(__file__).resolve().parent.parent / ".streamlit" / "favicon.png"
st.set_page_config(
    page_title="School Board Vote Tracker",
    page_icon=str(_favicon) if _favicon.exists() else ":classical_building:",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

.block-container { padding-top: 1.5rem; max-width: 1200px; }

.main-title {
    font-family: 'Inter', sans-serif;
    font-size: 2.2rem;
    font-weight: 700;
    color: #FFFFFF;
    margin-bottom: 0;
    line-height: 1.2;
}
.main-subtitle {
    font-family: 'Inter', sans-serif;
    font-size: 1.05rem;
    color: #94A3B8;
    margin-top: 2px;
    margin-bottom: 1.2rem;
}

/* KPI cards */
[data-testid="stMetric"] {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 16px 20px;
}
[data-testid="stMetricLabel"] {
    font-family: 'Inter', sans-serif;
    font-size: 0.8rem !important;
    font-weight: 500;
    color: #64748B !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    font-family: 'Inter', sans-serif;
    font-size: 1.8rem !important;
    font-weight: 700;
    color: #1B2A4A !important;
}

/* Section headers */
.section-header {
    font-family: 'Inter', sans-serif;
    font-size: 1.25rem;
    font-weight: 600;
    color: #FFFFFF;
    margin-top: 0.8rem;
    margin-bottom: 0.4rem;
    padding-bottom: 0.3rem;
    border-bottom: 2px solid #E2E8F0;
}

/* Table styling */
.dataframe { font-family: 'Inter', sans-serif !important; }

/* Hide Streamlit branding */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stAppDeployButton"] { display: none; }
._profileContainer_gzau3_53 { display: none !important; }
._container_gzau3_1 { display: none !important; }
[data-testid="stStatusWidget"] { display: none; }
div[class*="profileContainer"] { display: none !important; }
div[class*="hostContainer"] { display: none !important; }
iframe[title="streamlit_badge"] { display: none !important; }
#stStreamlitBadge { display: none !important; }

/* Sidebar */
[data-testid="stSidebar"] { background: #1B2A4A; }

div[data-testid="stDataFrame"] div[class*="glideDataEditor"] {
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}
</style>
""", unsafe_allow_html=True)


# ── Database ──────────────────────────────────────────────────────────────

@st.cache_resource
def get_db():
    init_database(str(DATABASE_PATH))
    return get_session(str(DATABASE_PATH))


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    session = get_db()
    db_ops = DatabaseOperations(session)
    analytics = VoteAnalytics(session)

    # Sidebar
    st.sidebar.markdown(
        '<p class="main-title" style="font-size:1.4rem;">School Board Vote Tracker</p>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        '<p class="main-subtitle" style="font-size:0.9rem;">'
        'Structured data on school board governance decisions across the United States'
        '</p>',
        unsafe_allow_html=True,
    )
    st.sidebar.divider()
    page = st.sidebar.radio(
        "Navigate",
        ["Dashboard", "Contested Votes", "District Browser",
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

    # Footer (all pages)
    st.markdown("")
    st.divider()
    st.markdown(
        "<div style='text-align: center; color: #94A3B8; font-size: 0.8rem; padding: 8px 0;'>"
        "School Board Vote Tracker &bull; "
        "Data extracted from public BoardDocs minutes using a zero-cost rule engine &bull; "
        "No LLM API calls required"
        "<br>"
        "Built by <strong>Nathan Goldberg</strong> &nbsp;|&nbsp; "
        "<a href='mailto:nathanmauricegoldberg@gmail.com' style='color: #0984E3; text-decoration: none;'>nathanmauricegoldberg@gmail.com</a> &nbsp;|&nbsp; "
        "<a href='https://www.linkedin.com/in/nathan-goldberg-62a44522a' target='_blank' style='color: #0984E3; text-decoration: none;'>LinkedIn</a>"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Dashboard page ────────────────────────────────────────────────────────

def render_dashboard(db_ops, analytics, session):
    st.markdown(
        '<p class="main-title">School Board Vote Tracker</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="main-subtitle">'
        'The first structured database of school board voting records. '
        'Tracking how elected board members vote on personnel, budgets, curriculum, '
        'and policy decisions across hundreds of districts nationwide.'
        '</p>',
        unsafe_allow_html=True,
    )

    stats = db_ops.get_vote_statistics()
    states = analytics.votes_by_state()
    state_count = len(set(s["state"] for s in states)) if states else 0
    failed_count = session.query(func.count(Vote.vote_id)).filter(Vote.result == "failed").scalar() or 0

    # KPI Row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Districts", f"{stats['total_districts']:,}")
    c2.metric("States", f"{state_count}")
    c3.metric("Votes Tracked", f"{stats['total_votes']:,}")
    c4.metric("Contested Votes", f"{stats['contested_votes']:,}")
    c5.metric("Failed Motions", f"{failed_count:,}")

    st.markdown("")

    # State coverage badges
    if states:
        section_header(f"Data Coverage: {state_count} States")
        state_list = sorted(states, key=lambda x: x["state"])
        badges = " ".join(
            f'<span style="display:inline-block; background:#1B2A4A; border:1px solid #334155; '
            f'border-radius:6px; padding:4px 10px; margin:3px; font-size:0.85rem; color:#E2E8F0;">'
            f'{s["state"]} ({s["districts"]}d, {s["total_votes"]}v)</span>'
            for s in state_list
        )
        st.markdown(badges, unsafe_allow_html=True)
        st.markdown("")

    # Charts Row 1
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

    # Charts Row 2
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

    # Top dissenters
    section_header("Most Frequent Dissenters")
    st.caption("Board members who most often vote 'No' on motions (minimum 3 recorded votes).")
    dissenters = analytics.top_dissenters(limit=10)
    if dissenters:
        diss_df = pd.DataFrame(dissenters)
        diss_df["dissent_rate"] = diss_df["dissent_rate"].apply(lambda x: f"{x:.1%}")
        st.dataframe(
            diss_df, use_container_width=True, hide_index=True,
            column_config={
                "member_name": "Board Member",
                "total_votes": "Total Votes",
                "no_votes": "No Votes",
                "abstain_votes": "Abstentions",
                "dissent_rate": "Dissent Rate",
            },
        )

    # Data quality
    st.markdown("")
    section_header("Data Quality")
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
            total = sum(conf_data.values())
            for _, row in conf_df.iterrows():
                pct = row["Votes"] / total * 100 if total else 0
                st.metric(f"{row['Confidence']} Confidence", f"{row['Votes']:,} ({pct:.1f}%)")
        with col2:
            colors = {"High": "#00B894", "Medium": "#FDCB6E", "Low": "#FF7675"}
            fig = go.Figure(go.Bar(
                x=conf_df["Confidence"], y=conf_df["Votes"],
                marker_color=[colors.get(c, "#999") for c in conf_df["Confidence"]],
                text=conf_df["Votes"], textposition="outside",
            ))
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif"),
                title="Vote Confidence Distribution",
                height=300, margin=dict(l=40, r=20, t=40, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "**High** confidence votes have explicit roll-call language or structured BoardDocs vote blocks. "
            "**Medium** confidence votes match multiple vote-indicating patterns. "
            "**Low** confidence votes are inferred from agenda item type with a single pattern match."
        )

    # Methodology
    st.markdown("")
    with st.expander("About This Data / Methodology", expanded=False):
        st.markdown("""
### How It Works

The School Board Vote Tracker extracts structured voting data from public board meeting
minutes published through BoardDocs:

1. **Scrape** — Playwright-based scrapers collect meeting minutes from BoardDocs platforms
   across {n_districts}+ school districts in {n_states} states.
2. **Extract** — A 1,800-line rule engine parses agenda items, motions, vote counts, and
   individual roll-call records. **No LLM is used** — all extraction is deterministic,
   costing $0 in API fees.
3. **Classify** — Agenda items are categorized into 15 policy areas (personnel, budget,
   curriculum, facilities, etc.) using keyword-based heuristics.
4. **Validate** — Each vote receives a confidence score (high/medium/low) based on how
   many extraction signals were present.

### What Makes This Unique

- **First structured dataset** of school board voting records at this scale
- **Individual roll-call records**: 11,000+ named votes showing exactly how each board
  member voted
- **Zero-cost extraction**: rule engine replaces LLM calls entirely
- **Contested vote detection**: identifies the {n_contested} motions where board members
  disagreed

### Limitations

- Coverage is limited to districts using BoardDocs (the dominant platform)
- Some districts publish only agenda text, not full minutes with vote details
- 16% of votes have "low" confidence extraction — use the confidence filter to focus
  on high-quality records
""".format(
            n_districts=stats["total_districts"],
            n_states=state_count,
            n_contested=stats["contested_votes"],
        ))


# ── Contested Votes page ──────────────────────────────────────────────────

def render_contested_votes(db_ops, session):
    st.markdown(
        '<p class="main-title">Contested Votes</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="main-subtitle">'
        'Non-unanimous votes are where governance gets interesting. '
        'These are the decisions where at least one board member disagreed.'
        '</p>',
        unsafe_allow_html=True,
    )

    total_contested = session.query(func.count(Vote.vote_id)).filter(Vote.is_unanimous == False).scalar() or 0
    total_with_iv = (
        session.query(func.count(Vote.vote_id.distinct()))
        .join(IndividualVote, Vote.vote_id == IndividualVote.vote_id)
        .filter(Vote.is_unanimous == False)
        .scalar() or 0
    )
    failed_count = session.query(func.count(Vote.vote_id)).filter(Vote.result == "failed").scalar() or 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Contested Votes", f"{total_contested:,}")
    c2.metric("With Named Roll Calls", f"{total_with_iv:,}")
    c3.metric("Motions That Failed", f"{failed_count:,}")

    st.markdown("")

    # Filters
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        state_filter = st.text_input("Filter by State", placeholder="e.g., TX, FL, NY", key="cv_state")
    with col2:
        cat_val = category_selectbox("Category", key="cv_cat")
    with col3:
        confidence_filter = st.selectbox("Confidence", ["All", "High Only", "High + Medium"], key="cv_conf")
    with col4:
        sort_by = st.selectbox("Sort by", ["Most Recent", "Closest Margin"])

    results = db_ops.get_contested_votes(
        state=state_filter.upper().strip() if state_filter else None,
        category=cat_val,
    )

    if confidence_filter == "High Only":
        results = [(v, i, m, d) for v, i, m, d in results if v.confidence == "high"]
    elif confidence_filter == "High + Medium":
        results = [(v, i, m, d) for v, i, m, d in results if v.confidence in ("high", "medium")]

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

        icon = "FAILED" if vote.result == "failed" else "CONTESTED"
        icon_color = "#FF7675" if vote.result == "failed" else "#FDCB6E"
        cat_label = format_category(item.item_category)

        with st.expander(
            f"[{icon}] {district.district_name} ({district.state}) | "
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
                    st.caption("No individual vote records available.")


# ── District Browser page ─────────────────────────────────────────────────

def render_district_browser(db_ops, session):
    st.markdown(
        '<p class="main-title">District Browser</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="main-subtitle">'
        'Explore meeting data and vote records for individual school districts.'
        '</p>',
        unsafe_allow_html=True,
    )

    districts = db_ops.get_all_districts()
    if not districts:
        st.warning("No districts in database.")
        return

    col1, col2 = st.columns([1, 3])
    with col1:
        states = sorted(set(d.state for d in districts))
        selected_state = st.selectbox("State", ["All"] + states)
    filtered = districts if selected_state == "All" else [d for d in districts if d.state == selected_state]
    with col2:
        district_names = {d.district_name: d for d in filtered}
        selected_name = st.selectbox("District", sorted(district_names.keys()))

    if not selected_name:
        return

    district = district_names[selected_name]

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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("State", district.state)
    c2.metric("Meetings", meeting_count)
    c3.metric("Votes", vote_count)
    c4.metric("Individual Records", iv_count)

    meetings = db_ops.get_meetings_for_district(district.district_id)
    section_header(f"Meetings ({len(meetings)})")

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
                has_vote_marker = " **[VOTE]**" if item.has_vote else ""
                st.markdown(
                    f"**{item.item_number or '-'}** {item.item_title} "
                    f"*({cat_label})*{has_vote_marker}"
                )
                if item.vote:
                    vote = item.vote
                    unanimous = "Unanimous" if vote.is_unanimous else f"{vote.votes_for}-{vote.votes_against}"
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;Result: **{vote.result.upper()}** ({unanimous})")
                    if vote.individual_votes:
                        vote_strs = []
                        for iv in vote.individual_votes:
                            if iv.member_vote == "yes":
                                vote_strs.append(f"{iv.member_name}: Yes")
                            elif iv.member_vote == "no":
                                vote_strs.append(f"**{iv.member_name}: No**")
                            else:
                                vote_strs.append(f"{iv.member_name}: {iv.member_vote}")
                        st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;" + " | ".join(vote_strs))


# ── Vote Search page ──────────────────────────────────────────────────────

def render_vote_search(db_ops):
    st.markdown(
        '<p class="main-title">Vote Search</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="main-subtitle">'
        'Search across all districts for specific policy topics, keywords, or motion text.'
        '</p>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        keyword = st.text_input("Search keyword", placeholder="e.g., superintendent, budget, textbook, HVAC")
    with col2:
        state_filter = st.text_input("State", placeholder="e.g., NY")
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
            conf_badge = {"high": "HIGH", "medium": "MED", "low": "LOW"}.get(vote.confidence or "low", "?")

            with st.expander(
                f"{district.district_name} ({district.state}) | {meeting.meeting_date} | "
                f"{item.item_title} [{conf_badge}]"
            ):
                st.write(f"**Category:** {cat_label}")
                st.write(f"**Confidence:** {(vote.confidence or 'unknown').title()}")
                st.write(f"**Motion:** {vote.motion_text or 'N/A'}")
                unanimous = "Unanimous" if vote.is_unanimous else f"{vote.votes_for}-{vote.votes_against}"
                st.markdown(f"**Result:** {vote.result.upper()} ({unanimous})")
                if vote.individual_votes:
                    st.write("**Individual Votes:**")
                    for iv in vote.individual_votes:
                        marker = "Yes" if iv.member_vote == "yes" else f"**{iv.member_vote.upper()}**"
                        st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;{iv.member_name}: {marker}")
    else:
        st.info("Enter a keyword to search across all vote records.")


# ── Member Profiles page ──────────────────────────────────────────────────

def render_member_profiles(analytics, session):
    st.markdown(
        '<p class="main-title">Board Member Profiles</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="main-subtitle">'
        'Explore individual board members and their voting records.'
        '</p>',
        unsafe_allow_html=True,
    )

    board_members = (session.query(BoardMember, District.district_name, District.state)
                     .join(District, BoardMember.district_id == District.district_id)
                     .order_by(District.state, District.district_name, BoardMember.member_name)
                     .all())

    if not board_members:
        st.warning("No board member records available.")
        return

    total_members = len(board_members)
    districts_with_members = len(set(bm.BoardMember.district_id for bm in board_members))
    states_with_members = len(set(bm.state for bm in board_members))

    c1, c2, c3 = st.columns(3)
    c1.metric("Board Members", total_members)
    c2.metric("Across Districts", districts_with_members)
    c3.metric("In States", states_with_members)

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

    member_df = pd.DataFrame(member_data)
    states = sorted(member_df["State"].unique())
    selected_state = st.selectbox("Filter by State", ["All"] + states, key="mp_state")
    if selected_state != "All":
        member_df = member_df[member_df["State"] == selected_state]

    st.dataframe(member_df, use_container_width=True, hide_index=True)

    # Detailed voting record
    st.markdown("")
    section_header("Individual Voting Records")
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Votes", profile["total_votes"])
    c2.metric("Yes Votes", profile["yes_votes"])
    c3.metric("No Votes", profile["no_votes"])
    c4.metric("Dissent Rate", f"{profile['dissent_rate']:.1%}")

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

    section_header("Voting History")
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
        st.dataframe(pd.DataFrame(history_data), use_container_width=True, hide_index=True)


# ── Trends page ───────────────────────────────────────────────────────────

def render_trends(analytics):
    st.markdown(
        '<p class="main-title">Trends & Analytics</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="main-subtitle">'
        'Patterns in school board voting across time, geography, and policy areas.'
        '</p>',
        unsafe_allow_html=True,
    )

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

    section_header("District Comparison: Contested Vote Rates")
    st.caption("Districts with the highest proportion of non-unanimous votes.")
    district_rates = analytics.district_dissent_rates()
    if district_rates:
        st.plotly_chart(district_contested_chart(district_rates), use_container_width=True)


if __name__ == "__main__":
    main()

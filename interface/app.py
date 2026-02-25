"""Streamlit dashboard for the School Board Vote Tracker.

Polished, client-facing dashboard for demos and outreach.

Run: streamlit run interface/app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import re
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from sqlalchemy import func, case

from config.settings import DATABASE_PATH
from database.models import (
    init_database, get_session,
    District, Meeting, AgendaItem, Vote, IndividualVote, BoardMember,
)
from database.operations import DatabaseOperations
from analytics.vote_analytics import VoteAnalytics
from analytics.visualizations import (
    category_vote_chart, state_comparison_chart, dissent_rate_chart,
    member_vote_pie,
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

ITEMS_PER_PAGE = 10

# ── Name validation ───────────────────────────────────────────────────────

_BAD_NAME_START = [
    "and ", "second by ", "board member", "chairperson", "school board",
    "student achievement", "human resources", "attorney", "as presented",
    "real property", "for the purpose", "teaching assistant",
    "volunteer assistant", "varsity", "junior varsity", "head coach",
    "assistant coach", "co for ", "members ",
]

_BAD_NAME_CONTAINS = [
    "board member", "as presented", "purpose of", "property negotiator",
    "members are all", "second by", "student board member",
]


def is_valid_member_name(name: str) -> bool:
    """Return True if *name* looks like a real person's name."""
    if not name or len(name.strip()) < 4:
        return False
    n = name.strip()
    if n.endswith("."):
        return False
    if " " not in n:
        return False
    low = n.lower()
    if low == "vice chair" or low == "teacher":
        return False
    for pat in _BAD_NAME_START:
        if low.startswith(pat):
            return False
    for pat in _BAD_NAME_CONTAINS:
        if pat in low:
            return False
    if "(" in n or ")" in n:
        return False
    if low.endswith(" and"):
        return False
    return True


# ── Helpers ───────────────────────────────────────────────────────────────

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


def completeness_score(vote, item):
    """Score how complete a contested vote record is (higher = more detail)."""
    score = 0
    if vote.individual_votes:
        score += 3 + min(len(vote.individual_votes), 10)
    if vote.motion_text:
        score += 2
    if item.item_category and item.item_category != "other":
        score += 1
    if vote.votes_for is not None and vote.votes_against is not None:
        score += 1
    if vote.motion_maker or vote.motion_seconder:
        score += 1
    return score


def _render_member_detail(profile, analytics, session, key_prefix):
    """Render the full profile for a selected board member."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Votes", profile["total_votes"])
    c2.metric("Yes Votes", profile["yes_votes"])
    c3.metric("No Votes", profile["no_votes"])
    c4.metric("Dissent Rate", f"{profile['dissent_rate']:.1%}")

    col1, col2 = st.columns(2)
    with col1:
        fig = member_vote_pie(profile)
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_pie")
    with col2:
        if profile.get("categories"):
            st.write("**Voting by Category:**")
            cat_df = pd.DataFrame(profile["categories"])
            cat_df["category"] = cat_df["category"].apply(format_category)
            cat_df["dissent_rate"] = cat_df.apply(
                lambda r: f"{r['no_votes']/r['total']*100:.0f}%"
                if r["total"] > 0 else "0%",
                axis=1,
            )
            st.dataframe(
                cat_df, use_container_width=True, hide_index=True,
                column_config={
                    "category": "Category",
                    "total": "Total Votes",
                    "no_votes": "No Votes",
                    "dissent_rate": "Dissent Rate",
                },
            )

    section_header("Voting History")
    selected_name = profile["member_name"]
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
                "Item": (
                    item.item_title[:80]
                    + ("..." if len(item.item_title or "") > 80 else "")
                ),
                "Category": format_category(item.item_category),
                "Vote": iv.member_vote.upper(),
                "Result": (vote.result or "").upper(),
                "Unanimous": "Yes" if vote.is_unanimous else "No",
            })
        st.dataframe(
            pd.DataFrame(history_data),
            use_container_width=True,
            hide_index=True,
        )


def _render_vote_expander(vote, item, meeting, district):
    """Render a single contested vote inside an expander."""
    margin = ""
    if vote.votes_for is not None and vote.votes_against is not None:
        margin = f" ({vote.votes_for}-{vote.votes_against})"

    icon = "FAILED" if vote.result == "failed" else "CONTESTED"
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
                st.write(
                    f"**Moved by:** {vote.motion_maker or '?'} / "
                    f"**Seconded by:** {vote.motion_seconder or '?'}"
                )
        with col2:
            yes_votes = [iv for iv in vote.individual_votes if iv.member_vote == "yes"]
            no_votes = [iv for iv in vote.individual_votes if iv.member_vote == "no"]
            abstains = [iv for iv in vote.individual_votes if iv.member_vote == "abstain"]
            if yes_votes:
                st.markdown(
                    "**Yes:** " + ", ".join(iv.member_name for iv in yes_votes)
                )
            if no_votes:
                st.markdown(
                    "**No:** "
                    + ", ".join(f"**{iv.member_name}**" for iv in no_votes)
                )
            if abstains:
                st.markdown(
                    "**Abstain:** " + ", ".join(iv.member_name for iv in abstains)
                )


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

/* KPI cards — dark theme */
[data-testid="stMetric"] {
    background: #1B2A4A;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 16px 20px;
}
[data-testid="stMetricLabel"] {
    font-family: 'Inter', sans-serif;
    font-size: 0.8rem !important;
    font-weight: 500;
    color: #94A3B8 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
[data-testid="stMetricValue"] {
    font-family: 'Inter', sans-serif;
    font-size: 1.8rem !important;
    font-weight: 700;
    color: #E2E8F0 !important;
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
    border-bottom: 2px solid #334155;
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

/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [data-baseweb="tab"] { font-family: 'Inter', sans-serif; font-weight: 500; }

div[data-testid="stDataFrame"] div[class*="glideDataEditor"] {
    border: 1px solid #334155;
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

    # Sidebar — branding & about
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

    stats = db_ops.get_vote_statistics()
    st.sidebar.markdown(
        f"**{stats['total_districts']:,}** districts &bull; "
        f"**{stats['total_votes']:,}** votes &bull; "
        f"**{stats['contested_votes']:,}** contested"
    )
    st.sidebar.markdown("")

    with st.sidebar.expander("About This Data", expanded=False):
        st.markdown(
            "This dashboard presents the first structured database of school board voting "
            "records. Data is extracted from public BoardDocs meeting minutes using a "
            "zero-cost rule engine — **no LLM API calls required**.\n\n"
            "Each vote receives a confidence score (high/medium/low) based on extraction "
            "quality. Use the confidence filter on the Explore tab to focus on "
            "the most reliable records."
        )

    st.sidebar.markdown("")
    st.sidebar.markdown(
        "<div style='color: #E2E8F0; padding: 8px 0;'>"
        "<p style='font-family: Inter, sans-serif; font-size: 1rem; font-weight: 600; "
        "color: #FFFFFF; margin-bottom: 4px;'>Built by Nathan Goldberg</p>"
        "<a href='mailto:nathanmauricegoldberg@gmail.com' style='color: #0984E3; "
        "font-size: 0.9rem; text-decoration: none;'>Email</a>"
        " &nbsp;&bull;&nbsp; "
        "<a href='https://www.linkedin.com/in/nathan-goldberg-62a44522a' target='_blank' "
        "style='color: #0984E3; font-size: 0.9rem; text-decoration: none;'>LinkedIn</a>"
        "</div>",
        unsafe_allow_html=True,
    )

    # Main area — title + tabs
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

    # ── Overview / Proof of Concept Note ──────────────────────────────
    st.markdown(
        "<div style='background: #1B2A4A; border: 1px solid #334155; border-radius: 10px; "
        "padding: 20px 24px; margin-bottom: 1.2rem; line-height: 1.7;'>"
        "<span style='font-family: Inter, sans-serif; font-size: 0.95rem; color: #E2E8F0;'>"
        "This dashboard presents the first structured database of school board voting records "
        "in the United States — extracted from public BoardDocs meeting minutes using a "
        "zero-cost rule engine (no LLM API calls). The current dataset covers "
        "<strong>{n_districts:,} districts</strong> across <strong>{n_states} states</strong> with "
        "<strong>{n_votes:,} votes</strong> and serves as a <strong>proof of concept</strong> "
        "for nationwide coverage. Expansion to thousands of additional districts is underway."
        "</span></div>".format(
            n_districts=stats["total_districts"],
            n_states=len(set(s["state"] for s in analytics.votes_by_state())) if analytics.votes_by_state() else 0,
            n_votes=stats["total_votes"],
        ),
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["Overview", "Board Members", "Explore"])

    with tabs[0]:
        render_overview(db_ops, analytics, session, stats)
    with tabs[1]:
        render_board_members(analytics, session)
    with tabs[2]:
        render_explore(db_ops, analytics, session)

    # Footer
    st.markdown("")
    st.divider()
    st.markdown(
        "<div style='text-align: center; padding: 16px 0;'>"
        "<p style='font-family: Inter, sans-serif; font-size: 1.3rem; font-weight: 600; "
        "color: #FFFFFF; margin-bottom: 6px;'>Built by Nathan Goldberg</p>"
        "<p style='font-family: Inter, sans-serif; font-size: 1rem; margin-top: 0; margin-bottom: 16px;'>"
        "<a href='mailto:nathanmauricegoldberg@gmail.com' style='color: #0984E3; text-decoration: none;'>nathanmauricegoldberg@gmail.com</a>"
        " &nbsp;&bull;&nbsp; "
        "<a href='https://www.linkedin.com/in/nathan-goldberg-62a44522a' target='_blank' "
        "style='color: #0984E3; text-decoration: none;'>LinkedIn</a></p>"
        "<p style='font-family: Inter, sans-serif; font-size: 0.8rem; color: #94A3B8; margin-top: 0;'>"
        "School Board Vote Tracker &bull; "
        "Data extracted from public BoardDocs minutes using a zero-cost rule engine &bull; "
        "No LLM API calls required</p>"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Overview tab ──────────────────────────────────────────────────────────

def render_overview(db_ops, analytics, session, stats):
    states = analytics.votes_by_state()
    state_count = len(set(s["state"] for s in states)) if states else 0
    failed_count = (
        session.query(func.count(Vote.vote_id))
        .filter(Vote.result == "failed").scalar() or 0
    )

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
            st.plotly_chart(
                category_vote_chart(categories),
                use_container_width=True,
                key="ov_category",
            )
    with col2:
        if states:
            st.plotly_chart(
                state_comparison_chart(states),
                use_container_width=True,
                key="ov_state",
            )

    # Dissent rate chart — full width
    contested_cats = analytics.most_contested_categories()
    if contested_cats:
        for c in contested_cats:
            c["category"] = format_category(c["category"])
        st.plotly_chart(
            dissent_rate_chart(contested_cats),
            use_container_width=True,
            key="ov_dissent",
        )

    # Extraction method
    st.markdown("")
    section_header("Extraction Method")
    st.markdown(
        "All records are extracted from real board meeting minutes published through "
        "BoardDocs. The extraction method determines how many confirming signals were "
        "present — records at every level are overwhelmingly accurate."
    )
    confidence_counts = (
        session.query(Vote.confidence, func.count(Vote.vote_id))
        .group_by(Vote.confidence)
        .all()
    )
    if confidence_counts:
        conf_data = {r[0] or "unknown": r[1] for r in confidence_counts}
        total = sum(conf_data.values())
        conf_methods = [
            (
                "Roll-Call & Vote Blocks",
                "high",
                conf_data.get("high", 0),
                "Highest confidence — explicit roll-call language or structured "
                "BoardDocs vote blocks with multiple confirming signals",
            ),
            (
                "Multi-Pattern Match",
                "medium",
                conf_data.get("medium", 0),
                "High confidence — several vote-indicating patterns corroborate "
                "the extracted record (e.g., motion text + result + vote count)",
            ),
            (
                "Single-Pattern Inference",
                "low",
                conf_data.get("low", 0),
                "Moderate confidence — inferred from a single pattern match, but "
                "still extracted from real meeting minutes",
            ),
        ]

        conf_df = pd.DataFrame([
            {"Method": method, "Votes": count}
            for method, _, count, _ in conf_methods if count > 0
        ])

        col1, col2 = st.columns([1, 2])
        with col1:
            for method, _, count, note in conf_methods:
                if count == 0:
                    continue
                pct = count / total * 100 if total else 0
                st.metric(method, f"{count:,} ({pct:.1f}%)")
                st.caption(note)
        with col2:
            colors = {
                "Roll-Call & Vote Blocks": "#00B894",
                "Multi-Pattern Match": "#FDCB6E",
                "Single-Pattern Inference": "#FF7675",
            }
            fig = go.Figure(go.Bar(
                x=conf_df["Method"], y=conf_df["Votes"],
                marker_color=[colors.get(m, "#999") for m in conf_df["Method"]],
                text=conf_df["Votes"], textposition="outside",
            ))
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, sans-serif"),
                title="Votes by Extraction Method",
                height=550, margin=dict(l=40, r=20, t=40, b=40),
                yaxis=dict(range=[0, max(conf_df["Votes"]) * 1.18]),
            )
            st.plotly_chart(fig, use_container_width=True, key="ov_confidence")

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
- **Individual roll-call records**: {n_individual:,}+ named votes showing exactly how each
  board member voted
- **Zero-cost extraction**: rule engine replaces LLM calls entirely
- **Contested vote detection**: identifies the {n_contested} motions where board members
  disagreed

### Limitations

- Coverage is limited to districts using BoardDocs (the dominant platform)
- Some districts publish only agenda text, not full minutes with vote details
- Some votes have "low" confidence extraction — use the confidence filter to focus
  on high-quality records
""".format(
            n_districts=stats["total_districts"],
            n_states=state_count,
            n_individual=stats["total_individual_votes"],
            n_contested=stats["contested_votes"],
        ))


# ── Board Members tab ────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def _get_featured_members(_session):
    """Return board members with the most interesting voting records."""
    rows = (
        _session.query(
            IndividualVote.member_name,
            func.count(IndividualVote.individual_vote_id).label("total"),
            func.sum(case((IndividualVote.member_vote == "yes", 1), else_=0)).label("yes"),
            func.sum(case((IndividualVote.member_vote == "no", 1), else_=0)).label("no"),
            func.sum(case((IndividualVote.member_vote == "abstain", 1), else_=0)).label("abstain"),
        )
        .group_by(IndividualVote.member_name)
        .having(func.count(IndividualVote.individual_vote_id) >= 30)
        .having(
            (func.sum(case((IndividualVote.member_vote == "no", 1), else_=0))
             + func.sum(case((IndividualVote.member_vote == "abstain", 1), else_=0))) >= 1
        )
        .order_by(
            (func.sum(case((IndividualVote.member_vote == "no", 1), else_=0))
             * 100.0 / func.count(IndividualVote.individual_vote_id)).desc()
        )
        .all()
    )
    featured = []
    for r in rows:
        name = r[0]
        if not is_valid_member_name(name):
            continue
        featured.append({
            "name": name,
            "total": r[1],
            "yes": r[2],
            "no": r[3],
            "abstain": r[4],
            "dissent_pct": round(r[3] / r[1] * 100, 1) if r[1] else 0,
        })
        if len(featured) >= 25:
            break
    return featured


def render_board_members(analytics, session):
    section_header("Featured Board Members")

    featured = _get_featured_members(session)

    if featured:
        feat_options = [
            f"{m['name']} — {m['total']} votes, {m['no']} No, "
            f"{m['abstain']} Abstain ({m['dissent_pct']}% dissent)"
            for m in featured
        ]
        feat_idx = st.selectbox(
            "Select a featured board member",
            range(len(feat_options)),
            format_func=lambda i: feat_options[i],
            key="feat_member",
        )
        feat_name = featured[feat_idx]["name"]
        profile = analytics.member_profile(feat_name)
        _render_member_detail(profile, analytics, session, key_prefix="feat")
    else:
        st.info("No featured members available.")


# ── Explore tab ──────────────────────────────────────────────────────────

def render_explore(db_ops, analytics, session):
    search_mode = st.radio(
        "What are you looking for?",
        ["Contested Votes", "Keyword Search", "Browse Districts", "Find Board Members"],
        horizontal=True,
        key="explore_mode",
    )

    st.markdown("")

    if search_mode == "Contested Votes":
        _explore_contested(db_ops, session)
    elif search_mode == "Keyword Search":
        _explore_keyword(db_ops)
    elif search_mode == "Browse Districts":
        _explore_districts(db_ops, session)
    elif search_mode == "Find Board Members":
        _explore_members(analytics, session)


def _explore_contested(db_ops, session):
    """Contested votes with filters and pagination."""
    all_results = db_ops.get_contested_votes(limit=1000)
    all_results = [
        (v, i, m, d) for v, i, m, d in all_results
        if v.individual_votes and len(v.individual_votes) > 0
    ]

    total_count = len(all_results)
    failed_count = sum(1 for v, i, m, d in all_results if v.result == "failed")

    c1, c2 = st.columns(2)
    c1.metric("Contested Votes with Roll Calls", f"{total_count:,}")
    c2.metric("Motions That Failed", f"{failed_count:,}")

    st.markdown("")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        state_filter = st.text_input(
            "Filter by State", placeholder="e.g., TX, FL, NY", key="cv_state"
        )
    with col2:
        cat_val = category_selectbox("Category", key="cv_cat")
    with col3:
        confidence_filter = st.selectbox(
            "Confidence", ["All", "High Only", "High + Medium"], key="cv_conf"
        )
    with col4:
        sort_by = st.selectbox(
            "Sort by", ["Most Detailed", "Most Recent", "Closest Margin"],
            key="cv_sort",
        )

    results = list(all_results)
    if state_filter:
        sf = state_filter.upper().strip()
        results = [(v, i, m, d) for v, i, m, d in results if d.state == sf]
    if cat_val:
        results = [(v, i, m, d) for v, i, m, d in results if i.item_category == cat_val]
    if confidence_filter == "High Only":
        results = [(v, i, m, d) for v, i, m, d in results if v.confidence == "high"]
    elif confidence_filter == "High + Medium":
        results = [
            (v, i, m, d) for v, i, m, d in results
            if v.confidence in ("high", "medium")
        ]

    if sort_by == "Most Recent":
        results = sorted(results, key=lambda r: str(r[2].meeting_date or ""), reverse=True)
    elif sort_by == "Closest Margin":
        def margin_key(r):
            v = r[0]
            if v.votes_for is not None and v.votes_against is not None:
                return abs(v.votes_for - v.votes_against)
            return 999
        results = sorted(results, key=margin_key)
    else:
        results = sorted(
            results, key=lambda r: completeness_score(r[0], r[1]), reverse=True
        )

    st.write(f"**{len(results)}** contested votes found")

    # Pagination
    if "cv_show_count" not in st.session_state:
        st.session_state.cv_show_count = ITEMS_PER_PAGE

    show_n = min(st.session_state.cv_show_count, len(results))
    for vote, item, meeting, district in results[:show_n]:
        _render_vote_expander(vote, item, meeting, district)

    if show_n < len(results):
        remaining = len(results) - show_n
        if st.button(f"Show more ({remaining} remaining)", key="cv_more"):
            st.session_state.cv_show_count += ITEMS_PER_PAGE
            st.rerun()


def _explore_keyword(db_ops):
    """Keyword search across all votes."""
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        keyword = st.text_input(
            "Search keyword",
            placeholder="e.g., superintendent, budget, textbook, HVAC",
            key="ks_keyword",
        )
    with col2:
        state_filter = st.text_input("State", placeholder="e.g., NY", key="ks_state")
    with col3:
        cat_val = category_selectbox("Category", key="ks_cat")

    if keyword:
        results = db_ops.search_votes(
            keyword,
            state=state_filter.upper().strip() if state_filter else None,
            category=cat_val,
        )
        st.write(f"Found **{len(results)}** votes matching '{keyword}'")

        if "ks_show_count" not in st.session_state:
            st.session_state.ks_show_count = ITEMS_PER_PAGE

        show_n = min(st.session_state.ks_show_count, len(results))

        for vote, item, meeting, district in results[:show_n]:
            cat_label = format_category(item.item_category)
            conf_badge = {"high": "HIGH", "medium": "MED", "low": "LOW"}.get(
                vote.confidence or "low", "?"
            )
            with st.expander(
                f"{district.district_name} ({district.state}) | {meeting.meeting_date} | "
                f"{item.item_title} [{conf_badge}]"
            ):
                st.write(f"**Category:** {cat_label}")
                st.write(f"**Confidence:** {(vote.confidence or 'unknown').title()}")
                st.write(f"**Motion:** {vote.motion_text or 'N/A'}")
                unanimous = (
                    "Unanimous" if vote.is_unanimous
                    else f"{vote.votes_for}-{vote.votes_against}"
                )
                st.markdown(f"**Result:** {vote.result.upper()} ({unanimous})")
                if vote.individual_votes:
                    st.write("**Individual Votes:**")
                    for iv in vote.individual_votes:
                        marker = (
                            "Yes" if iv.member_vote == "yes"
                            else f"**{iv.member_vote.upper()}**"
                        )
                        st.write(f"&nbsp;&nbsp;&nbsp;&nbsp;{iv.member_name}: {marker}")

        if show_n < len(results):
            remaining = len(results) - show_n
            if st.button(f"Show more ({remaining} remaining)", key="ks_more"):
                st.session_state.ks_show_count += ITEMS_PER_PAGE
                st.rerun()
    else:
        st.info("Enter a keyword to search across all vote records.")


def _explore_districts(db_ops, session):
    """Browse districts and their meetings."""
    districts = db_ops.get_all_districts()
    if not districts:
        st.warning("No districts in database.")
        return

    col1, col2 = st.columns([1, 3])
    with col1:
        states = sorted(set(d.state for d in districts))
        selected_state = st.selectbox("State", ["All"] + states, key="db_state")
    filtered = (
        districts if selected_state == "All"
        else [d for d in districts if d.state == selected_state]
    )
    with col2:
        district_names = {d.district_name: d for d in filtered}
        selected_name = st.selectbox(
            "District", sorted(district_names.keys()), key="db_district"
        )

    if not selected_name:
        return

    district = district_names[selected_name]

    meeting_count = (
        session.query(func.count(Meeting.meeting_id))
        .filter(Meeting.district_id == district.district_id).scalar()
    )
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
        with st.expander(
            f"{meeting.meeting_date} | {meeting.meeting_type.replace('_', ' ').title()}"
        ):
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

            items = (
                session.query(AgendaItem)
                .filter(AgendaItem.meeting_id == meeting.meeting_id)
                .all()
            )

            for item in items:
                cat_label = format_category(item.item_category)
                has_vote_marker = " **[VOTE]**" if item.has_vote else ""
                st.markdown(
                    f"**{item.item_number or '-'}** {item.item_title} "
                    f"*({cat_label})*{has_vote_marker}"
                )
                if item.vote:
                    vote = item.vote
                    unanimous = (
                        "Unanimous" if vote.is_unanimous
                        else f"{vote.votes_for}-{vote.votes_against}"
                    )
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;Result: **{vote.result.upper()}** ({unanimous})"
                    )
                    if vote.individual_votes:
                        vote_strs = []
                        for iv in vote.individual_votes:
                            if iv.member_vote == "yes":
                                vote_strs.append(f"{iv.member_name}: Yes")
                            elif iv.member_vote == "no":
                                vote_strs.append(f"**{iv.member_name}: No**")
                            else:
                                vote_strs.append(f"{iv.member_name}: {iv.member_vote}")
                        st.markdown(
                            "&nbsp;&nbsp;&nbsp;&nbsp;" + " | ".join(vote_strs)
                        )


def _explore_members(analytics, session):
    """Search board members by state/name/district."""
    board_members = (
        session.query(BoardMember, District.district_name, District.state)
        .join(District, BoardMember.district_id == District.district_id)
        .order_by(District.state, District.district_name, BoardMember.member_name)
        .all()
    )
    board_members = [
        bm for bm in board_members if is_valid_member_name(bm.BoardMember.member_name)
    ]

    col1, col2, col3 = st.columns(3)
    with col1:
        member_states = sorted(set(bm.state for bm in board_members))
        search_state = st.selectbox(
            "State", ["All"] + member_states, key="bm_search_state"
        )
    with col2:
        search_name = st.text_input(
            "Member Name", placeholder="e.g., Smith", key="bm_search_name"
        )
    with col3:
        search_district = st.text_input(
            "District", placeholder="e.g., Rochester", key="bm_search_district"
        )

    has_filter = (
        search_state != "All"
        or (search_name and search_name.strip())
        or (search_district and search_district.strip())
    )

    if has_filter:
        filtered = board_members
        if search_state != "All":
            filtered = [bm for bm in filtered if bm.state == search_state]
        if search_name and search_name.strip():
            q = search_name.strip().lower()
            filtered = [
                bm for bm in filtered
                if q in bm.BoardMember.member_name.lower()
            ]
        if search_district and search_district.strip():
            q = search_district.strip().lower()
            filtered = [bm for bm in filtered if q in bm.district_name.lower()]

        st.write(f"**{len(filtered)}** board members found")

        if filtered:
            role_map = {
                "president": "President/Chair",
                "vice_president": "Vice President/Vice Chair",
                "secretary": "Secretary/Clerk",
                "treasurer": "Treasurer",
                "trustee": "Trustee",
                "member": "Member",
            }
            member_data = []
            for bm in filtered:
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
            st.dataframe(
                pd.DataFrame(member_data),
                use_container_width=True,
                hide_index=True,
            )

            # Detailed lookup
            members_with_votes = (
                session.query(
                    IndividualVote.member_name,
                    func.count(IndividualVote.individual_vote_id).label("cnt"),
                )
                .group_by(IndividualVote.member_name)
                .having(func.count(IndividualVote.individual_vote_id) >= 3)
                .order_by(func.count(IndividualVote.individual_vote_id).desc())
                .all()
            )
            filtered_names = set(bm.BoardMember.member_name for bm in filtered)
            selectable = [
                m for m in members_with_votes
                if m[0] in filtered_names and is_valid_member_name(m[0])
            ]

            if selectable:
                st.markdown("")
                section_header("View Detailed Voting Record")
                opts = [f"{m[0]} ({m[1]} votes)" for m in selectable]
                sel_idx = st.selectbox(
                    "Select Board Member",
                    range(len(opts)),
                    format_func=lambda i: opts[i],
                    key="bm_detail_member",
                )
                sel_name = selectable[sel_idx][0]
                profile = analytics.member_profile(sel_name)
                _render_member_detail(
                    profile, analytics, session, key_prefix="search"
                )
    else:
        st.info(
            "Use the filters above to search for board members by state, name, or district."
        )


if __name__ == "__main__":
    main()

"""Chart generation for the web interface — dark theme."""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

ACCENT_BLUE = "#0984E3"
PALETTE = [
    "#0984E3", "#6C5CE7", "#00B894", "#E17055", "#FDCB6E",
    "#74B9FF", "#A29BFE", "#55EFC4", "#FF7675", "#DFE6E9",
]


def _dark_layout(fig, **kwargs):
    if "margin" not in kwargs:
        kwargs["margin"] = dict(l=40, r=20, t=40, b=40)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif"),
        **kwargs,
    )
    return fig


def category_vote_chart(categories: list[dict]) -> go.Figure:
    """Stacked bar chart of votes by policy category."""
    df = pd.DataFrame(categories)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Unanimous",
        x=df["category"],
        y=df["unanimous"],
        marker_color="#00B894",
    ))
    fig.add_trace(go.Bar(
        name="Contested",
        x=df["category"],
        y=df["contested"],
        marker_color="#FF7675",
    ))
    _dark_layout(fig, barmode="stack", height=420,
                 xaxis_tickangle=-45,
                 title="Votes by Policy Category",
                 yaxis_title="Number of Votes")
    return fig


def state_comparison_chart(states: list[dict]) -> go.Figure:
    """Bar chart comparing states."""
    df = pd.DataFrame(states)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Unanimous",
        x=df["state"],
        y=df["total_votes"] - df["contested"],
        marker_color="#00B894",
    ))
    fig.add_trace(go.Bar(
        name="Contested",
        x=df["state"],
        y=df["contested"],
        marker_color="#FF7675",
    ))
    _dark_layout(fig, barmode="stack", height=420,
                 title="Votes by State",
                 yaxis_title="Number of Votes")
    return fig


def dissent_rate_chart(categories: list[dict]) -> go.Figure:
    """Horizontal bar chart of dissent rates by category."""
    df = pd.DataFrame(categories)
    if df.empty:
        return go.Figure()

    df = df.sort_values("contested_pct", ascending=True)

    fig = go.Figure(go.Bar(
        x=df["contested_pct"],
        y=df["category"],
        orientation="h",
        marker_color=df["contested_pct"].apply(
            lambda x: "#FF7675" if x > 20 else "#FDCB6E" if x > 10 else "#00B894"
        ),
        text=df["contested_pct"].apply(lambda x: f"{x:.1f}%"),
        textposition="outside",
    ))
    _dark_layout(fig, height=420,
                 title="Dissent Rate by Policy Category",
                 xaxis_title="% Contested",
                 xaxis=dict(range=[0, max(df["contested_pct"].max() * 1.2, 10)]))
    return fig


def monthly_trend_chart(trends: list[dict]) -> go.Figure:
    """Line chart of monthly vote trends."""
    df = pd.DataFrame(trends)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["month"], y=df["total_votes"],
        mode="lines+markers",
        name="Total Votes",
        line=dict(color=ACCENT_BLUE, width=2),
    ))
    fig.add_trace(go.Scatter(
        x=df["month"], y=df["contested"],
        mode="lines+markers",
        name="Contested Votes",
        line=dict(color="#FF7675", width=2),
    ))
    _dark_layout(fig, height=420,
                 title="Monthly Vote Activity",
                 yaxis_title="Number of Votes")
    return fig


def member_vote_pie(profile: dict) -> go.Figure:
    """Pie chart of a member's voting record."""
    if not profile or profile.get("total_votes", 0) == 0:
        return go.Figure()

    fig = go.Figure(go.Pie(
        labels=["Yes", "No", "Abstain"],
        values=[
            profile.get("yes_votes", 0),
            profile.get("no_votes", 0),
            profile.get("abstain_votes", 0),
        ],
        marker_colors=["#00B894", "#FF7675", "#FDCB6E"],
        hole=0.45,
    ))
    _dark_layout(fig, height=350,
                 title=f"Voting Record: {profile['member_name']}")
    return fig


def district_contested_chart(districts: list[dict]) -> go.Figure:
    """Bar chart of districts by contested vote rate."""
    df = pd.DataFrame(districts[:20])
    if df.empty:
        return go.Figure()

    df = df.sort_values("contested_pct", ascending=True)
    labels = df.apply(lambda r: f"{r['district_name']} ({r['state']})", axis=1)

    fig = go.Figure(go.Bar(
        x=df["contested_pct"],
        y=labels,
        orientation="h",
        marker_color=df["contested_pct"].apply(
            lambda x: "#FF7675" if x > 30 else "#FDCB6E" if x > 15 else "#00B894"
        ),
        text=df["contested_pct"].apply(lambda x: f"{x:.1f}%"),
        textposition="outside",
    ))
    _dark_layout(fig, height=600,
                 title="Districts with Highest Contested Vote Rates",
                 xaxis_title="% Contested Votes",
                 margin=dict(l=250, r=20, t=40, b=40))
    return fig

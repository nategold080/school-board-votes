"""Chart generation for the web interface."""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def category_vote_chart(categories: list[dict]) -> go.Figure:
    """Bar chart of votes by policy category."""
    df = pd.DataFrame(categories)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Unanimous",
        x=df["category"],
        y=df["unanimous"],
        marker_color="#2ecc71",
    ))
    fig.add_trace(go.Bar(
        name="Contested",
        x=df["category"],
        y=df["contested"],
        marker_color="#e74c3c",
    ))
    fig.update_layout(
        barmode="stack",
        title="Votes by Policy Category",
        xaxis_title="Category",
        yaxis_title="Number of Votes",
        xaxis_tickangle=-45,
        height=500,
        template="plotly_white",
    )
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
        marker_color="#2ecc71",
    ))
    fig.add_trace(go.Bar(
        name="Contested",
        x=df["state"],
        y=df["contested"],
        marker_color="#e74c3c",
    ))
    fig.update_layout(
        barmode="stack",
        title="Votes by State",
        xaxis_title="State",
        yaxis_title="Number of Votes",
        height=400,
        template="plotly_white",
    )
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
            lambda x: "#e74c3c" if x > 20 else "#f39c12" if x > 10 else "#2ecc71"
        ),
        text=df["contested_pct"].apply(lambda x: f"{x:.1f}%"),
        textposition="outside",
    ))
    fig.update_layout(
        title="Dissent Rate by Policy Category",
        xaxis_title="% of Votes That Are Contested",
        yaxis_title="",
        height=500,
        template="plotly_white",
        xaxis=dict(range=[0, max(df["contested_pct"].max() * 1.2, 10)]),
    )
    return fig


def monthly_trend_chart(trends: list[dict]) -> go.Figure:
    """Line chart of monthly vote trends."""
    df = pd.DataFrame(trends)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["month"],
        y=df["total_votes"],
        mode="lines+markers",
        name="Total Votes",
        line=dict(color="#3498db", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=df["month"],
        y=df["contested"],
        mode="lines+markers",
        name="Contested Votes",
        line=dict(color="#e74c3c", width=2),
    ))
    fig.update_layout(
        title="Monthly Vote Activity",
        xaxis_title="Month",
        yaxis_title="Number of Votes",
        height=400,
        template="plotly_white",
    )
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
        marker_colors=["#2ecc71", "#e74c3c", "#f39c12"],
        hole=0.4,
    ))
    fig.update_layout(
        title=f"Voting Record: {profile['member_name']}",
        height=350,
        template="plotly_white",
    )
    return fig


def district_contested_chart(districts: list[dict]) -> go.Figure:
    """Bar chart of districts by contested vote rate."""
    df = pd.DataFrame(districts[:20])  # Top 20
    if df.empty:
        return go.Figure()

    df = df.sort_values("contested_pct", ascending=True)
    labels = df.apply(lambda r: f"{r['district_name']} ({r['state']})", axis=1)

    fig = go.Figure(go.Bar(
        x=df["contested_pct"],
        y=labels,
        orientation="h",
        marker_color=df["contested_pct"].apply(
            lambda x: "#e74c3c" if x > 30 else "#f39c12" if x > 15 else "#2ecc71"
        ),
        text=df["contested_pct"].apply(lambda x: f"{x:.1f}%"),
        textposition="outside",
    ))
    fig.update_layout(
        title="Districts with Highest Contested Vote Rates",
        xaxis_title="% Contested Votes",
        height=600,
        template="plotly_white",
        margin=dict(l=250),
    )
    return fig

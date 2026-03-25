"""10 维雷达图组件 — Plotly go.Scatterpolar."""

import plotly.graph_objects as go

DIMENSION_LABELS = [
    "Audience",
    "Engagement",
    "Virality",
    "Posting",
    "Monetization",
    "Growth",
    "Circle Influence",
    "Char. Consistency",
    "Community",
    "Data Confidence",
]

DIMENSION_KEYS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    "circle_influence_score",
    "character_consistency",
    "community_score",
    "data_confidence",
]


def create_radar_chart(features: dict, title: str = "Creator Profile") -> go.Figure:
    """Create a 10-dimensional radar chart for a creator's feature scores.

    Args:
        features: dict with keys matching DIMENSION_KEYS, values 0-100
        title: chart title
    """
    values = [float(features.get(k, 0) or 0) for k in DIMENSION_KEYS]
    values.append(values[0])  # close the polygon
    labels = DIMENSION_LABELS + [DIMENSION_LABELS[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=labels,
        fill="toself",
        fillcolor="rgba(99, 110, 250, 0.2)",
        line=dict(color="rgb(99, 110, 250)", width=2),
        name=title,
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=10)),
            angularaxis=dict(tickfont=dict(size=11)),
        ),
        showlegend=False,
        title=dict(text=title, x=0.5),
        margin=dict(l=60, r=60, t=50, b=30),
        height=400,
    )

    return fig

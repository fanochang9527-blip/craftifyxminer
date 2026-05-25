"""9 维雷达图组件 — Plotly go.Scatterpolar。"""

from __future__ import annotations

import plotly.graph_objects as go

DEFAULT_DIMENSION_LABELS = [
    "Audience",
    "Engagement",
    "Virality",
    "Posting",
    "Monetization",
    "Growth",
    "Char. Consistency",
    "Community",
    "Audience Segment",
]

DIMENSION_KEYS = [
    "audience_score",
    "engagement_score",
    "virality_score",
    "posting_score",
    "monetization_score",
    "growth_score",
    "character_consistency",
    "community_score",
    "audience_segment_score",
]


def create_radar_chart(
    features: dict,
    title: str = "Creator Profile",
    labels: list[str] | None = None,
) -> go.Figure:
    """Create a 9-dimensional radar chart for a creator's feature scores.

    Args:
        features: dict with keys matching DIMENSION_KEYS, values 0-100
        title: chart title
        labels: optional 10 translated axis labels (same order as DIMENSION_KEYS)
    """
    dim_labels = labels if labels is not None and len(labels) == len(DIMENSION_KEYS) else DEFAULT_DIMENSION_LABELS

    values = [float(features.get(k, 0) or 0) for k in DIMENSION_KEYS]
    values.append(values[0])  # close the polygon
    theta_labels = dim_labels + [dim_labels[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=theta_labels,
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

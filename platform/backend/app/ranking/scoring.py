"""ranking_score: the single sortable number the daily Top N is ordered
by. Confidence-weighted probability is the primary driver; a positive
market edge adds a modest, confidence-gated boost.

    ranking_score = final_probability * confidence_score
                  + EDGE_BOOST_WEIGHT * max(edge, 0) * confidence_score

Edge is deliberately NOT the primary driver and never penalizes a
fixture when negative or absent (max(edge, 0)) — a large edge from a
low-confidence prediction is much more likely noise than signal (this is
exactly the platform's warning against calling something a "value bet"
solely because the model disagrees with the market), so the edge term is
itself gated by confidence_score rather than added unconditionally.
"""

from __future__ import annotations

EDGE_BOOST_WEIGHT = 0.5


def compute_ranking_score(*, final_probability: float, confidence_score: float, edge: float | None) -> float:
    base = final_probability * confidence_score
    edge_boost = EDGE_BOOST_WEIGHT * max(edge, 0.0) * confidence_score if edge is not None else 0.0
    return base + edge_boost

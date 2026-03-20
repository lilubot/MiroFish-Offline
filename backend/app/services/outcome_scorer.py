"""
Simulation outcome scoring primitives.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Tuple


@dataclass
class SimulationOutcome:
    """Core quantitative metrics describing a simulation run."""

    total_posts: int = 0
    total_engagement: int = 0
    average_post_reach: float = 0.0
    viral_posts_count: int = 0
    sentiment_standard_deviation: float = 0.0
    platform_distribution: Dict[str, float] = field(default_factory=dict)
    top_influencers: List[Tuple[str, float]] = field(default_factory=list)
    peak_activity_round: int = 0


class OutcomeScorer:
    """Compute additive core metrics from simulation post-like records."""

    def score_simulation(
        self,
        posts: List[Any],
        viral_threshold: int = 1000,
        influencer_limit: int = 5,
    ) -> SimulationOutcome:
        total_posts = len(posts)
        total_engagement = self._sum_engagement(posts)
        average_post_reach = self._compute_average_reach(posts)

        return SimulationOutcome(
            total_posts=total_posts,
            total_engagement=total_engagement,
            average_post_reach=average_post_reach,
            viral_posts_count=sum(
                1 for post in posts if self._engagement_value(post) >= viral_threshold
            ),
            sentiment_standard_deviation=self._compute_sentiment_standard_deviation(posts),
            platform_distribution=self._compute_platform_distribution(posts),
            top_influencers=self._find_top_influencers(posts, influencer_limit=influencer_limit),
            peak_activity_round=self._find_peak_activity_round(posts),
        )

    @staticmethod
    def _value(source: Any, key: str, default: Any = 0) -> Any:
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    def _engagement_value(self, post: Any) -> int:
        direct_value = self._value(post, "engagement", None)
        if direct_value is not None:
            return int(direct_value)

        components = (
            self._value(post, "likes", 0),
            self._value(post, "upvotes", 0),
            self._value(post, "comments", 0),
            self._value(post, "replies", 0),
            self._value(post, "shares", 0),
            self._value(post, "retweets", 0),
            self._value(post, "reposts", 0),
        )
        return int(sum(int(component or 0) for component in components))

    def _sum_engagement(self, posts: List[Any]) -> int:
        return sum(self._engagement_value(post) for post in posts)

    def _compute_average_reach(self, posts: List[Any]) -> float:
        if not posts:
            return 0.0

        total_reach = 0.0
        for post in posts:
            reach = self._value(post, "reach", None)
            if reach is None:
                reach = self._value(post, "impressions", self._engagement_value(post))
            total_reach += float(reach or 0.0)

        return total_reach / len(posts)

    def _compute_sentiment_standard_deviation(self, posts: List[Any]) -> float:
        sentiments = [
            float(self._value(post, "sentiment"))
            for post in posts
            if self._value(post, "sentiment", None) is not None
        ]
        if len(sentiments) < 2:
            return 0.0

        mean = sum(sentiments) / len(sentiments)
        variance = sum((value - mean) ** 2 for value in sentiments) / len(sentiments)
        return math.sqrt(variance)

    def _compute_platform_distribution(self, posts: List[Any]) -> Dict[str, float]:
        if not posts:
            return {}

        platform_counts = Counter(
            str(self._value(post, "platform", "unknown")).lower()
            for post in posts
        )
        total = sum(platform_counts.values())
        return {
            platform: count / total
            for platform, count in platform_counts.items()
        }

    def _find_top_influencers(
        self,
        posts: List[Any],
        influencer_limit: int = 5,
    ) -> List[Tuple[str, float]]:
        influence_scores: Dict[str, float] = defaultdict(float)

        for post in posts:
            author_name = self._value(post, "author_name", None)
            if author_name is None:
                author_name = self._value(post, "agent_name", self._value(post, "author_id", "unknown"))
            influence_scores[str(author_name)] += float(self._engagement_value(post))

        ranked = sorted(
            influence_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        return ranked[:influencer_limit]

    def _find_peak_activity_round(self, posts: List[Any]) -> int:
        if not posts:
            return 0

        rounds = Counter(int(self._value(post, "created_round", 0) or 0) for post in posts)
        peak_round, _ = max(rounds.items(), key=lambda item: (item[1], -item[0]))
        return peak_round

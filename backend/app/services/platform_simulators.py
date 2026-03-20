"""
Platform-specific simulation scoring helpers.
"""

from abc import ABC, abstractmethod
from typing import Any


class PlatformSimulator(ABC):
    """Base scoring interface for platform-specific feed behavior."""

    platform_name = "generic"

    @abstractmethod
    def score_post_visibility(self, post: Any, agent: Any, round_num: int) -> float:
        """Return a normalized visibility score for a candidate post."""

    @abstractmethod
    def compute_engagement_multiplier(self, post: Any, round_num: int) -> float:
        """Return a platform-shaped engagement multiplier for a post."""

    @staticmethod
    def _value(source: Any, key: str, default: float = 0.0) -> float:
        if isinstance(source, dict):
            value = source.get(key, default)
        else:
            value = getattr(source, key, default)

        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, value))


class TwitterSimulator(PlatformSimulator):
    """Twitter/X-like behavior: fast decay, strong engagement amplification."""

    platform_name = "twitter"

    def score_post_visibility(self, post: Any, agent: Any, round_num: int) -> float:
        created_round = self._value(post, "created_round", round_num)
        likes = self._value(post, "likes")
        reposts = self._value(post, "retweets", self._value(post, "reposts"))
        replies = self._value(post, "comments", self._value(post, "replies"))
        follower_count = self._value(
            agent,
            "followers",
            self._value(agent, "follower_count", self._value(agent, "influence_weight")),
        )

        age_penalty = max(0.1, 1.0 - max(0.0, round_num - created_round) * 0.12)
        engagement_boost = min(2.5, 1.0 + (likes + reposts + replies) * 0.015)
        follower_boost = min(2.0, 1.0 + follower_count * 0.0002)

        raw_score = age_penalty * engagement_boost * follower_boost
        return self._clamp(raw_score / 3.5)

    def compute_engagement_multiplier(self, post: Any, round_num: int) -> float:
        del round_num
        sentiment = abs(self._value(post, "sentiment"))
        controversy = self._value(post, "controversy", sentiment)
        return max(0.75, 1.0 + (sentiment * 0.35) + (controversy * 0.25))


class RedditSimulator(PlatformSimulator):
    """Reddit-like behavior: slower decay, quality and community weighting."""

    platform_name = "reddit"

    def score_post_visibility(self, post: Any, agent: Any, round_num: int) -> float:
        del agent
        created_round = self._value(post, "created_round", round_num)
        upvotes = self._value(post, "upvotes", self._value(post, "likes"))
        comments = self._value(post, "comments")
        upvote_ratio = self._value(post, "upvote_ratio", 0.75)
        subreddit_size = self._value(post, "subreddit_subscribers", self._value(post, "community_size"))

        age_penalty = max(0.2, 1.0 - max(0.0, round_num - created_round) * 0.04)
        quality_boost = min(2.0, (max(upvote_ratio, 0.1) ** 1.25) + (upvotes * 0.002))
        discussion_boost = min(1.5, 1.0 + comments * 0.01)
        community_boost = min(1.5, 1.0 + subreddit_size / 1000000.0)

        raw_score = age_penalty * quality_boost * discussion_boost * community_boost
        return self._clamp(raw_score / 4.5)

    def compute_engagement_multiplier(self, post: Any, round_num: int) -> float:
        created_round = self._value(post, "created_round", round_num)
        age = max(0.0, round_num - created_round)
        discussion_depth = self._value(post, "comments")
        durability = max(0.7, 1.1 - age * 0.02)
        return max(0.65, durability + min(0.4, discussion_depth * 0.01))

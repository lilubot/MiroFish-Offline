"""
Executive Summary Generator

Generates a structured executive summary from a completed simulation report.
Saves both machine-readable JSON and human-readable Markdown formats.

Usage:
    generator = ExecutiveSummaryGenerator(llm_client, simulation_data)
    summary = generator.generate(full_report_path)
    generator.save(summary, output_dir)
"""

import os
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any
from datetime import datetime

from ..utils.logger import get_logger

logger = get_logger('mirofish.executive_summary')

# ─── Prompt ───────────────────────────────────────────────────────────────────

EXECUTIVE_SUMMARY_SYSTEM_PROMPT = """\
You are an expert analyst extracting a structured executive summary from a simulation report.

CRITICAL LANGUAGE REQUIREMENT: You MUST respond ENTIRELY in English.
Do NOT use Chinese, Japanese, Korean, or any non-English language anywhere in your output.
Output ONLY valid JSON — no prose, no markdown, no code fences.
"""

EXECUTIVE_SUMMARY_USER_PROMPT_TEMPLATE = """\
Given the following simulation report, extract a structured executive summary as JSON.

--- REPORT START ---
{report_excerpt}
--- REPORT END ---

Extract the following fields and return ONLY valid JSON (no other text):
{{
    "viral_outcome": "<1 sentence describing how the story spread>",
    "dominant_platform": "<which platform had most activity and why>",
    "backlash_pattern": "<1 sentence describing sentiment arc>",
    "risk_level": "<HIGH|MEDIUM|LOW>",
    "risk_summary": "<2-3 sentences on key risks identified>",
    "narrative_shift": <float -1.0 to 1.0>,
    "polarization_score": <float 0.0 to 1.0>,
    "consensus_reached": <true|false>,
    "winning_narrative": "<which framing won, or null if none>",
    "top_supporters": ["<name1>", "<name2>"],
    "top_critics": ["<name1>", "<name2>"],
    "key_neutral_voices": ["<name1>"],
    "key_events": [{{"round": <int>, "event": "<description>"}}],
    "twitter_sentiment": <float -1.0 to 1.0>,
    "reddit_sentiment": <float -1.0 to 1.0>,
    "strategic_recommendations": ["<rec1>", "<rec2>", "<rec3>"]
}}

Rules:
- All string values must be in English
- numeric fields must be actual numbers (not strings)
- Output ONLY the JSON object — no explanation, no markdown, no code fences
"""

# ─── Dataclass ────────────────────────────────────────────────────────────────

@dataclass
class ExecutiveSummary:
    """Structured executive summary for a simulation report."""

    simulation_id: str
    report_id: str
    generated_at: str

    # Outcome
    viral_outcome: str = ""
    dominant_platform: str = ""
    backlash_pattern: str = ""
    risk_level: str = "MEDIUM"
    risk_summary: str = ""

    # Narrative metrics
    narrative_shift: float = 0.0
    polarization_score: float = 0.0
    consensus_reached: bool = False
    winning_narrative: Optional[str] = None

    # Key actors
    top_supporters: List[str] = field(default_factory=list)
    top_critics: List[str] = field(default_factory=list)
    key_neutral_voices: List[str] = field(default_factory=list)

    # Timeline
    key_events: List[dict] = field(default_factory=list)

    # Platform sentiment
    twitter_sentiment: float = 0.0
    reddit_sentiment: float = 0.0

    # Recommendations
    strategic_recommendations: List[str] = field(default_factory=list)


# ─── Generator ────────────────────────────────────────────────────────────────

class ExecutiveSummaryGenerator:
    """Generates a structured executive summary from simulation data and a full report."""

    # Maximum characters from report to include in the LLM prompt
    REPORT_EXCERPT_CHARS = 8000

    def __init__(self, llm_client: Any, simulation_data: dict):
        """
        Args:
            llm_client: An LLMClient instance (must expose .chat() and/or .chat_json())
            simulation_data: Dict containing at least 'simulation_id' and 'report_id'
        """
        self.llm = llm_client
        self.sim_data = simulation_data

    def generate(self, full_report_path: str) -> ExecutiveSummary:
        """
        Generate an ExecutiveSummary from the full report markdown file.

        Args:
            full_report_path: Absolute path to full_report.md

        Returns:
            ExecutiveSummary dataclass populated with extracted values
        """
        if not os.path.exists(full_report_path):
            raise FileNotFoundError(f"Report file not found: {full_report_path}")

        with open(full_report_path, 'r', encoding='utf-8', errors='replace') as f:
            full_report = f.read()

        # Truncate to avoid excessive token usage
        report_excerpt = full_report[:self.REPORT_EXCERPT_CHARS]
        if len(full_report) > self.REPORT_EXCERPT_CHARS:
            report_excerpt += "\n\n... [report truncated for summary extraction] ..."

        logger.info(f"Generating executive summary for report: {full_report_path}")

        prompt = EXECUTIVE_SUMMARY_USER_PROMPT_TEMPLATE.format(report_excerpt=report_excerpt)

        # Prefer chat_json if available, fall back to chat + manual parse
        summary_data: dict = {}
        try:
            if hasattr(self.llm, 'chat_json'):
                summary_data = self.llm.chat_json(
                    messages=[
                        {"role": "system", "content": EXECUTIVE_SUMMARY_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
            else:
                raw = self.llm.chat(
                    messages=[
                        {"role": "system", "content": EXECUTIVE_SUMMARY_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                # Strip possible markdown code fences
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```", 2)[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.rsplit("```", 1)[0]
                summary_data = json.loads(raw.strip())
        except Exception as e:
            logger.error(f"Executive summary LLM extraction failed: {e}")
            summary_data = {}

        # Build the dataclass — use defaults for any missing/malformed fields
        summary = ExecutiveSummary(
            simulation_id=self.sim_data.get('simulation_id', ''),
            report_id=self.sim_data.get('report_id', ''),
            generated_at=datetime.now().isoformat(),
            viral_outcome=str(summary_data.get('viral_outcome', '')),
            dominant_platform=str(summary_data.get('dominant_platform', '')),
            backlash_pattern=str(summary_data.get('backlash_pattern', '')),
            risk_level=str(summary_data.get('risk_level', 'MEDIUM')).upper(),
            risk_summary=str(summary_data.get('risk_summary', '')),
            narrative_shift=self._safe_float(summary_data.get('narrative_shift', 0.0)),
            polarization_score=self._safe_float(summary_data.get('polarization_score', 0.0)),
            consensus_reached=bool(summary_data.get('consensus_reached', False)),
            winning_narrative=summary_data.get('winning_narrative'),
            top_supporters=self._safe_list(summary_data.get('top_supporters', [])),
            top_critics=self._safe_list(summary_data.get('top_critics', [])),
            key_neutral_voices=self._safe_list(summary_data.get('key_neutral_voices', [])),
            key_events=self._safe_events(summary_data.get('key_events', [])),
            twitter_sentiment=self._safe_float(summary_data.get('twitter_sentiment', 0.0)),
            reddit_sentiment=self._safe_float(summary_data.get('reddit_sentiment', 0.0)),
            strategic_recommendations=self._safe_list(summary_data.get('strategic_recommendations', [])),
        )

        logger.info(
            f"Executive summary generated: risk={summary.risk_level}, "
            f"polarization={summary.polarization_score:.2f}, "
            f"consensus={summary.consensus_reached}"
        )
        return summary

    def save(self, summary: ExecutiveSummary, output_dir: str):
        """
        Save the executive summary as both JSON and Markdown.

        Args:
            summary: ExecutiveSummary dataclass
            output_dir: Directory to write files into (created if absent)

        Returns:
            Tuple[str, str]: (json_path, md_path)
        """
        os.makedirs(output_dir, exist_ok=True)

        # JSON — machine-readable
        json_path = os.path.join(output_dir, 'executive_summary.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(summary), f, indent=2, ensure_ascii=False)

        # Markdown — human-readable card
        md_path = os.path.join(output_dir, 'executive_summary.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(self._render_markdown(summary))

        logger.info(f"Executive summary saved: {json_path}, {md_path}")
        return json_path, md_path

    # ─── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    @staticmethod
    def _safe_events(value: Any) -> List[dict]:
        if not isinstance(value, list):
            return []
        cleaned = []
        for item in value:
            if isinstance(item, dict):
                cleaned.append({
                    "round": int(item.get("round", 0)),
                    "event": str(item.get("event", "")),
                })
        return cleaned

    @staticmethod
    def _render_markdown(summary: ExecutiveSummary) -> str:
        """Render the executive summary as a clean Markdown card."""
        risk_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(summary.risk_level, "⚪")

        supporters_str = ", ".join(summary.top_supporters) if summary.top_supporters else "—"
        critics_str = ", ".join(summary.top_critics) if summary.top_critics else "—"
        neutrals_str = ", ".join(summary.key_neutral_voices) if summary.key_neutral_voices else "—"

        events_lines = "\n".join(
            f"- **Round {e['round']}:** {e['event']}" for e in summary.key_events
        ) if summary.key_events else "- No key events recorded"

        recommendations_lines = "\n".join(
            f"{i + 1}. {r}" for i, r in enumerate(summary.strategic_recommendations)
        ) if summary.strategic_recommendations else "1. No recommendations available"

        return f"""\
# Executive Summary — Simulation {summary.simulation_id}
*Report ID: {summary.report_id}*  
*Generated: {summary.generated_at}*

---

## 📊 Outcome

**{summary.viral_outcome}**

| Metric | Value |
|--------|-------|
| Dominant Platform | {summary.dominant_platform} |
| Backlash Pattern | {summary.backlash_pattern} |
| Risk Level | {risk_emoji} {summary.risk_level} |
| Narrative Shift | {summary.narrative_shift:+.2f} |
| Polarization Score | {summary.polarization_score:.2f} |
| Consensus Reached | {"Yes" if summary.consensus_reached else "No"} |
| Winning Narrative | {summary.winning_narrative or "None — ongoing fracture"} |
| Twitter Sentiment | {summary.twitter_sentiment:+.2f} |
| Reddit Sentiment | {summary.reddit_sentiment:+.2f} |

---

## 🎭 Key Actors

**Top Supporters:** {supporters_str}  
**Top Critics:** {critics_str}  
**Key Neutrals:** {neutrals_str}

---

## ⚠️ Risk Assessment

{risk_emoji} **{summary.risk_level}**

{summary.risk_summary}

---

## 📅 Key Timeline Events

{events_lines}

---

## 💡 Strategic Recommendations

{recommendations_lines}
"""

"""Main extraction pipeline using OpenAI API."""

import json
import logging
import time
from typing import Optional
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import OPENAI_API_KEY, STAGE1_MODEL, STAGE2_MODEL, MAX_RETRIES
from .prompts import (
    STAGE1_SYSTEM_PROMPT, STAGE1_USER_PROMPT,
    STAGE2_SYSTEM_PROMPT, STAGE2_USER_PROMPT,
    FULL_EXTRACTION_PROMPT
)
from .schemas import MeetingExtractionData, VoteData, AgendaItemData
from .validator import validate_extraction, validate_vote

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Two-stage LLM extraction pipeline for meeting minutes."""

    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.extraction_count = 0
        self.failure_count = 0

    def _call_llm(self, system_prompt: str, user_prompt: str,
                  model: str, max_tokens: int = 4096) -> Optional[dict]:
        """Call the OpenAI API and parse JSON response."""
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            # Track usage
            usage = response.usage
            self.total_input_tokens += usage.prompt_tokens
            self.total_output_tokens += usage.completion_tokens
            self._update_cost(model, usage.prompt_tokens, usage.completion_tokens)

            content = response.choices[0].message.content
            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            # Try to extract JSON from the response
            return self._extract_json(content)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None

    def _extract_json(self, text: str) -> Optional[dict]:
        """Try to extract JSON from text that may have extra content."""
        import re
        # Try to find JSON block in markdown
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try finding the outermost braces
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _update_cost(self, model: str, input_tokens: int, output_tokens: int):
        """Estimate API cost."""
        # Approximate pricing
        if "gpt-4o-mini" in model:
            cost = (input_tokens * 0.15 + output_tokens * 0.6) / 1_000_000
        elif "gpt-4o" in model:
            cost = (input_tokens * 2.5 + output_tokens * 10.0) / 1_000_000
        else:
            cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
        self.total_cost += cost

    def extract_meeting_two_stage(self, minutes_text: str,
                                   district_id: str = "") -> Optional[MeetingExtractionData]:
        """Run two-stage extraction on meeting minutes."""
        if not minutes_text or len(minutes_text.strip()) < 100:
            logger.warning(f"Minutes text too short for extraction ({len(minutes_text)} chars)")
            return None

        # Truncate very long minutes to stay within token limits
        max_chars = 60000  # ~15k tokens
        if len(minutes_text) > max_chars:
            minutes_text = minutes_text[:max_chars] + "\n\n[... text truncated ...]"

        # Stage 1: Classification & Segmentation
        logger.info(f"Stage 1: Classifying meeting ({len(minutes_text)} chars)")
        stage1_result = self._run_stage1(minutes_text)

        if not stage1_result:
            logger.warning("Stage 1 failed, attempting full extraction fallback")
            return self._full_extraction_fallback(minutes_text)

        # Stage 2: Deep extraction for items with votes
        agenda_items = []
        vote_items = [item for item in stage1_result.get("agenda_items", [])
                      if item.get("has_vote", False)]

        logger.info(f"Stage 2: Extracting {len(vote_items)} vote items")

        for item in stage1_result.get("agenda_items", []):
            if item.get("has_vote", False):
                vote_data = self._run_stage2(
                    minutes_text, item,
                    stage1_result.get("members_present", [])
                )
                agenda_items.append(AgendaItemData(
                    item_number=item.get("item_number"),
                    item_title=item.get("item_title", "Untitled"),
                    item_description=item.get("brief_description"),
                    item_category=vote_data.get("item_category", "other") if vote_data else "other",
                    has_vote=True,
                    vote=VoteData(**{k: v for k, v in vote_data.items()
                                     if k != "item_category"}) if vote_data else None,
                ))
            else:
                agenda_items.append(AgendaItemData(
                    item_number=item.get("item_number"),
                    item_title=item.get("item_title", "Untitled"),
                    item_description=item.get("brief_description"),
                    item_category="other",
                    has_vote=False,
                ))

        self.extraction_count += 1

        return MeetingExtractionData(
            meeting_type=stage1_result.get("meeting_type", "regular"),
            members_present=stage1_result.get("members_present", []),
            members_absent=stage1_result.get("members_absent", []),
            agenda_items=agenda_items,
            extraction_confidence=stage1_result.get("confidence", "medium"),
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    def _run_stage1(self, minutes_text: str) -> Optional[dict]:
        """Run Stage 1: Classification & Segmentation."""
        prompt = STAGE1_USER_PROMPT.format(minutes_text=minutes_text)
        result = self._call_llm(STAGE1_SYSTEM_PROMPT, prompt, STAGE1_MODEL, max_tokens=4096)
        if result and "agenda_items" in result:
            return result
        return None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=15))
    def _run_stage2(self, minutes_text: str, item: dict,
                    members_present: list) -> Optional[dict]:
        """Run Stage 2: Deep vote extraction for a single item."""
        prompt = STAGE2_USER_PROMPT.format(
            item_title=item.get("item_title", ""),
            item_number=item.get("item_number", "N/A"),
            item_description=item.get("brief_description", ""),
            members_present=", ".join(members_present),
            minutes_text=minutes_text,
        )
        result = self._call_llm(STAGE2_SYSTEM_PROMPT, prompt, STAGE2_MODEL, max_tokens=2048)

        if result:
            # Validate and clean the vote data
            result = validate_vote(result)
        return result

    def _full_extraction_fallback(self, minutes_text: str) -> Optional[MeetingExtractionData]:
        """Fallback: single-pass full extraction."""
        prompt = FULL_EXTRACTION_PROMPT.format(minutes_text=minutes_text)
        result = self._call_llm(STAGE2_SYSTEM_PROMPT, prompt, STAGE2_MODEL, max_tokens=8192)

        if not result:
            self.failure_count += 1
            return None

        try:
            validated = validate_extraction(result)
            self.extraction_count += 1
            return validated
        except Exception as e:
            logger.error(f"Validation failed for fallback extraction: {e}")
            self.failure_count += 1
            return None

    def get_stats(self) -> dict:
        """Get extraction statistics."""
        return {
            "total_extractions": self.extraction_count,
            "total_failures": self.failure_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost": round(self.total_cost, 4),
        }

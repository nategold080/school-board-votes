"""Rule-based extraction engine for school board meeting minutes.

This is the core extraction system. It uses pattern matching and keyword
classification to extract structured vote data from BoardDocs agendas
without any LLM calls. The LLM is only used for:
1. Initial calibration (validating rules against a few samples)
2. Edge cases that the rule engine can't handle confidently

Design principles:
- Marginal cost per new document ≈ 0 (no API calls)
- Works across all BoardDocs districts (same platform → same structure)
- Handles format variations through layered pattern matching
- Confidence scoring drives selective LLM fallback
"""

import re
import logging
from datetime import date
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Category classification rules
# ============================================================================

CATEGORY_RULES = {
    "consent_agenda": [
        r"consent\s+(agenda|calendar|items?)",
        r"approve\s+consent",
        r"approval\s+of\s+consent",
    ],
    "personnel": [
        r"personnel",
        r"human\s+(capital|resources)",
        r"staff(ing)?",
        r"hiring|termination|resignation|retirement",
        r"superintendent.*contract",
        r"employ(ment|ee)",
        r"certificated|classified\s+personnel",
    ],
    "budget_finance": [
        r"budget",
        r"financ(e|ial)",
        r"expenditure|appropriat",
        r"audit",
        r"bond",
        r"tax\s+(levy|rate|budget)",
        r"revenue",
        r"award\s+of\s+(contract|purchase|bid)",
        r"payment\s+for.*services",
        r"warrant|voucher",
        r"fiscal",
    ],
    "curriculum_instruction": [
        r"curriculum",
        r"instruction(al)?",
        r"textbook|adopt.*text",
        r"program\s+approv",
        r"academic\s+standard",
        r"student\s+achievement",
        r"educational?\s+(affairs|items?)",
        r"education\s+items?",
        r"assessment",
        r"grading",
    ],
    "facilities": [
        r"facilit(y|ies)",
        r"construct(ion)?",
        r"renovation",
        r"capital\s+project",
        r"building",
        r"lease\s+payment",
        r"property",
        r"maintenance",
        r"hvac|roofing|plumbing",
    ],
    "policy": [
        r"board\s+polic(y|ies)",
        r"policy\s+\d+",
        r"governance",
        r"bylaw",
        r"first\s+reading|second\s+reading",
        r"policy\s+(revis|adopt|amend)",
    ],
    "student_affairs": [
        r"student\s+(affairs|disciplin|program|activities)",
        r"attendance",
        r"extracurricular",
        r"athletics",
        r"student\s+code",
        r"graduation",
    ],
    "community_relations": [
        r"public\s+(comment|hearing|forum|participation)",
        r"community\s+(relation|partner|engagement)",
        r"speaker",
        r"communication",
    ],
    "technology": [
        r"technolog(y|ical)",
        r"\bIT\b\s+(contract|purchase|service)",
        r"digital",
        r"software|hardware",
        r"network|infrastructure",
        r"cyber",
    ],
    "safety_security": [
        r"safety|security",
        r"emergency\s+(plan|preparedness)",
        r"school\s+resource\s+officer|SRO",
        r"threat\s+assessment",
        r"bullying|harassment",
    ],
    "dei_equity": [
        r"diversity|equity|inclusion|\bDEI\b",
        r"equity\s+committee",
        r"anti.?rac",
        r"cultural\s+responsiv",
        r"title\s+IX",
    ],
    "special_education": [
        r"special\s+education|\bSPED\b|\bIEP\b",
        r"section\s+504",
        r"related\s+services",
        r"exceptional\s+(student|learner)",
        r"disabilit",
    ],
}

# Items that typically involve a formal vote
VOTE_LIKELY_PATTERNS = [
    r"consent\s+(agenda|calendar|items?)",
    r"approve\s+consent",
    r"approv(e|al)\s+of\s+(agenda|minutes|budget|contract|policy|resolution)",
    r"action\s+(on|items?)",
    r"adopt(ion)?\s+(of|resolution)",
    r"award\s+of\s+(contract|purchase|bid)",
    r"accept(ance)?\s+of\s+minutes",
    r"minutes\s+of\s+previous",
    r"first\s+reading|second\s+reading",
    r"roll\s+call\s+vote",
    r"resolution",
    r"ratif(y|ication)",
    r"authorization",
    r"personnel\s+(change|action|affair)",
    r"human\s+(capital|resource)\s+items?",
    r"education\s+items?",
    r"payment\s+for\s+.*services",
    r"new\s+business.*vote",
    r"discussion.action\s+items?",
    r"board\s+polic(y|ies)",
    r"superintendent.*evaluation",
    r"consideration\s+of\s+(accounts?|resolution)",
    r"financial\s+affairs?",
    r"capital\s+projects?",
    r"non.?public\s+school",
    r"professional\s+development",
    r"lease\s+payment",
    r"unfinished\s+business",
]

# Items that almost never have votes
NO_VOTE_PATTERNS = [
    r"call\s+to\s+order",
    r"pledge\s+of\s+allegiance",
    r"moment\s+of\s+silence",
    r"adjournment?",
    r"adjourn",
    r"recess",
    r"public\s+(comment|hearing|forum|participation)",
    r"superintendent.s?\s+(report|update)",
    r"president.s?\s+(report|remarks)",
    r"board\s+(report|member\s+report)",
    r"committee\s+report",
    r"presentation",
    r"recognition",
    r"acknowledge",
    r"student\s+representative",
    r"hearing\s+the\s+public",
    r"executive\s+session",
    r"closed\s+session",
    r"information\s+(only|item)",
    r"discussion\s+(only|item)",
    r"opening\s+of\s+meeting",
    r"welcome",
    r"invocation",
    r"correspondence",
    r"comments?\s+from\s+speaker",
]


@dataclass
class ExtractedItem:
    """A single extracted agenda item."""
    item_number: str = ""
    item_title: str = ""
    item_description: str = ""
    item_category: str = "other"
    has_vote: bool = False
    vote_type: str = "voice"
    result: str = "passed"
    is_unanimous: bool = True
    confidence: str = "medium"
    motion_text: str = ""
    votes_for: Optional[int] = None
    votes_against: Optional[int] = None
    individual_votes: list = field(default_factory=list)


@dataclass
class ExtractedMeeting:
    """Full extraction result for a meeting."""
    district_name: str = ""
    meeting_date: Optional[date] = None
    meeting_type: str = "regular"
    members_present: list = field(default_factory=list)
    members_absent: list = field(default_factory=list)
    agenda_items: list = field(default_factory=list)
    extraction_confidence: str = "medium"
    extraction_method: str = "rule_engine"  # rule_engine, llm, hybrid


class RuleBasedExtractor:
    """Extracts structured vote data using pattern matching.

    No LLM calls. Near-zero marginal cost per document.
    """

    def __init__(self):
        self._compile_patterns()
        self.extraction_count = 0
        self.total_items = 0
        self.total_votes = 0

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance."""
        self.category_patterns = {}
        for cat, patterns in CATEGORY_RULES.items():
            self.category_patterns[cat] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self.vote_likely = [re.compile(p, re.IGNORECASE) for p in VOTE_LIKELY_PATTERNS]
        self.no_vote = [re.compile(p, re.IGNORECASE) for p in NO_VOTE_PATTERNS]

    def extract(self, raw_text: str) -> ExtractedMeeting:
        """Extract structured data from raw meeting text."""
        meeting = ExtractedMeeting()

        # Parse metadata header
        self._extract_metadata(raw_text, meeting)

        # Extract agenda sections
        sections = self._extract_sections(raw_text)

        # Classify and analyze each section
        for section in sections:
            item = self._process_section(section)
            if item.item_title:  # Skip empty items
                meeting.agenda_items.append(item)
                self.total_items += 1
                if item.has_vote:
                    self.total_votes += 1

        # Extract any member names from the text
        self._extract_members(raw_text, meeting)

        # Infer meeting-level confidence
        if meeting.agenda_items:
            high_conf = sum(1 for i in meeting.agenda_items if i.confidence == "high")
            meeting.extraction_confidence = (
                "high" if high_conf > len(meeting.agenda_items) * 0.5
                else "medium" if high_conf > 0
                else "low"
            )

        self.extraction_count += 1
        return meeting

    def _extract_metadata(self, text: str, meeting: ExtractedMeeting):
        """Extract meeting metadata from header lines."""
        lines = text.split('\n')[:10]

        for line in lines:
            line = line.strip()
            if line.startswith("District:"):
                meeting.district_name = line.replace("District:", "").strip()
            elif line.startswith("Date:"):
                date_str = line.replace("Date:", "").strip()
                try:
                    parts = date_str.split("-")
                    meeting.meeting_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                except (ValueError, IndexError):
                    pass
            elif line.startswith("Meeting:"):
                name = line.replace("Meeting:", "").strip().lower()
                if "special" in name:
                    meeting.meeting_type = "special"
                elif "work" in name or "workshop" in name or "retreat" in name:
                    meeting.meeting_type = "work_session"
                elif "emergency" in name:
                    meeting.meeting_type = "emergency"
                else:
                    meeting.meeting_type = "regular"

    def _extract_sections(self, text: str) -> list[dict]:
        """Extract agenda sections from the text."""
        sections = []

        # Pattern: === SECTION HEADER ===
        pattern = r'===\s*(.+?)\s*==='
        matches = list(re.finditer(pattern, text))

        for i, match in enumerate(matches):
            header = match.group(1).strip()
            # Get text until next section
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()

            # Extract item number from header (e.g., "1.Call to Order" -> "1", "Call to Order")
            num_match = re.match(r'^(\d+(?:\.[A-Z]\b)?)\.\s*(.+)', header)
            if num_match:
                item_number = num_match.group(1)
                item_title = num_match.group(2)
            else:
                item_number = ""
                item_title = header

            sections.append({
                "number": item_number,
                "title": item_title,
                "body": body,
                "full_header": header,
            })

        # If no === sections found, try other patterns
        if not sections:
            sections = self._extract_sections_fallback(text)

        return sections

    def _extract_sections_fallback(self, text: str) -> list[dict]:
        """Fallback section extraction for non-standard formats."""
        sections = []
        # Try numbered items: "1. Item Title" or "A. Item Title"
        pattern = r'^(\d+|[A-Z])\.?\s+([A-Z][^\n]{5,})'
        for match in re.finditer(pattern, text, re.MULTILINE):
            sections.append({
                "number": match.group(1),
                "title": match.group(2).strip(),
                "body": "",
                "full_header": match.group(0),
            })
        return sections

    def _process_section(self, section: dict) -> ExtractedItem:
        """Classify a section and determine if it has a vote."""
        item = ExtractedItem()
        item.item_number = section["number"]
        item.item_title = section["title"]

        title_and_body = f"{section['title']} {section['body']}"

        # Classify category
        item.item_category = self._classify_category(title_and_body)

        # Determine vote likelihood
        item.has_vote, vote_confidence = self._assess_vote_likelihood(title_and_body)

        if item.has_vote:
            # Extract vote details from body text
            self._extract_vote_details(section["body"], title_and_body, item)
            item.confidence = vote_confidence

        return item

    def _classify_category(self, text: str) -> str:
        """Classify text into a policy category using keyword patterns."""
        scores = {}
        for cat, patterns in self.category_patterns.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                scores[cat] = score

        if scores:
            return max(scores, key=scores.get)
        return "other"

    def _assess_vote_likelihood(self, text: str) -> tuple[bool, str]:
        """Determine if an item likely has a vote.

        Returns (has_vote, confidence).
        """
        # Check for explicit no-vote indicators
        for pattern in self.no_vote:
            if pattern.search(text):
                return False, "high"

        # Check for explicit vote indicators
        vote_score = sum(1 for p in self.vote_likely if p.search(text))

        # Check for explicit vote language in body
        explicit_vote = bool(re.search(
            r'motion\s+(carried|passed|failed|approved|defeated)|'
            r'roll\s+call\s+vote|'
            r'vote:\s*\d|'
            r'approved?\s+\d+-\d+|'
            r'unanimously\s+approved|'
            r'carried\s+unanimously|'
            r'motion\s+by\s+\w+',
            text, re.IGNORECASE
        ))

        if explicit_vote:
            return True, "high"
        elif vote_score >= 2:
            return True, "medium"
        elif vote_score == 1:
            return True, "low"
        else:
            return False, "medium"

    def _extract_vote_details(self, body: str, full_text: str, item: ExtractedItem):
        """Extract vote details from the text."""
        text = full_text

        # Default: inferred vote
        item.vote_type = "voice"
        item.result = "passed"
        item.is_unanimous = True
        item.motion_text = f"Motion to approve {item.item_title}"

        # Check for explicit roll call
        if re.search(r'roll\s+call', text, re.IGNORECASE):
            item.vote_type = "roll_call"

        # Check for unanimous consent language
        if re.search(r'unanimou|by\s+general\s+consent|no\s+objection', text, re.IGNORECASE):
            item.vote_type = "unanimous_consent"
            item.is_unanimous = True

        # Check for specific vote counts (e.g., "5-2", "approved 7-0")
        count_match = re.search(r'(\d+)\s*[-–]\s*(\d+)(?:\s*[-–]\s*(\d+))?', text)
        if count_match:
            item.votes_for = int(count_match.group(1))
            item.votes_against = int(count_match.group(2))
            if count_match.group(3):
                item.votes_abstain = int(count_match.group(3))
            item.is_unanimous = item.votes_against == 0

        # Check for failure
        if re.search(r'fail(ed)?|defeat(ed)?|denied|not\s+approv', text, re.IGNORECASE):
            item.result = "failed"
            item.is_unanimous = False

        # Check for tabling
        if re.search(r'table[d]?\b|postpone[d]?|defer(red)?', text, re.IGNORECASE):
            item.result = "tabled"

        # Extract motion maker
        maker_match = re.search(r'motion\s+(?:made\s+)?by\s+(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?(\w+)', text, re.IGNORECASE)
        if maker_match:
            item.motion_text = f"Motion by {maker_match.group(1)}"

        # Extract seconder
        second_match = re.search(r'second(?:ed)?\s+by\s+(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?(\w+)', text, re.IGNORECASE)
        if second_match:
            item.motion_text += f", seconded by {second_match.group(1)}"

        # Extract individual votes from roll call
        individual_pattern = r'(?:Mr|Ms|Mrs|Dr)\.?\s+(\w+)\s*[-–:]\s*(yes|no|aye|nay|yea|abstain|absent)'
        for match in re.finditer(individual_pattern, text, re.IGNORECASE):
            name = match.group(1)
            vote = match.group(2).lower()
            if vote in ("aye", "yea"):
                vote = "yes"
            elif vote == "nay":
                vote = "no"
            item.individual_votes.append({"member_name": name, "member_vote": vote})

        if item.individual_votes:
            item.vote_type = "roll_call"
            item.votes_for = sum(1 for v in item.individual_votes if v["member_vote"] == "yes")
            item.votes_against = sum(1 for v in item.individual_votes if v["member_vote"] == "no")
            item.is_unanimous = item.votes_against == 0
            item.confidence = "high"

    def _extract_members(self, text: str, meeting: ExtractedMeeting):
        """Try to extract board member names from the text."""
        # Look for "Members Present:" or "Present:" patterns
        present_match = re.search(
            r'(?:members?\s+)?present\s*[:\-]\s*(.+?)(?:\n\n|\n[A-Z]|absent)',
            text, re.IGNORECASE | re.DOTALL
        )
        if present_match:
            names_text = present_match.group(1)
            # Split by commas, semicolons, or newlines
            names = re.split(r'[,;\n]', names_text)
            meeting.members_present = [n.strip() for n in names if n.strip() and len(n.strip()) > 2]

        absent_match = re.search(
            r'(?:members?\s+)?absent\s*[:\-]\s*(.+?)(?:\n\n|\n[A-Z])',
            text, re.IGNORECASE | re.DOTALL
        )
        if absent_match:
            names_text = absent_match.group(1)
            names = re.split(r'[,;\n]', names_text)
            meeting.members_absent = [n.strip() for n in names if n.strip() and len(n.strip()) > 2]

    def get_stats(self) -> dict:
        return {
            "extractions": self.extraction_count,
            "total_items": self.total_items,
            "total_votes": self.total_votes,
            "method": "rule_engine",
            "api_cost": 0.0,
        }


class HybridExtractor:
    """Combines rule-based extraction with selective LLM enhancement.

    Architecture:
    1. Rule engine processes ALL documents (free, fast)
    2. LLM is called ONLY for low-confidence extractions (expensive, slow)
    3. LLM results are used to improve rule engine patterns over time

    This makes the system:
    - Scalable: O(1) cost per document for most documents
    - Accurate: LLM handles edge cases
    - Improving: Each LLM call potentially improves the rules
    """

    def __init__(self, llm_extractor=None, confidence_threshold="low"):
        self.rule_engine = RuleBasedExtractor()
        self.llm_extractor = llm_extractor  # Optional LLM fallback
        self.confidence_threshold = confidence_threshold
        self.llm_calls = 0
        self.rule_only = 0

    def extract(self, raw_text: str, district_id: str = "") -> ExtractedMeeting:
        """Extract using rules first, LLM only if needed."""
        # Step 1: Rule-based extraction
        meeting = self.rule_engine.extract(raw_text)

        # Step 2: Check if LLM enhancement is needed
        needs_llm = self._needs_llm_enhancement(meeting)

        if needs_llm and self.llm_extractor:
            # Only send to LLM if we have low confidence
            try:
                llm_result = self.llm_extractor.extract_meeting_two_stage(raw_text, district_id)
                if llm_result:
                    meeting = self._merge_results(meeting, llm_result)
                    meeting.extraction_method = "hybrid"
                    self.llm_calls += 1
            except Exception as e:
                logger.warning(f"LLM enhancement failed: {e}")
        else:
            self.rule_only += 1

        return meeting

    def _needs_llm_enhancement(self, meeting: ExtractedMeeting) -> bool:
        """Determine if a meeting extraction needs LLM enhancement."""
        if self.confidence_threshold == "none":
            return False

        if not meeting.agenda_items:
            return True

        low_conf = sum(1 for i in meeting.agenda_items if i.confidence == "low" and i.has_vote)
        total_votes = sum(1 for i in meeting.agenda_items if i.has_vote)

        if total_votes == 0:
            return True  # No votes detected — might be a format we don't understand

        # If more than half of votes are low confidence, use LLM
        if self.confidence_threshold == "low":
            return low_conf > total_votes * 0.5
        elif self.confidence_threshold == "medium":
            med_or_low = sum(1 for i in meeting.agenda_items
                           if i.confidence in ("low", "medium") and i.has_vote)
            return med_or_low > total_votes * 0.5

        return False

    def _merge_results(self, rule_result: ExtractedMeeting,
                       llm_result) -> ExtractedMeeting:
        """Merge rule-based and LLM results, preferring higher-confidence data."""
        # Use LLM members if rule engine didn't find any
        if not rule_result.members_present and llm_result.members_present:
            rule_result.members_present = llm_result.members_present
            rule_result.members_absent = llm_result.members_absent

        # For each LLM agenda item, try to match with rule result
        # and upgrade confidence
        for llm_item in llm_result.agenda_items:
            matched = False
            for rule_item in rule_result.agenda_items:
                if self._items_match(rule_item, llm_item):
                    # Upgrade with LLM data
                    if llm_item.has_vote and llm_item.vote:
                        rule_item.has_vote = True
                        rule_item.vote_type = llm_item.vote.vote_type
                        rule_item.result = llm_item.vote.result
                        rule_item.is_unanimous = llm_item.vote.is_unanimous
                        rule_item.votes_for = llm_item.vote.votes_for
                        rule_item.votes_against = llm_item.vote.votes_against
                        if llm_item.vote.individual_votes:
                            rule_item.individual_votes = [
                                {"member_name": iv.member_name, "member_vote": iv.member_vote}
                                for iv in llm_item.vote.individual_votes
                            ]
                        rule_item.confidence = "high"
                        rule_item.motion_text = llm_item.vote.motion_text or rule_item.motion_text
                    if llm_item.item_category != "other":
                        rule_item.item_category = llm_item.item_category
                    matched = True
                    break

            if not matched and llm_item.has_vote:
                # LLM found a vote we missed — add it
                rule_result.agenda_items.append(ExtractedItem(
                    item_number=llm_item.item_number or "",
                    item_title=llm_item.item_title,
                    item_description=llm_item.item_description or "",
                    item_category=llm_item.item_category,
                    has_vote=True,
                    confidence="medium",
                ))

        return rule_result

    @staticmethod
    def _items_match(rule_item: ExtractedItem, llm_item) -> bool:
        """Check if two items refer to the same agenda item."""
        # Match by item number
        if rule_item.item_number and llm_item.item_number:
            r_num = rule_item.item_number.strip().rstrip('.')
            l_num = (llm_item.item_number or "").strip().rstrip('.')
            if r_num == l_num:
                return True

        # Match by title similarity
        r_title = rule_item.item_title.lower().strip()
        l_title = (llm_item.item_title or "").lower().strip()
        if r_title and l_title:
            # Check if one title contains the other
            if r_title in l_title or l_title in r_title:
                return True
            # Check word overlap
            r_words = set(r_title.split())
            l_words = set(l_title.split())
            overlap = len(r_words & l_words)
            if overlap >= min(len(r_words), len(l_words)) * 0.5:
                return True

        return False

    def get_stats(self) -> dict:
        rule_stats = self.rule_engine.get_stats()
        return {
            **rule_stats,
            "llm_calls": self.llm_calls,
            "rule_only": self.rule_only,
            "llm_rate": self.llm_calls / max(1, self.llm_calls + self.rule_only),
        }

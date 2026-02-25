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
from pathlib import Path
from typing import Optional

import yaml

from database.operations import normalize_member_name as _normalize_member_name

logger = logging.getLogger(__name__)

# Load extraction config from YAML
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "extraction_config.yaml"
try:
    with open(_CONFIG_PATH, "r") as _f:
        EXTRACTION_CONFIG = yaml.safe_load(_f)
except (FileNotFoundError, yaml.YAMLError) as _e:
    logger.warning(f"Could not load extraction config from {_CONFIG_PATH}: {_e}. Using defaults.")
    EXTRACTION_CONFIG = {}

NON_VOTE_TITLES = EXTRACTION_CONFIG.get("non_vote_titles", [
    "MEETING OPENING", "CALL TO ORDER", "PLEDGE OF ALLEGIANCE",
    "MOMENT OF SILENCE", "ADJOURNMENT", "RECESS", "INVOCATION",
])


# ============================================================================
# Category classification rules
# ============================================================================

CATEGORY_RULES = {
    "consent_agenda": [
        r"consent\s+(agenda|calendar|items?)",
        r"approve\s+consent",
        r"approval\s+of\s+consent",
        r"^consent$",
        r"consent\s+general",
        r"consent\s+vote",
        r"items?\s+of\s+consent",
    ],
    "personnel": [
        r"personnel",
        r"human\s+(capital|resources?)",
        r"staff(ing)?",
        r"hiring|termination|resignation|retirement",
        r"superintendent.*contract",
        r"employ(ment|ee)",
        r"certificated|classified\s+personnel",
        r"coach(es|ing)?\s+approv",
        r"volunteer\s+approv",
        r"substitute\s+(teacher|list)",
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
        r"purchase\s+order",
        r"donation|gift",
        r"fund\s+(transfer|balance)",
        r"contract\s+(approv|renew|award)",
        r"change\s+order",
        r"accounts?\s+payable",
        r"insurance",
        r"fee\s+(schedule|increase|waiver)",
        r"consideration\s+of\s+accounts?",
        r"referendum",
        r"paid\s+bills",
        r"bids?\s*,?\s*contracts?\s*,?\s*agreements?",
        r"(?:action\s+(?:only\s+)?[-–]?\s*)?(?:bids?|agreements?)\b",
        r"sponsor\s+event",
        r"authorize\s+.*(?:contract|agreement|payment)",
        r"bank\s+balance",
        r"collateral\s+reconciliation",
        r"cash\s+summary",
        r"vendor\s+contract",
        r"release\s+of\s+funds",
        r"claim\s+settlement",
        r"authorize\s+additional\s+pay",
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
        r"field\s+trip",
        r"professional\s+development",
        r"training",
        r"school\s+improvement\s+plan",
        r"gifted|talented|enrichment",
        r"educational\s+services?",
        r"^education$",
        r"summer\s+school",
        r"educational\s+tour",
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
        r"naming\s+(of\s+)?facilit",
        r"use\s+of\s+facilit",
        r"architect|engineering\s+service",
    ],
    "policy": [
        r"board\s+polic(y|ies)",
        r"^polic(y|ies)$",
        r"policy\s+\d+",
        r"governance",
        r"bylaw",
        r"first\s+reading|second\s+reading",
        r"policy\s+(revis|adopt|amend)",
        r"regulation\s+\d+",
        r"policy\s+(review|update|revision|manual)",
        r"administrative\s+regulation",
        r"^policy\s+items?$",
        r"policy\s+level\s+issues?",
        r"resolutions?\s+for\s+consideration",
    ],
    "student_affairs": [
        r"student\s+(affairs|disciplin|program|activities)",
        r"attendance",
        r"extracurricular",
        r"athletics",
        r"student\s+code",
        r"graduation|commencement",
        r"school\s+calendar",
        r"student\s+handbook",
        r"dress\s+code",
        r"transportation",
        r"student\s+services?",
        r"field\s+trip",
        r"coach(es|ing)?\b",
        r"basketball|football|soccer|baseball|volleyball|tennis|swim|track|cheer|wrestling|sport",
        r"nutrition|food\s+service|school\s+lunch|meal\s+program",
        r"youth\s+report",
        r"student\s+(?:school\s+)?board\s+representative",
        r"scholar\s+report",
        r"disciplin\w*\s+(?:of\s+)?(?:a\s+)?(?:particular|student)",
        r"expuls",
        r"individual\s+plan\s+of\s+study",
        r"student\s+delegates?",
    ],
    "community_relations": [
        r"public\s+(comment|hearing|forum|participation|input)",
        r"community\s+(relation|partner|engagement|comment)",
        r"speaker",
        r"communication",
        r"citizen.?s?\s+(?:comment|time|input)",
        r"open\s+forum",
        r"hearing\s+(from|of)\s+(the\s+)?(public|visitor|those\s+present)",
        r"call\s+to\s+the\s+public",
        r"comments?\s+from\s+(the\s+)?(public|visitor|speaker|those)",
        r"response.*from\s+those\s+present",
        r"citizens?\s+(?:and\s+)?groups?\s+address",
        r"audience\s+participation",
        r"^hearings?$",
        r"walk.?ins?",
        r"visitor.?s?\s+comments?",
        r"requests?\s+to\s+address\s+the\s+board",
        r"hearing\s+on\s+polic",
        r"recognitions?\b|awards?\b|honors?\b",
        r"community\s+comments?",
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
        r"equity\s+(?:&|and)\s+(?:culture|CRE)",
        r"celebrating\s+(?:identity|diversity)",
        r"equity\s+(?:update|report|plan|audit|resolution)",
        r"equity\s+leaders?",
        r"racial\s+equity",
        r"social\s+justice",
        r"multicultural",
    ],
    "special_education": [
        r"special\s+education|\bSPED\b|\bIEP\b",
        r"section\s+504",
        r"related\s+services",
        r"exceptional\s+(student|learner)",
        r"disabilit",
    ],
    "procedural": [
        r"approv(e|al)\s+of\s+(the\s+)?(agenda|minutes|previous)",
        r"accept(ance)?\s+of\s+(agenda|minutes)",
        r"adopt(ion)?\s+of\s+(the\s+)?(agenda|minutes)",
        r"approve\s+agenda",
        r"review\s+(and\s+)?(adopt|approve)\s+(agenda|minutes)",
        r"call\s+to\s+order",
        r"pledge\s+of\s+allegiance",
        r"roll\s+call",
        r"action\s+on\s+minutes",
        r"return\s+to\s+open\s+meeting",
        r"approve\s+as\s+presented",
        r"final\s+resolution:\s+motion",
        r"board\s+member\s+vote",
        r"secretary\s+pro\s+tem",
        r"appointment\s+of\s+secretary",
        r"agenda\s+was\s+(adopted|approved)",
        r"^approval$",
        r"^addendum$",
        r"moment\s+of\s+silence",
        r"adjournment?",
        r"adjourn",
        r"recess",
        r"opening\s+of\s+meeting",
        r"welcome\b",
        r"invocation",
        r"flag\s+salute",
        r"executive\s+session",
        r"closed\s+(session|meeting)",
        r"return\s+to\s+open\s+session",
        r"reconvene",
        r"open\s+session",
        r"meeting\s+opening",
        r"opening\s+items?",
        r"^opening$",
        r"meeting\s+closing",
        r"closing\s+items?",
        r"^closing$",
        r"minutes\s+of\s+previous",
        r"review\s+agenda",
        r"disclosures?\s+and\s+abstention",
        r"items?\s+for\s+board\s+action",
        r"superintendent\s+withdraws",
        r"chairman\s+adds\s+items",
        r"adjustments?\s+to\s+the\s+agenda",
        r"items?\s+pulled",
        r"upcoming\s+dates?",
        r"^agenda$",
        r"order\s+of\s+business",
        r"regular\s+(session|board\s+meeting)",
        r"land\s+acknowledg",
        r"^business$",
        r"agenda\s+approv",
        r"wrap.?up\s+items?",
        r"upcoming\s+meeting\s+dates?",
        r"meeting\s+dates?\s+for",
        r"^meeting\s+dates?$",
        r"sunshine\s+act",
        r"closing\s+procedures?",
        r"^procedural\s+items?$",
        r"^closing$",
        r"^minutes$",
        r"adjorn",
        r"\d+:\d+\s*(AM|PM)\s+board\s+meeting",
        r"evening\s+session",
        r"additions?\s+.*to\s+(the\s+)?agenda",
        r"modifications?\s+to\s+(the\s+)?agenda",
        r"removals?\s+.*agenda",
        r"agenda\s+modifications?",
        r"approv(e|al)\s+of\s+(the\s+)?proposed\s+agenda",
        r"^preliminaries$",
        r"organizational\s+items?",
        r"^meeting\s+schedule$",
        r"schedule\s+of\s+future\s+board",
        r"part\s+(i|ii|iii|iv|v)\b",
        r"enter\s+(?:public|open)\s+meeting",
        r"regular\s+meeting\s+(?:minutes|called)",
        r"^special\s+meeting$",
        r"nominations?\s+for\s+board\s+(?:president|vice|secretary|officer)",
        r"election\s+of\s+board\s+(?:president|vice|secretary|officer)",
        r"accept\s+and\s+adopt",
        r"adopt\s+(?:the\s+)?(?:agenda|resolution|proposed)",
        r"adopt\s+(?:the\s+)?proposed\s+changes",
        r"a\s+motion\s+to\s+approve\s+the\s+(?:agenda|minutes)",
        r"resolution\s*(?:#|no\.?|:)?\s*(?:\d|approv)",
        r"approve\s+(?:the\s+)?(?:agenda|minutes|meeting)",
        r"mission\s+statement",
        r"audio\s+files?\b",
    ],
    "admin_operations": [
        r"action\s+items?",
        r"action\s+agenda",
        r"unfinished\s+business",
        r"new\s+business",
        r"old\s+business",
        r"other\s+business",
        r"superintendent.?s?\s+(report|update|recommendation|comment)",
        r"superintendent\s+comment",
        r"board\s+(report|member\s+report|briefing)",
        r"board\s+(comment|discussion|member\s+comment)",
        r"committee\s+report",
        r"correspondence",
        r"information\s+item",
        r"discussion\s+item",
        r"board\s+calendar",
        r"board\s+self.?evaluation",
        r"annual\s+(report|review)",
        r"organizational\s+meeting",
        r"election\s+of\s+officers",
        r"recogniti",
        r"presentation",
        r"announcement",
        r"future\s+(agenda|meeting|business)\s+item",
        r"future\s+(meetings?|business)",
        r"for\s+discussion",
        r"workshop\b",
        r"^information$",
        r"^discussion$",
        r"^action$",
        r"board\s+of\s+education",
        r"cabinet\s+update",
        r"(?:chief\s+exec|CEO).?s?\s+(report|update)",
        r"verbal\s+report",
        r"good\s+news",
        r"spotlight",
        r"monitoring\s+item",
        r"superintendent.?s?\s+closing",
        r"board.?(admin|affairs|matters|member\s+matters)",
        r"school\s+board\s+member\s+matters",
        r"comments?\s+from\s+the\s+(audience|floor)",
        r"open\s+to\s+the\s+public",
        r"acknowledge?ment",
        r"request\s+to\s+address",
        r"president.?s?\s+report",
        r"informational\s+agenda",
        r"discussion\s+agenda",
        r"^work\s+session$",
        r"treasurer.?s?\s+report",
        r"reports?\s+to\s+the\s+board",
        r"administrative\s+reports?",
        r"written\s+reports?",
        r"monthly\s+reports?",
        r"informational\s+items?",
        r"general\s+(information|business)",
        r"business\s+services?",
        r"freedom\s+of\s+information",
        r"miscellaneous",
        r"any\s+other\s+matters?",
        r"for\s+action",
        r"administrative\s+items?",
        r"^updates?$",
        r"reports?\s+from\s+the\s+department",
        r"board\s+business",
        r"general\s+counsel",
        r"student\s+board\s+member",
        r"^other\s+reports?",
        r"solicitor.?s?\s+report",
        r"items?\s+for\s+future\s+agenda",
        r"board\s+concerns?",
        r"board\s+work",
        r"advisory\s+council",
        r"comments?\s+by\s+the\s+board",
        r"business\s+report",
        r"report\s+of\s+the\s+superintendent",
        r"teaching\s+and\s+learning",
        r"student\s+government",
        r"student\s+representative",
        r"student\s+trustee",
        r"scholar\s+board\s+member",
        r"student\s+board\s+representative",
        r"head\s+start",
        r"bargaining\s+unit",
        r"open\s+to\s+the\s+board",
        r"board\s+of\s+trustees?\s+report",
        r"^disclosures?$",
        r"open\s+time",
        r"^planning$",
        r"deputy\s+superintendent",
        r"student.?s?\s+report",
        r"food\s+service",
        r"agenda\s+plan",
        r"information/discussion",
        r"non.?consent",
        r"for\s+information\b",
        r"committee\s+meeting\s+report",
        r"reports?\s+.*by\s+.*board",
        r"attorney.?s?\s+report",
        r"legal\s+issues?",
        r"board\s+meeting\s+survey",
        r"board\s+member\s+items?",
        r"matters?\s+reserved",
        r"review\s+board\s+goals?",
        r"action\s*[-–]\s*(general|business)",
        r"pledge\s+leader",
        r"national\s+anthem",
        r"legislation\b",
        r"liaison\s+reports?",
        r"external\s+reports?",
        r"special\s+reports?",
        r"discussion/action",
        r"^comments?\s*$",
        r"comments?\s+by\s+the\s+(?:treasurer|superintendent)",
        r"items?\s+for\s+distribution",
        r"district\s+updates?",
        r"superinten\w+\s+(?:remarks?|business|closing|update|report)",
        r"next\s+meeting.?s?\s+topics?",
        r"board\s+round\s*table",
        r"agenda\s+preview",
        r"look\s+around\s+the\s+district",
        r"resolutions?\s+(?:added|supporting)",
        r"academics?\s+resolutions?",
        r"abstracts?\b",
        r"board\s+member\s+resolution",
        r"information\s+only\s+reports?",
        r"rpm\s+update",
        r"^regular\s+agenda$",
        r"division\s+recommendations?\s*[-–]?\s*resolutions?",
        r"board\s+consensus",
        r"(?:work\s+session|resolutions?\s+corrected)\s*[-–]?\s*resolutions?",
        r"^[A-Z]\.?\s*Resolutions?$",
        r"^resolutions?$",
        r"authorizations?\b",
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
    motion_maker: str = ""
    motion_seconder: str = ""
    votes_for: Optional[int] = None
    votes_against: Optional[int] = None
    votes_abstain: Optional[int] = None
    individual_votes: list = field(default_factory=list)


@dataclass
class ExtractedMeeting:
    """Full extraction result for a meeting."""
    district_name: str = ""
    meeting_date: Optional[date] = None
    meeting_type: str = "regular"
    members_present: list = field(default_factory=list)
    members_absent: list = field(default_factory=list)
    member_roles: dict = field(default_factory=dict)  # name -> role
    agenda_items: list = field(default_factory=list)
    extraction_confidence: str = "medium"
    extraction_method: str = "rule_engine"  # rule_engine, llm, hybrid


class RuleBasedExtractor:
    """Extracts structured vote data using pattern matching.

    No LLM calls. Near-zero marginal cost per document.
    """

    # Non-name words that can follow "Motion by" — must not be extracted as person names
    MOTION_MAKER_BLOCKLIST = {
        "exception", "consent", "resolution", "acclamation", "roll call",
        "voice vote", "board", "committee", "staff", "administration",
        "roll", "voice", "unanimous",
    }

    # Navigation / UI words that should not be treated as agenda item titles
    NAV_WORD_BLOCKLIST = {
        "previous", "next", "back", "forward", "home", "menu",
        "print", "close", "search", "login", "logout",
    }

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

        # Extract vote data from minutes text (higher quality than agenda)
        self._extract_minutes_sections(raw_text, meeting)

        # Extract any member names from the text
        self._extract_members(raw_text, meeting)

        # Post-processing: normalize member names for consistent matching
        meeting.members_present = list(dict.fromkeys(
            self.normalize_member_name(n) for n in meeting.members_present
            if self.normalize_member_name(n)
        ))
        meeting.members_absent = list(dict.fromkeys(
            self.normalize_member_name(n) for n in meeting.members_absent
            if self.normalize_member_name(n)
        ))
        # Rebuild member_roles with normalized keys
        if meeting.member_roles:
            normalized_roles = {}
            for name, role in meeting.member_roles.items():
                norm = self.normalize_member_name(name)
                if norm:
                    normalized_roles[norm] = role
            meeting.member_roles = normalized_roles

        for item in meeting.agenda_items:
            if item.motion_maker:
                item.motion_maker = self.normalize_member_name(item.motion_maker)
            if item.motion_seconder:
                item.motion_seconder = self.normalize_member_name(item.motion_seconder)
            for iv in item.individual_votes:
                iv["member_name"] = self.normalize_member_name(iv["member_name"])

        # === Post-processing Pass 1: Dedup and strip non-vote items ===
        # Must run before vote recalculation
        # NON_VOTE_TITLES loaded from config/extraction_config.yaml at module level
        for item in meeting.agenda_items:
            # Deduplicate individual votes (safety net for overlapping text regions)
            if item.individual_votes:
                item.individual_votes = self._deduplicate_votes(item.individual_votes)
            # P2: Strip vote records from non-vote procedural items
            title_upper = (item.item_title or "").strip().upper()
            if any(blocked in title_upper for blocked in NON_VOTE_TITLES):
                item.has_vote = False
                item.individual_votes = []
                item.votes_for = None
                item.votes_against = None
                item.votes_abstain = None

        # === Post-processing Pass 2: Recalculate counts and validate ===
        for item in meeting.agenda_items:
            # Recalculate from individual votes (P3, P4)
            if item.individual_votes:
                yes_count = sum(1 for v in item.individual_votes if v["member_vote"] == "yes")
                no_count = sum(1 for v in item.individual_votes if v["member_vote"] == "no")
                abstain_count = sum(1 for v in item.individual_votes if v["member_vote"] == "abstain")
                item.votes_for = yes_count
                item.votes_against = no_count
                item.votes_abstain = abstain_count
                # P4: Abstentions are not opposition — unanimous when no one voted "no"
                item.is_unanimous = no_count == 0
                item.vote_type = "roll_call"
                item.has_vote = True
            elif item.has_vote:
                # P3: 0-0 non-unanimous with no individual votes — extraction failure
                if (item.votes_for or 0) == 0 and (item.votes_against or 0) == 0:
                    if not item.is_unanimous:
                        item.has_vote = False
                # P4: For items without individual votes, track unanimity via votes_against
                if item.has_vote and item.votes_against is not None:
                    item.is_unanimous = item.votes_against == 0

            # P1: Validate consent agenda — reject impossible 0-for counts
            if item.has_vote and item.item_category == "consent_agenda":
                if (item.votes_for or 0) == 0 and (item.votes_against or 0) > 0:
                    item.votes_for = None
                    item.votes_against = None
                    item.votes_abstain = None
                    item.confidence = "low"
            # General: 0-for with many against is extremely suspicious
            if item.has_vote and (item.votes_for or 0) == 0 and (item.votes_against or 0) > 3:
                item.votes_for = None
                item.votes_against = None
                item.votes_abstain = None
                item.confidence = "low"

            # Validate result against vote counts
            if item.votes_for is not None and item.votes_against is not None:
                if item.votes_against > item.votes_for and item.result == "passed":
                    item.result = "failed"
                if item.votes_for > item.votes_against and item.result == "failed":
                    logger.warning(f"Contradictory result: {item.votes_for}-{item.votes_against} marked 'failed', overriding to 'passed'")
                    item.result = "passed"

        # === Post-processing Pass 3: Confidence scoring ===
        for item in meeting.agenda_items:
            # Strong evidence: 3+ individual votes → high
            if len(item.individual_votes) >= 3:
                item.confidence = "high"
            elif len(item.individual_votes) >= 2 and item.confidence == "low":
                item.confidence = "medium"
            # P7: Promote low-confidence items with partial evidence to medium
            elif item.confidence == "low" and item.has_vote:
                if item.motion_maker and item.motion_seconder:
                    item.confidence = "medium"
                elif 1 <= len(item.individual_votes) <= 2:
                    item.confidence = "medium"
                elif item.result in ("passed", "failed", "tabled") and item.vote_type != "roll_call":
                    title_and_desc = (item.item_title or "") + " " + (item.item_description or "")
                    if re.search(r'motion\s+(carried|passed|failed|approved|defeated)|'
                                 r'approved|carried|defeated|denied|tabled',
                                 title_and_desc, re.IGNORECASE):
                        item.confidence = "medium"
                elif item.item_category in ("personnel", "budget_finance", "consent_agenda"):
                    item.confidence = "medium"

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

    def _extract_minutes_sections(self, raw_text: str, meeting: ExtractedMeeting):
        """Parse MINUTES TEXT section for vote records using minutes-specific patterns.

        Minutes typically contain roll call votes, attendance, motion makers,
        and individual member votes in formats different from agenda items.
        Minutes data overrides agenda data when available (higher confidence).
        """
        # Find MINUTES TEXT section
        minutes_start = raw_text.find("MINUTES TEXT:")
        if minutes_start == -1:
            minutes_start = raw_text.find("MINUTES AJAX:")
        if minutes_start == -1:
            return

        minutes_text = raw_text[minutes_start:]

        # Extract attendance from minutes
        present_match = re.search(
            r'(?:Members?\s+)?(?:Present|PRESENT)\s*[:\-]\s*(.+?)(?:\n\n|\n(?:Members?\s+)?(?:Absent|ABSENT)|\n[A-Z]{2,})',
            minutes_text, re.DOTALL
        )
        if present_match:
            names_text = present_match.group(1)
            for name in re.split(r'[,;\n]', names_text):
                name = name.strip()
                if name and len(name) > 2 and name.lower() not in ("none", "n/a"):
                    clean = self._clean_member_name(name)
                    if clean and self._is_valid_member_name(clean) and clean not in meeting.members_present:
                        meeting.members_present.append(clean)

        absent_match = re.search(
            r'(?:Members?\s+)?(?:Absent|ABSENT)\s*[:\-]\s*(.+?)(?:\n\n|\n[A-Z]{2,})',
            minutes_text, re.DOTALL
        )
        if absent_match:
            names_text = absent_match.group(1)
            for name in re.split(r'[,;\n]', names_text):
                name = name.strip()
                if name and len(name) > 2 and name.lower() not in ("none", "n/a"):
                    clean = self._clean_member_name(name)
                    if clean and self._is_valid_member_name(clean) and clean not in meeting.members_absent:
                        meeting.members_absent.append(clean)

        # Build index of existing agenda items by title for merging
        existing_titles = {}
        for item in meeting.agenda_items:
            existing_titles[item.item_title.lower().strip()] = item

        # Extract vote blocks from minutes text
        # Pattern: "Motion by Name, seconded by Name" followed by vote result
        vote_blocks = list(re.finditer(
            r'(?:Motion|MOTION)\s+(?:made\s+)?by\s+'
            r'(?:(?:Mr|Ms|Mrs|Dr|Trustee|Member)\.?\s+)?([A-Za-z][A-Za-z\s\'""\'-]+?)'
            r',?\s*(?:second(?:ed)?|SECOND(?:ED)?)\s+by\s*,?\s*'
            r'(?:(?:Mr|Ms|Mrs|Dr|Trustee|Member)\.?\s+)?([A-Za-z][A-Za-z\s\'""\'-]+?)'
            r'\s*[.,:;]',
            minutes_text, re.IGNORECASE
        ))

        for i, block_match in enumerate(vote_blocks):
            motion_maker = block_match.group(1).strip()
            motion_seconder = block_match.group(2).strip()
            # Reject non-name words extracted as motion makers
            if motion_maker.lower() in self.MOTION_MAKER_BLOCKLIST:
                motion_maker = ""
            if motion_seconder.lower() in self.MOTION_MAKER_BLOCKLIST:
                motion_seconder = ""
            block_start = block_match.start()
            # Bound context by adjacent vote blocks to prevent cross-contamination
            prev_bound = vote_blocks[i - 1].end() if i > 0 else 0
            next_bound = vote_blocks[i + 1].start() if i + 1 < len(vote_blocks) else len(minutes_text)
            context_before = minutes_text[max(prev_bound, block_start - 300):block_start]
            context_after = minutes_text[block_match.end():min(next_bound, block_match.end() + 500)]
            full_context = context_before + minutes_text[block_start:block_match.end()] + context_after

            # Try to find the item title from context before the motion
            item_title = ""
            # Look for a header-like line before the motion
            title_lines = [l.strip() for l in context_before.split('\n') if l.strip()]
            for tl in reversed(title_lines):
                # Skip short lines or lines that are clearly vote text
                if (len(tl) > 5 and len(tl) < 200
                        and not re.match(r'^\s*(RESULT|MOVER|SECONDER|AYES|NAYS|Motion)', tl, re.IGNORECASE)):
                    item_title = tl[:120]
                    break

            # Parse vote result from context after
            result = "passed"
            is_unanimous = True
            votes_for = None
            votes_against = None
            votes_abstain = None

            result_match = re.search(
                r'(?:Motion|MOTION)\s+(?:carried|passed|CARRIED|PASSED)\s*(?:(\d+)\s*[-–]\s*(\d+)(?:\s*[-–]\s*(\d+))?)?',
                full_context, re.IGNORECASE
            )
            if result_match:
                result = "passed"
                if result_match.group(1):
                    votes_for = int(result_match.group(1))
                    votes_against = int(result_match.group(2))
                    if result_match.group(3):
                        votes_abstain = int(result_match.group(3))
                    is_unanimous = votes_against == 0
            elif re.search(r'(?:Motion|MOTION)\s+(?:failed|defeated|FAILED|DEFEATED)', full_context, re.IGNORECASE):
                result = "failed"
                is_unanimous = False
            elif re.search(r'(?:carried|passed)\s+unanimously', full_context, re.IGNORECASE):
                result = "passed"
                is_unanimous = True

            # Parse individual votes from roll call
            individual_votes = []

            # Format: "Roll Call: Mr. Name - Yes, Ms. Name - No"
            roll_call_match = re.search(
                r'(?:Roll\s+Call|ROLL\s+CALL)\s*:\s*(.+?)(?:\n\n|\n(?:Motion|MOTION|[A-Z]{2,}\s))',
                full_context, re.DOTALL | re.IGNORECASE
            )
            if roll_call_match:
                rc_text = roll_call_match.group(1)
                for vm in re.finditer(
                    r'(?:Mr|Ms|Mrs|Dr)\.?\s+([A-Za-z\'-]+)\s*[-–:]\s*(Yes|No|Aye|Nay|Yea|Abstain|Absent)',
                    rc_text, re.IGNORECASE
                ):
                    name = vm.group(1).strip()
                    vote = vm.group(2).lower()
                    if vote in ("aye", "yea"):
                        vote = "yes"
                    elif vote == "nay":
                        vote = "no"
                    individual_votes.append({"member_name": name, "member_vote": vote})

            # Format: "Ayes - Name, Name; Nays - Name" or "Aye: Name, Name"
            # Also handles: "Aye: Name1, Name2, Absent: Name3" (all on one line)
            if not individual_votes:
                for label, vote_val in [("Aye|Yes", "yes"), ("Nay|No", "no"),
                                         ("Abstain", "abstain"), ("Absent", "absent")]:
                    label_match = re.search(
                        rf'(?:{label})s?\s*[-–:]\s*(.+?)(?:\n|;|(?=\s*(?:Absent|Nay|Abstain|Aye|Yes|No)s?\s*[-–:])|\Z)',
                        full_context, re.IGNORECASE
                    )
                    if label_match:
                        names_text = label_match.group(1).strip().rstrip(',')
                        if names_text.lower() not in ("none", "n/a", "-", ""):
                            for name in re.split(r'[,;]', names_text):
                                name = name.strip()
                                # Skip names that are actually vote labels
                                if name and len(name) > 1 and not re.match(r'^(Absent|Nay|Abstain|Aye|Yes|No)s?$', name, re.I):
                                    individual_votes.append(
                                        {"member_name": name, "member_vote": vote_val}
                                    )

            if individual_votes:
                votes_for = sum(1 for v in individual_votes if v["member_vote"] == "yes")
                votes_against = sum(1 for v in individual_votes if v["member_vote"] == "no")
                votes_abstain = sum(1 for v in individual_votes if v["member_vote"] == "abstain")
                is_unanimous = votes_against == 0

            # Try to merge with an existing agenda item
            merged = False
            if item_title:
                title_lower = item_title.lower().strip()
                for existing_item in meeting.agenda_items:
                    et = existing_item.item_title.lower().strip()
                    if (et and title_lower and
                            (et in title_lower or title_lower in et
                             or len(set(et.split()) & set(title_lower.split())) >= min(len(et.split()), len(title_lower.split())) * 0.5)):
                        # Override with minutes data (higher confidence)
                        existing_item.has_vote = True
                        existing_item.vote_type = "roll_call" if individual_votes else "voice"
                        existing_item.result = result
                        existing_item.is_unanimous = is_unanimous
                        existing_item.motion_maker = motion_maker
                        existing_item.motion_seconder = motion_seconder
                        existing_item.motion_text = f"Motion by {motion_maker}, seconded by {motion_seconder}"
                        existing_item.votes_for = votes_for
                        existing_item.votes_against = votes_against
                        existing_item.votes_abstain = votes_abstain
                        existing_item.confidence = "high"
                        if individual_votes:
                            existing_item.individual_votes = individual_votes
                        merged = True
                        break

            if not merged:
                # Add as a new agenda item from minutes
                new_item = ExtractedItem(
                    item_title=item_title or f"Motion by {motion_maker}",
                    item_category=self._classify_category(item_title or ""),
                    has_vote=True,
                    vote_type="roll_call" if individual_votes else "voice",
                    result=result,
                    is_unanimous=is_unanimous,
                    confidence="high",
                    motion_text=f"Motion by {motion_maker}, seconded by {motion_seconder}",
                    motion_maker=motion_maker,
                    motion_seconder=motion_seconder,
                    votes_for=votes_for,
                    votes_against=votes_against,
                    votes_abstain=votes_abstain,
                    individual_votes=individual_votes,
                )
                meeting.agenda_items.append(new_item)
                self.total_items += 1
                if new_item.has_vote:
                    self.total_votes += 1

        # Also look for standalone roll call blocks in minutes not tied to motions
        # Format: "ROLL CALL: Mr. Smith - Yes, Ms. Jones - No"
        for rc_match in re.finditer(
            r'(?:Roll\s+Call|ROLL\s+CALL)\s+(?:Vote|VOTE)\s*:\s*(.+?)(?:\n\n|\n(?:[A-Z]{2,}\s|\d+\.))',
            minutes_text, re.DOTALL | re.IGNORECASE
        ):
            rc_text = rc_match.group(1)
            ind_votes = []
            for vm in re.finditer(
                r'(?:Mr|Ms|Mrs|Dr)\.?\s+([A-Za-z\'-]+)\s*[-–:]\s*(Yes|No|Aye|Nay|Yea|Abstain|Absent)',
                rc_text, re.IGNORECASE
            ):
                name = vm.group(1).strip()
                vote = vm.group(2).lower()
                if vote in ("aye", "yea"):
                    vote = "yes"
                elif vote == "nay":
                    vote = "no"
                ind_votes.append({"member_name": name, "member_vote": vote})

            if ind_votes:
                # Try to attach to the most recent agenda item without individual votes
                for item in reversed(meeting.agenda_items):
                    if item.has_vote and not item.individual_votes:
                        item.individual_votes = ind_votes
                        item.vote_type = "roll_call"
                        item.votes_for = sum(1 for v in ind_votes if v["member_vote"] == "yes")
                        item.votes_against = sum(1 for v in ind_votes if v["member_vote"] == "no")
                        item.votes_abstain = sum(1 for v in ind_votes if v["member_vote"] == "abstain")
                        item.is_unanimous = item.votes_against == 0
                        item.confidence = "high"
                        break

    def _extract_sections(self, text: str) -> list[dict]:
        """Extract agenda sections from the text."""
        sections = []

        # Limit text to agenda portion only (stop before PAGE TEXT / MINUTES TEXT markers)
        agenda_end = len(text)
        for marker in ["PAGE TEXT:", "MINUTES TEXT:", "MINUTES AJAX:"]:
            idx = text.find(marker)
            if idx != -1 and idx < agenda_end:
                agenda_end = idx
        agenda_text = text[:agenda_end]

        # Pattern: === SECTION HEADER ===
        pattern = r'===\s*(.+?)\s*==='
        matches = list(re.finditer(pattern, agenda_text))

        for i, match in enumerate(matches):
            header = match.group(1).strip()
            # Get text until next section
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(agenda_text)
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

        # Parse --- Item Detail --- blocks and attach to matching sections
        self._attach_item_details(text, sections)

        # Filter out navigation junk and too-short titles
        sections = [
            s for s in sections
            if len(s["title"].strip()) >= 3
            and s["title"].strip().lower() not in self.NAV_WORD_BLOCKLIST
        ]

        return sections

    def _attach_item_details(self, text: str, sections: list[dict]):
        """Parse '--- Item Detail ---' blocks from BD-GetAgendaItem responses
        and attach their content to matching agenda sections."""
        detail_pattern = r'---\s*Item Detail\s*---\s*\n(.+?)(?=\n---\s*Item Detail|$)'
        detail_blocks = list(re.finditer(detail_pattern, text, re.DOTALL))

        if not detail_blocks:
            return

        for block in detail_blocks:
            detail_text = block.group(1).strip()
            if len(detail_text) < 20:
                continue

            # Try to match this detail block to an existing section
            # by looking for the section title in the first few lines of detail
            first_lines = detail_text[:300].lower()
            matched = False

            for section in sections:
                title_lower = section["title"].lower().strip()
                if len(title_lower) > 5 and title_lower in first_lines:
                    section["body"] = section["body"] + "\n\n" + detail_text if section["body"] else detail_text
                    matched = True
                    break

            if not matched:
                # Extract title from the detail block itself (first non-empty line)
                lines = [l.strip() for l in detail_text.split('\n') if l.strip()]
                if lines:
                    sections.append({
                        "number": "",
                        "title": lines[0][:120],
                        "body": detail_text,
                        "full_header": lines[0][:120],
                    })

    def _extract_sections_fallback(self, text: str) -> list[dict]:
        """Fallback section extraction for non-standard formats."""
        sections = []
        # Try numbered items: "1. Item Title" or "A. Item Title"
        pattern = r'^(\d+[A-Z]?|[A-Z])\.?\s+([A-Z][^\n]{5,})'
        for match in re.finditer(pattern, text, re.MULTILINE):
            sections.append({
                "number": match.group(1),
                "title": match.group(2).strip(),
                "body": "",
                "full_header": match.group(0),
            })
        return sections

    # Generic section headers that aren't real agenda items
    GENERIC_HEADERS = [
        r"^action\s+items?\s*$",
        r"^action\s+agenda\s*$",
        r"^action\s*$",
        r"^unfinished\s+business\s*$",
        r"^new\s+business\s*$",
        r"^old\s+business\s*$",
        r"^other\s+business\s*$",
        r"^information\s+items?\s*$",
        r"^information\s*$",
        r"^discussion\s+items?\s*$",
        r"^discussion\s*$",
        r"^reports?\s*$",
        r"^board\s+reports?\s*$",
        r"^presentations?\s*$",
        r"^recognitions?\s*$",
        r"^announcements?\s*$",
        r"^opening\s+items?\s*$",
        r"^opening\s*$",
        r"^items?\s*$",
        r"^\d+\s+(street|avenue|ave|blvd|drive|road)\b",  # Address lines (page footer junk)
        r"^lincoln\s+street",
        r"^ninth\s+avenue",
        r"^resources?\s+tab\s*$",  # UI element, not an agenda item
        r"^other\s*$",
    ]

    def _process_section(self, section: dict) -> ExtractedItem:
        """Classify a section and determine if it has a vote."""
        item = ExtractedItem()
        item.item_number = section["number"]
        item.item_title = section["title"]

        # Skip generic section headers that aren't real agenda items
        title_clean = section["title"].strip()
        # Strip letter prefix like "A." "C." before checking
        title_no_prefix = re.sub(r'^[A-Z]\.\s*', '', title_clean)
        if (any(re.match(p, title_no_prefix, re.IGNORECASE) for p in self.GENERIC_HEADERS)
                and len(section["body"].strip()) < 50):
            item.item_category = "procedural"
            return item

        title_and_body = f"{section['title']} {section['body']}"
        body = section["body"]

        # Extract item description from body (first ~500 chars of non-vote text)
        if body:
            desc_text = body[:500].strip()
            # Remove vote block lines from description
            desc_lines = []
            for line in desc_text.split('\n'):
                if not re.match(r'^\s*(RESULT|MOVER|SECONDER|AYES|NAYS|ABSTAIN|ABSENT|Vote|Motion)\s*:', line, re.IGNORECASE):
                    desc_lines.append(line)
            desc = '\n'.join(desc_lines).strip()
            if len(desc) > 10:
                item.item_description = desc[:500]

        # Classify category
        item.item_category = self._classify_category(title_and_body)

        # Try structured BoardDocs vote block first (highest quality)
        if self._extract_boarddocs_vote_block(body, item):
            return item

        # Determine vote likelihood
        item.has_vote, vote_confidence = self._assess_vote_likelihood(title_and_body)

        if item.has_vote:
            # Extract vote details from body text
            self._extract_vote_details(body, title_and_body, item)
            item.confidence = vote_confidence

        return item

    def _extract_boarddocs_vote_block(self, body: str, item: ExtractedItem) -> bool:
        """Parse structured BoardDocs vote blocks from BD-GetAgendaItem responses.

        These blocks look like:
            RESULT: ADOPTED [UNANIMOUS]
            MOVER: John Smith, Board Member
            SECONDER: Jane Doe, Board Member
            AYES: Smith, Doe, Johnson, Williams, Brown
            NAYS: None
            ABSTAIN: None
            ABSENT: Davis

        Returns True if a structured vote block was found and parsed.
        """
        if not body:
            return False

        # Look for RESULT: line (the anchor of a vote block)
        result_match = re.search(
            r'RESULT:\s*(.+?)(?:\[(.+?)\])?\s*$',
            body, re.MULTILINE | re.IGNORECASE
        )
        if not result_match:
            return False

        result_text = result_match.group(1).strip().rstrip('[').strip()
        qualifier = (result_match.group(2) or "").strip()

        item.has_vote = True
        item.confidence = "high"

        # Parse result
        result_lower = result_text.lower()
        if any(w in result_lower for w in ("adopted", "approved", "passed", "carried")):
            item.result = "passed"
        elif any(w in result_lower for w in ("failed", "defeated", "denied", "rejected")):
            item.result = "failed"
        elif any(w in result_lower for w in ("tabled", "postponed", "deferred")):
            item.result = "tabled"
        elif "withdrawn" in result_lower:
            item.result = "withdrawn"
        else:
            logger.debug(f"Unrecognized vote result '{result_text}', defaulting to 'passed'")
            item.result = "passed"

        # Check unanimous
        if "unanimous" in qualifier.lower() or "unanimous" in result_lower:
            item.is_unanimous = True
            item.vote_type = "unanimous_consent"
        else:
            item.vote_type = "roll_call"

        # Parse MOVER
        mover_match = re.search(
            r'MOVER:\s*(.+?)(?:,\s*(?:Board Member|Vice Chair|Chair|Member|Trustee|Director))?\s*$',
            body, re.MULTILINE | re.IGNORECASE
        )
        if mover_match:
            item.motion_maker = mover_match.group(1).strip()
            item.motion_text = f"Motion by {item.motion_maker}"

        # Parse SECONDER
        seconder_match = re.search(
            r'SECONDER:\s*(.+?)(?:,\s*(?:Board Member|Vice Chair|Chair|Member|Trustee|Director))?\s*$',
            body, re.MULTILINE | re.IGNORECASE
        )
        if seconder_match:
            item.motion_seconder = seconder_match.group(1).strip()
            if item.motion_text:
                item.motion_text += f", seconded by {item.motion_seconder}"

        # Parse individual votes from AYES/NAYS/ABSTAIN/ABSENT lines
        def parse_name_list(label):
            pattern = rf'{label}:\s*(.+?)(?:\n|$)'
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                names_text = match.group(1).strip()
                if names_text.lower() in ("none", "n/a", "", "-"):
                    return []
                return [n.strip() for n in re.split(r'[,;]', names_text) if n.strip()]
            return []

        ayes = parse_name_list("AYES")
        nays = parse_name_list("NAYS")
        abstains = parse_name_list("ABSTAIN")
        absents = parse_name_list("ABSENT")

        for name in ayes:
            item.individual_votes.append({"member_name": name, "member_vote": "yes"})
        for name in nays:
            item.individual_votes.append({"member_name": name, "member_vote": "no"})
        for name in abstains:
            item.individual_votes.append({"member_name": name, "member_vote": "abstain"})
        for name in absents:
            item.individual_votes.append({"member_name": name, "member_vote": "absent"})

        if item.individual_votes:
            item.vote_type = "roll_call"
            item.votes_for = len(ayes)
            item.votes_against = len(nays)
            item.votes_abstain = len(abstains)
            item.is_unanimous = len(nays) == 0 and len(abstains) == 0

        return True

    def _classify_category(self, text: str) -> str:
        """Classify text into a policy category using keyword patterns."""
        # Strip common section-letter prefixes (e.g., "A.Opening Items" -> "Opening Items")
        clean_text = re.sub(r'^[A-Z]\.\s*', '', text.strip())
        # Strip parenthetical suffixes like "*(PUBLIC CANNOT ADDRESS THESE ITEMS)"
        clean_text = re.sub(r'\s*\*?\((?:PUBLIC|public)[^)]*\)\s*$', '', clean_text)
        # Strip leading "Consent - " prefix to expose the real topic
        consent_stripped = re.sub(r'^Consent\s*[-–]\s*', '', clean_text, flags=re.IGNORECASE)
        # Strip leading "Action (Consent):" or "Action:" prefix
        action_stripped = re.sub(
            r'^(?:Action\s*(?:\(Consent\)|Only)?\s*[-–:,]?\s*)',
            '', clean_text, flags=re.IGNORECASE
        ).strip()
        # Strip leading "Resolution:" prefix to expose the real topic
        resolution_stripped = re.sub(
            r'^Resolution\s*:\s*(?:Motion\s+to\s+)?(?:That\s+the\s+)?(?:School\s+Board\s+)?(?:Approv\w+\s+)?',
            '', clean_text, flags=re.IGNORECASE
        ).strip()

        scores = {}
        for cat, patterns in self.category_patterns.items():
            score = sum(1 for p in patterns if p.search(clean_text))
            # Also check with consent prefix stripped
            if consent_stripped != clean_text:
                score += sum(1 for p in patterns if p.search(consent_stripped))
            # Also check with action prefix stripped
            if action_stripped != clean_text:
                score += sum(1 for p in patterns if p.search(action_stripped))
            # Also check with resolution prefix stripped
            if resolution_stripped != clean_text and len(resolution_stripped) > 5:
                score += sum(1 for p in patterns if p.search(resolution_stripped))
            if score > 0:
                scores[cat] = score

        # If "Consent -" prefix was present and no other match, classify as consent_agenda
        if not scores and consent_stripped != clean_text:
            return "consent_agenda"

        if scores:
            return max(scores, key=scores.get)

        # Fallback heuristics for items that match no category patterns:
        # "Motion by Name" items are board actions (typically from minutes text)
        if re.match(r'^Motion\s+by\b', clean_text, re.IGNORECASE):
            return "admin_operations"

        # "Resolution:" items that didn't match any specific category
        if re.match(r'^Resolution\s*[:#]', clean_text, re.IGNORECASE):
            return "procedural"

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
        # Must be near vote language and reasonable board sizes (≤15 members)
        count_match = re.search(r'(\d+)\s*[-–]\s*(\d+)(?:\s*[-–]\s*(\d+))?', text)
        if count_match:
            a, b = int(count_match.group(1)), int(count_match.group(2))
            # Reject garbage: year ranges (2002-2026), policy numbers (14-1414),
            # item ranges ("Items 10-15"), page/section refs (933-1000)
            is_valid_count = (
                a <= 15 and b <= 15
                and not (a >= 1900 or b >= 1900)  # year-like
                and not re.search(
                    r'items?\s+\d+\s*[-–]\s*\d+|'     # "Items 10-15"
                    r'policy\s+\d|'                     # "Policy 1414"
                    r'section\s+\d|'                    # "Section 504"
                    r'\.\d+\s+supplemental',            # ".02 Supplemental"
                    text, re.IGNORECASE
                )
            )
            if is_valid_count:
                item.votes_for = a
                item.votes_against = b
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
            maker_name = maker_match.group(1)
            if maker_name.lower() not in self.MOTION_MAKER_BLOCKLIST:
                item.motion_maker = maker_name
                item.motion_text = f"Motion by {maker_name}"

        # Extract seconder
        second_match = re.search(r'second(?:ed)?\s+by\s+(?:(?:Mr|Ms|Mrs|Dr)\.?\s+)?(\w+)', text, re.IGNORECASE)
        if second_match:
            seconder_name = second_match.group(1)
            if seconder_name.lower() not in self.MOTION_MAKER_BLOCKLIST:
                item.motion_seconder = seconder_name
                if item.motion_text:
                    item.motion_text += f", seconded by {seconder_name}"
                else:
                    item.motion_text = f"Seconded by {seconder_name}"

        # Extract individual votes from roll call (Mr./Ms. Name: Yes format)
        individual_pattern = r'(?:Mr|Ms|Mrs|Dr)\.?\s+(\w+)\s*[-–:]\s*(yes|no|aye|nay|yea|abstain|absent)'
        for match in re.finditer(individual_pattern, text, re.IGNORECASE):
            name = match.group(1)
            vote = match.group(2).lower()
            if vote in ("aye", "yea"):
                vote = "yes"
            elif vote == "nay":
                vote = "no"
            item.individual_votes.append({"member_name": name, "member_vote": vote})

        # Extract individual votes from "Ayes: Name, Name" / "Nays: Name" format
        # (common in BoardDocs page text, e.g. Walton County FL)
        if not item.individual_votes:
            self._extract_ayes_nays_format(text, item)

        if item.individual_votes:
            item.vote_type = "roll_call"
            item.votes_for = sum(1 for v in item.individual_votes if v["member_vote"] == "yes")
            item.votes_against = sum(1 for v in item.individual_votes if v["member_vote"] == "no")
            item.is_unanimous = item.votes_against == 0
            item.confidence = "high"

    def _extract_ayes_nays_format(self, text: str, item: ExtractedItem):
        """Extract individual votes from 'Ayes: Name, Name' / 'Nays: Name' format.

        This format appears in BoardDocs page text, especially after minutes are posted:
            Motion by John Smith, second by Jane Doe.
            Final Resolution: Motion Carried
            Ayes: John Smith, Jane Doe, Bob Johnson, Mary Williams
            Nays: None
        """
        def parse_names(label):
            pattern = rf'(?:^|\n)\s*{label}\s*:\s*(.+?)(?:\n|$)'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                names_text = match.group(1).strip()
                if names_text.lower() in ("none", "n/a", "", "-"):
                    return []
                return [n.strip() for n in re.split(r',\s*', names_text) if n.strip() and len(n.strip()) > 2]
            return []

        ayes = parse_names("Ayes")
        nays = parse_names("Nays")
        abstains = parse_names("Abstain(?:ed)?")
        absents = parse_names("Absent")

        if not ayes and not nays:
            return

        for name in ayes:
            item.individual_votes.append({"member_name": name, "member_vote": "yes"})
        for name in nays:
            item.individual_votes.append({"member_name": name, "member_vote": "no"})
        for name in abstains:
            item.individual_votes.append({"member_name": name, "member_vote": "abstain"})
        for name in absents:
            item.individual_votes.append({"member_name": name, "member_vote": "absent"})

        if item.individual_votes:
            item.votes_for = len(ayes)
            item.votes_against = len(nays)
            item.votes_abstain = len(abstains)
            item.is_unanimous = len(nays) == 0 and len(abstains) == 0

        # Also try to extract full-name motion maker from "Motion by Full Name, second by Full Name"
        full_maker = re.search(
            r'Motion\s+by\s+((?:[A-Z][a-z]+\s+)+[A-Z][a-z]+),\s*second(?:ed)?\s+by\s+((?:[A-Z][a-z]+\s+)+[A-Z][a-z]+)',
            text
        )
        if full_maker:
            item.motion_maker = full_maker.group(1).strip()
            item.motion_seconder = full_maker.group(2).strip()
            item.motion_text = f"Motion by {item.motion_maker}, seconded by {item.motion_seconder}"

    def _extract_members(self, text: str, meeting: ExtractedMeeting):
        """Extract board member names from various formats found in BoardDocs pages."""
        members = {}  # name -> role

        # Pattern 1: "Members Present:" / "Present:" (traditional minutes format)
        present_match = re.search(
            r'(?:members?\s+)?present\s*[:\-]\s*(.+?)(?:\n\n|\n[A-Z]|absent)',
            text, re.IGNORECASE | re.DOTALL
        )
        if present_match:
            names_text = present_match.group(1)
            for name in re.split(r'[,;\n]', names_text):
                name = name.strip()
                if name and len(name) > 2:
                    members[name] = "member"

        absent_match = re.search(
            r'(?:members?\s+)?absent\s*[:\-]\s*(.+?)(?:\n\n|\n[A-Z])',
            text, re.IGNORECASE | re.DOTALL
        )
        if absent_match:
            names_text = absent_match.group(1)
            for name in re.split(r'[,;\n]', names_text):
                name = name.strip()
                if name and len(name) > 2 and name.lower() not in ("none", "n/a"):
                    meeting.members_absent.append(name)

        # Pattern 2: "Board Members: Name, Title; Name, Title; ..." (Montrose CO style)
        bm_match = re.search(
            r'Board Members:\s*(.+?)(?:\n(?:Superintendent|Secretary|$))',
            text, re.IGNORECASE
        )
        if bm_match:
            entries = re.split(r';\s*|\s+and\s+', bm_match.group(1))
            for entry in entries:
                entry = entry.strip().rstrip(',')
                if not entry:
                    continue
                # "Name, Title" format
                parts = entry.rsplit(',', 1)
                if len(parts) == 2:
                    name = self._clean_member_name(parts[0].strip())
                    role = self._normalize_role(parts[1].strip())
                else:
                    name = self._clean_member_name(entry)
                    role = "member"
                if name and len(name) > 2:
                    members[name] = role

        # Pattern 3: "Name, Board Member - District N" / "Name, Chair - District N" (Osceola FL)
        for match in re.finditer(
            r'^([A-Z][a-z\'"]+(?:\s+(?:"[^"]+"\s+)?[A-Z][a-z]+)+),\s*'
            r'(Board Member|Chair|Vice Chair|Member)\s*-?\s*(?:District\s+\d+)?',
            text, re.MULTILINE
        ):
            name = self._clean_member_name(match.group(1))
            role = self._normalize_role(match.group(2))
            if name and len(name) > 2:
                members[name] = role

        # Pattern 4: Vertical "Board President\nNAME\n..." (San Bernardino CA style)
        # Look for "Board President" / "Board Vice President" / "Board Members" headers
        # followed by ALL CAPS names on subsequent lines
        for match in re.finditer(
            r'(?:^|\n)(Board (?:Vice )?President|Board Members|Student Board Members)\n',
            text
        ):
            header = match.group(1)
            role = self._normalize_role(header.replace('Board ', '').strip())
            if 'Student' in header:
                continue  # Skip student board members
            # Read lines after the header until we hit a non-name line
            remaining = text[match.end():]
            for line in remaining.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Stop if we hit another header or non-ALL-CAPS line
                if re.match(r'(Board |Student |Superintendent|Secretary|View |Download |Print )', line):
                    break
                # Must be mostly uppercase (a name in ALL CAPS, possibly with Ed.D. credential)
                name_part = re.sub(r',?\s*Ed\.D\.?$', '', line)
                if name_part == name_part.upper() and re.match(r'^[A-Z][A-Z .\u2019\'-]+$', name_part):
                    name = self._clean_member_name(line)
                    if name and len(name) > 2:
                        members[name] = role
                else:
                    break

        # Pattern 5: "BOARD OF EDUCATION\nNAME1 • NAME2 • NAME3" (Chula Vista CA style)
        boe_match = re.search(
            r'BOARD OF EDUCATION\n([A-Z][A-Z .\u2022\u2013\'-]+(?:\n[A-Z][A-Z .\u2022\u2013\'-]+)*)',
            text
        )
        if boe_match:
            names_line = boe_match.group(1).strip()
            # Split by bullet separator •
            if '\u2022' in names_line or '•' in names_line:
                for name in re.split(r'\s*[•\u2022]\s*', names_line):
                    name = self._clean_member_name(name.strip())
                    if name and len(name) > 2:
                        members[name] = "member"

        # Pattern 6: "Name: President, Name: Vice President, Name: Member" (Santa Ana CA)
        # Match each "Name: Role" pair individually
        for match in re.finditer(
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+(?:,\s*Ed\.D\.?)?)\s*:\s*'
            r'(President|Vice President|Clerk|Member|Secretary|Trustee)',
            text
        ):
            name = self._clean_member_name(match.group(1))
            role = self._normalize_role(match.group(2))
            if name and len(name) > 2:
                members[name] = role

        # Pattern 7: "Secretary, Board of Education" preceded by a name (Boulder Valley CO)
        sec_match = re.search(
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\n\s*Secretary,?\s*Board of Education',
            text
        )
        if sec_match and not members:
            name = self._clean_member_name(sec_match.group(1))
            if name and len(name) > 2:
                members[name] = "secretary"

        # Populate meeting fields, filtering out invalid names
        if members:
            valid_members = {
                name: role for name, role in members.items()
                if self._is_valid_member_name(name)
            }
            meeting.members_present = list(valid_members.keys())
            meeting.member_roles = valid_members

    # Blocklist of names that are titles, roles, or other non-name strings
    MEMBER_NAME_BLOCKLIST = {
        "trustee", "attorney", "president", "vice president", "secretary",
        "treasurer", "superintendent", "none", "none.", "n/a", "absent",
        "present", "member", "chair", "chiar", "vice-chair", "technology",
        "seller", "sale", "purchaser(s)", "superintendent)",
    }

    @staticmethod
    def _clean_member_name(name: str) -> str:
        """Clean up a member name by removing titles, credentials, etc."""
        # Remove honorary/professional titles
        name = re.sub(r'^(?:Dr\.?|Mr\.?|Ms\.?|Mrs\.?|Prof\.?)\s+', '', name)
        # Remove trailing credentials
        name = re.sub(r',?\s*(?:Ed\.D\.?|Ph\.D\.?|M\.D\.?|J\.D\.?|Esq\.?)$', '', name)
        # Remove quoted nicknames but keep the rest: Teresa "Terry" Castillo -> Teresa Castillo
        name = re.sub(r'\s*"[^"]+"\s*', ' ', name)
        # Remove parenthetical notes like "(arrived at 7:05 p.m.)" or "(virtual)"
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', name)
        # Remove "arrived/departed" annotations
        name = re.sub(r'\s*(?:arrived|departed).*$', '', name, flags=re.IGNORECASE)
        # Normalize whitespace
        name = ' '.join(name.split())
        # Title-case if all caps
        if name == name.upper() and len(name) > 3:
            name = name.title()
        return name.strip()

    @staticmethod
    def normalize_member_name(name: str) -> str:
        """Normalize a member name for consistent matching.

        Delegates to database.operations.normalize_member_name for a single
        source of truth across extraction and storage layers.
        """
        return _normalize_member_name(name)

    @classmethod
    def _is_valid_member_name(cls, name: str) -> bool:
        """Validate that a string is a plausible board member name.

        Rejects:
        - Names shorter than 4 characters (catches 'Esq.', single-word fragments)
        - Names on the blocklist (titles, roles, placeholders)
        - Names containing digits (catches '#3-24/25', 'Ca 90504')
        - Names that are all uppercase and shorter than 5 chars (stray acronyms)
        - Names that look like sentences or data fragments (contain colons, start with parens)
        """
        if not name or not name.strip():
            return False

        name_stripped = name.strip()

        # Too short
        if len(name_stripped) < 4:
            return False

        # Blocklist check (case-insensitive)
        if name_stripped.lower().rstrip('.') in cls.MEMBER_NAME_BLOCKLIST:
            return False

        # Contains digits — catches identifiers, zip codes, dates, case numbers
        if re.search(r'\d', name_stripped):
            return False

        # Starts with special characters — catches "(3 anticipated cases", "#3-24/25"
        if re.match(r'^[^A-Za-z]', name_stripped):
            return False

        # All uppercase and short — stray acronyms like "CSEA", "SEIU"
        if name_stripped == name_stripped.upper() and len(name_stripped) < 5:
            return False

        # Contains colons — catches "Administration Present:", "Agency Negotiators: ..."
        if ':' in name_stripped:
            return False

        # Looks like a sentence or phrase (too many words, >6)
        if len(name_stripped.split()) > 6:
            return False

        # Starts with common non-name prefixes
        non_name_prefixes = (
            'that the ', 'agency ', 'administration ', 'agenda ',
            'property', 'arrived', 'departed', 'here @', 'arrived @',
            'member ', 'date:', 'time:', 'ca ', 'none ',
        )
        if name_stripped.lower().startswith(non_name_prefixes):
            return False

        return True

    @staticmethod
    def _deduplicate_votes(individual_votes: list) -> list:
        """Remove duplicate member entries from individual votes.

        When a member appears multiple times (from overlapping text regions
        or duplicate content in agenda/minutes), keep only one entry per member.
        If votes conflict (e.g., YES from an adjacent unanimous vote and NO from
        the actual contested vote), prefer NO/ABSTAIN — explicit dissent is a
        more reliable signal than inclusion in a general YES list.
        """
        if not individual_votes:
            return individual_votes

        # Priority: no > abstain > absent > yes
        # Dissent is a deliberate signal; YES can come from adjacent unanimous votes
        vote_priority = {"no": 4, "abstain": 3, "absent": 2, "yes": 1}

        seen = {}  # lowercase name -> (entry, priority)
        for vote_entry in individual_votes:
            name_lower = vote_entry["member_name"].strip().lower()
            priority = vote_priority.get(vote_entry["member_vote"], 0)

            if name_lower not in seen or priority > seen[name_lower][1]:
                seen[name_lower] = (vote_entry, priority)

        return [entry for entry, _ in seen.values()]

    @staticmethod
    def _normalize_role(role_text: str) -> str:
        """Normalize role text to a standard role identifier."""
        role_text = role_text.lower().strip()
        if 'president' in role_text or 'chair' in role_text:
            if 'vice' in role_text:
                return "vice_president"
            return "president"
        if 'secretary' in role_text or 'clerk' in role_text:
            return "secretary"
        if 'treasurer' in role_text:
            return "treasurer"
        if 'trustee' in role_text:
            return "trustee"
        if 'director' in role_text:
            return "member"
        return "member"

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
                    # Upgrade with LLM data (P5: guard against vote=None)
                    if llm_item.has_vote and getattr(llm_item, 'vote', None) is not None:
                        rule_item.has_vote = True
                        if llm_item.vote.vote_type:
                            rule_item.vote_type = llm_item.vote.vote_type
                        if llm_item.vote.result:
                            rule_item.result = llm_item.vote.result
                        if llm_item.vote.is_unanimous is not None:
                            rule_item.is_unanimous = llm_item.vote.is_unanimous
                        if llm_item.vote.votes_for is not None:
                            rule_item.votes_for = llm_item.vote.votes_for
                        if llm_item.vote.votes_against is not None:
                            rule_item.votes_against = llm_item.vote.votes_against
                        if getattr(llm_item.vote, 'individual_votes', None):
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

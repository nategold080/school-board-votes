"""LLM prompt templates for extracting structured vote data from meeting minutes."""

STAGE1_SYSTEM_PROMPT = """You are an expert at analyzing school board meeting minutes. Your job is to extract structured information from raw meeting minutes text.

You will identify:
1. Board members present and absent
2. Each distinct agenda item discussed
3. Whether each item involved a formal vote

Be thorough but concise. Focus on accuracy."""

STAGE1_USER_PROMPT = """Analyze the following school board meeting minutes. Extract:

1. **Meeting type**: regular, special, emergency, or work_session
2. **Members present**: List all board members who were present (just names)
3. **Members absent**: List any board members noted as absent
4. **Agenda items**: For each distinct agenda item, provide:
   - item_number: The agenda item number if given (e.g., "7.A", "Item 12")
   - item_title: Brief title/description
   - has_vote: true if a formal vote/motion occurred on this item, false otherwise
   - brief_description: One sentence about what the item covers

Respond ONLY with valid JSON in this exact format:
```json
{{
  "meeting_type": "regular",
  "members_present": ["Name1", "Name2"],
  "members_absent": ["Name3"],
  "agenda_items": [
    {{
      "item_number": "1",
      "item_title": "Approval of Minutes",
      "has_vote": true,
      "brief_description": "Approval of previous meeting minutes"
    }}
  ],
  "confidence": "high"
}}
```

Tips for identifying votes:
- Look for: "motion", "moved", "seconded", "carried", "approved", "passed", "defeated", "roll call", "vote", "aye", "nay"
- Consent agendas are single votes covering multiple routine items
- "No objection" or "by general consent" counts as a vote (unanimous_consent type)
- Items with only discussion and no motion do NOT have votes
- Executive/closed session entries should be noted but marked has_vote: false unless a vote is explicitly recorded

MEETING MINUTES:
{minutes_text}"""

STAGE2_SYSTEM_PROMPT = """You are an expert at extracting precise vote data from school board meeting minutes. You extract structured, accurate information about motions, votes, and individual voting records.

You must be extremely precise about:
- The exact wording of motions
- Who made and seconded motions
- How each member voted
- Whether votes were unanimous or contested
- The correct vote counts"""

STAGE2_USER_PROMPT = """Extract detailed vote information for the following agenda item from school board meeting minutes.

AGENDA ITEM: {item_title} (Item #{item_number})
ITEM DESCRIPTION: {item_description}

KNOWN MEMBERS PRESENT: {members_present}

Relevant section of minutes:
{minutes_text}

Extract the vote details and respond ONLY with valid JSON:
```json
{{
  "motion_text": "The exact text of the motion as stated in the minutes, or a close paraphrase",
  "motion_maker": "Name of member who made the motion (null if not stated)",
  "motion_seconder": "Name of member who seconded (null if not stated)",
  "vote_type": "roll_call | voice | unanimous_consent | show_of_hands",
  "result": "passed | failed | tabled | withdrawn | amended_and_passed",
  "votes_for": 5,
  "votes_against": 2,
  "votes_abstain": 0,
  "is_unanimous": false,
  "individual_votes": [
    {{"member_name": "Smith", "member_vote": "yes"}},
    {{"member_name": "Jones", "member_vote": "no"}}
  ],
  "item_category": "personnel | budget_finance | curriculum_instruction | facilities | policy | student_affairs | community_relations | consent_agenda | technology | safety_security | dei_equity | special_education | other",
  "confidence": "high | medium | low"
}}
```

IMPORTANT RULES:
1. If the minutes say "motion carried unanimously" or "approved unanimously":
   - Set is_unanimous: true, result: "passed"
   - Set vote_type: "voice" unless a roll call is specified
   - Set votes_for to the number of members present, votes_against: 0
   - List all present members with member_vote: "yes" in individual_votes

2. If the minutes say "motion carried 5-2" or similar:
   - Set the exact vote counts
   - is_unanimous: false
   - Only include individual_votes if the minutes specify who voted which way

3. For consent agendas:
   - item_category: "consent_agenda"
   - Include the motion text describing what was in the consent agenda

4. If a motion was amended:
   - result: "amended_and_passed" (if it ultimately passed)
   - motion_text should reflect the final/amended motion if possible

5. If an item was tabled:
   - result: "tabled"

6. confidence should be:
   - "high" if the minutes clearly state the motion, vote type, and result
   - "medium" if you had to infer some details (e.g., vote counts from "carried")
   - "low" if the information is ambiguous or incomplete

7. For item_category, choose the single best fit from the categories listed."""

FULL_EXTRACTION_PROMPT = """Analyze these school board meeting agenda/minutes and extract ALL structured data.

IMPORTANT: This text may come from a BoardDocs agenda view, which shows the agenda structure but not always the detailed vote results. When you see agenda section headers (like "=== 8.CONSENT AGENDA ===" or "=== 9.PERSONNEL AFFAIRS ==="), you should:
1. Classify each section by its category
2. Infer whether a vote likely occurred based on the item type:
   - "Consent Agenda" or "Approve Consent Agenda" → has_vote: true, vote type: voice, result: passed, is_unanimous: true, confidence: low
   - "Action on Minutes" or "Acceptance of Minutes" → has_vote: true, result: passed, is_unanimous: true, confidence: low
   - "Personnel Affairs/Changes" → has_vote: true (these are typically voted on), confidence: low
   - "Award of Contract/Purchase" → has_vote: true, category: budget_finance, confidence: low
   - "Board Policies" → has_vote: true, category: policy, confidence: low
   - "Call to Order", "Adjournment", "Comments from Speakers" → has_vote: false
   - "Committee Reports", "Superintendent's Report" → has_vote: false
3. If explicit vote data IS present (roll call, motion text, member names), extract it with high confidence

For the entire meeting, identify:
1. Meeting type (regular/special/emergency/work_session)
2. All board members present and absent (if listed)
3. Every agenda item, whether or not it had a vote
4. For items with votes: complete vote details (or inferred votes with low confidence)

Respond with valid JSON:
```json
{{
  "meeting_type": "regular",
  "members_present": ["Name1", "Name2"],
  "members_absent": ["Name3"],
  "agenda_items": [
    {{
      "item_number": "1",
      "item_title": "Call to Order",
      "item_description": "Meeting called to order at 7:00 PM",
      "item_category": "other",
      "has_vote": false,
      "vote": null
    }},
    {{
      "item_number": "2",
      "item_title": "Approval of Agenda",
      "item_description": "Motion to approve the meeting agenda",
      "item_category": "other",
      "has_vote": true,
      "vote": {{
        "motion_text": "Motion to approve the agenda as presented",
        "motion_maker": "Smith",
        "motion_seconder": "Jones",
        "vote_type": "voice",
        "result": "passed",
        "votes_for": 7,
        "votes_against": 0,
        "votes_abstain": 0,
        "is_unanimous": true,
        "individual_votes": [
          {{"member_name": "Smith", "member_vote": "yes"}},
          {{"member_name": "Jones", "member_vote": "yes"}}
        ],
        "confidence": "high"
      }}
    }}
  ],
  "extraction_confidence": "high"
}}
```

CATEGORY OPTIONS: personnel, budget_finance, curriculum_instruction, facilities, policy, student_affairs, community_relations, consent_agenda, technology, safety_security, dei_equity, special_education, other

VOTE RULES:
- "carried unanimously" = is_unanimous: true, all present members voted yes
- "carried 5-2" = extract counts, only include individual_votes if names are given
- Consent agendas = single vote for multiple routine items, category: consent_agenda
- Amended motions = result: "amended_and_passed" if ultimately passed
- Tabled items = result: "tabled"
- Executive sessions = note but mark has_vote: false unless a public vote is recorded
- If no formal motion/vote occurred, has_vote: false and vote: null

MEETING MINUTES:
{minutes_text}"""

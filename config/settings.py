"""Configuration settings for the School Board Votes project."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_MINUTES_DIR = DATA_DIR / "raw_minutes"
EXTRACTED_DIR = DATA_DIR / "extracted"
DATABASE_PATH = PROJECT_ROOT / os.getenv("DATABASE_PATH", "data/database.sqlite")
DISTRICTS_FILE = PROJECT_ROOT / "config" / "districts.json"

# Ensure directories exist
RAW_MINUTES_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Scraping settings
SCRAPE_DELAY = float(os.getenv("SCRAPE_DELAY_SECONDS", "1.5"))
USER_AGENT = os.getenv("USER_AGENT", "SchoolBoardVoteTracker/1.0 (Research Project)")
REQUEST_TIMEOUT = 30  # seconds

# Extraction settings
STAGE1_MODEL = os.getenv("EXTRACTION_MODEL_STAGE1", "gpt-4o-mini")
STAGE2_MODEL = os.getenv("EXTRACTION_MODEL_STAGE2", "gpt-4o")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Item categories
ITEM_CATEGORIES = [
    "personnel",
    "budget_finance",
    "curriculum_instruction",
    "facilities",
    "policy",
    "student_affairs",
    "community_relations",
    "consent_agenda",
    "technology",
    "safety_security",
    "dei_equity",
    "special_education",
    "other",
]

# Vote types
VOTE_TYPES = ["roll_call", "voice", "unanimous_consent", "show_of_hands"]

# Vote results
VOTE_RESULTS = ["passed", "failed", "tabled", "withdrawn", "amended_and_passed"]

# Member vote options
MEMBER_VOTE_OPTIONS = ["yes", "no", "abstain", "absent", "recused"]

# Meeting types
MEETING_TYPES = ["regular", "special", "emergency", "work_session"]

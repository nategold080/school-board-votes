"""Tools for discovering and cataloging school districts and their minutes URLs."""

import json
import logging
from pathlib import Path
from config.settings import DISTRICTS_FILE

logger = logging.getLogger(__name__)


def load_districts() -> list[dict]:
    """Load the district list from districts.json."""
    if DISTRICTS_FILE.exists():
        with open(DISTRICTS_FILE, "r") as f:
            return json.load(f)
    return []


def save_districts(districts: list[dict]):
    """Save the district list to districts.json."""
    DISTRICTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DISTRICTS_FILE, "w") as f:
        json.dump(districts, f, indent=2)
    logger.info(f"Saved {len(districts)} districts to {DISTRICTS_FILE}")


def get_districts_by_state(state: str) -> list[dict]:
    """Get districts for a specific state."""
    districts = load_districts()
    return [d for d in districts if d.get("state") == state]


def get_districts_by_platform(platform: str) -> list[dict]:
    """Get districts using a specific platform."""
    districts = load_districts()
    return [d for d in districts if d.get("platform") == platform]


def get_scraper_for_district(district: dict):
    """Return the appropriate scraper instance for a district."""
    from scraper.boarddocs_scraper import BoardDocsScraper
    from scraper.pdf_scraper import PDFMinutesScraper
    from scraper.html_scraper import HTMLMinutesScraper

    platform = district.get("platform", "html").lower()
    district_id = district["district_id"]
    name = district["district_name"]
    url = district["minutes_url"]

    if platform == "boarddocs":
        return BoardDocsScraper(district_id, name, url)
    elif platform == "pdf":
        return PDFMinutesScraper(district_id, name, url)
    else:
        return HTMLMinutesScraper(district_id, name, url)

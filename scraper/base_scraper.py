"""Abstract base scraper class for school board meeting minutes."""

import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import date
from dataclasses import dataclass
import requests

from config.settings import SCRAPE_DELAY, USER_AGENT, REQUEST_TIMEOUT, RAW_MINUTES_DIR

logger = logging.getLogger(__name__)


@dataclass
class MeetingMinutes:
    """Represents a single set of meeting minutes."""
    district_id: str
    meeting_date: date
    meeting_type: str
    source_url: str
    raw_text: str
    file_path: str = None


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    def __init__(self, district_id: str, district_name: str, base_url: str):
        self.district_id = district_id
        self.district_name = district_name
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
        })
        self.delay = SCRAPE_DELAY
        self.timeout = REQUEST_TIMEOUT

    def _get(self, url: str, **kwargs) -> requests.Response:
        """Make a GET request with delay and error handling."""
        time.sleep(self.delay)
        try:
            response = self.session.get(url, timeout=self.timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"Request failed for {url}: {e}")
            raise

    def _save_raw(self, minutes: MeetingMinutes) -> str:
        """Save raw minutes text to disk."""
        safe_name = self.district_name.replace(" ", "_").replace("/", "_")[:50]
        date_str = minutes.meeting_date.strftime("%Y-%m-%d")
        dir_path = RAW_MINUTES_DIR / self.district_id
        dir_path.mkdir(parents=True, exist_ok=True)
        file_path = dir_path / f"{safe_name}_{date_str}.txt"
        file_path.write_text(minutes.raw_text, encoding="utf-8")
        minutes.file_path = str(file_path)
        return str(file_path)

    @abstractmethod
    def discover_meetings(self, months_back: int = 12) -> list[dict]:
        """Discover available meetings. Returns list of {date, url, type}."""
        pass

    @abstractmethod
    def scrape_meeting(self, meeting_url: str, meeting_date: date,
                       meeting_type: str = "regular") -> MeetingMinutes:
        """Scrape a single meeting's minutes."""
        pass

    def scrape_all(self, months_back: int = 12) -> list[MeetingMinutes]:
        """Discover and scrape all available meetings."""
        results = []
        try:
            meetings = self.discover_meetings(months_back)
            logger.info(f"Found {len(meetings)} meetings for {self.district_name}")
        except Exception as e:
            logger.error(f"Failed to discover meetings for {self.district_name}: {e}")
            return results

        for meeting_info in meetings:
            try:
                minutes = self.scrape_meeting(
                    meeting_info["url"],
                    meeting_info["date"],
                    meeting_info.get("type", "regular")
                )
                if minutes and minutes.raw_text and len(minutes.raw_text.strip()) > 100:
                    self._save_raw(minutes)
                    results.append(minutes)
                    logger.info(f"Scraped {self.district_name} - {meeting_info['date']}")
                else:
                    logger.warning(f"Empty/short minutes for {self.district_name} - {meeting_info['date']}")
            except Exception as e:
                logger.error(f"Failed to scrape {self.district_name} - {meeting_info['date']}: {e}")
                continue

        return results

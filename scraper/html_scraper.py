"""Scraper for districts that post meeting minutes as HTML pages."""

import re
import logging
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper, MeetingMinutes

logger = logging.getLogger(__name__)


class HTMLMinutesScraper(BaseScraper):
    """Scraper for districts posting minutes as HTML web pages."""

    def __init__(self, district_id: str, district_name: str, base_url: str,
                 minutes_link_selector: str = None):
        super().__init__(district_id, district_name, base_url)
        self.link_selector = minutes_link_selector

    def discover_meetings(self, months_back: int = 12) -> list[dict]:
        """Find meeting minutes links on the district's minutes page."""
        meetings = []
        cutoff = date.today() - timedelta(days=months_back * 30)

        try:
            response = self._get(self.base_url)
            soup = BeautifulSoup(response.text, "lxml")

            # Strategy 1: Use provided CSS selector
            if self.link_selector:
                links = soup.select(self.link_selector)
            else:
                # Strategy 2: Find all links containing minute-related keywords
                links = soup.find_all("a", href=True)

            for link in links:
                href = link.get("href", "") if isinstance(link, dict) else link["href"]
                text = link.get_text(strip=True) if hasattr(link, 'get_text') else str(link)
                combined = f"{text} {href}"

                # Skip non-relevant links
                if not any(kw in combined.lower() for kw in
                          ["minute", "meeting", "board", "regular", "special"]):
                    continue

                # Skip PDF links (handled by PDFMinutesScraper)
                if href.lower().endswith(".pdf"):
                    continue

                meeting_date = self._extract_date(combined)
                if meeting_date and meeting_date >= cutoff:
                    full_url = urljoin(self.base_url, href)
                    meetings.append({
                        "date": meeting_date,
                        "url": full_url,
                        "type": self._classify_type(text),
                    })

        except Exception as e:
            logger.error(f"Failed to discover HTML minutes for {self.district_name}: {e}")

        # Deduplicate by date
        seen_dates = set()
        unique_meetings = []
        for m in meetings:
            if m["date"] not in seen_dates:
                seen_dates.add(m["date"])
                unique_meetings.append(m)

        return unique_meetings

    def scrape_meeting(self, meeting_url: str, meeting_date: date,
                       meeting_type: str = "regular") -> MeetingMinutes:
        """Scrape meeting minutes from an HTML page."""
        try:
            response = self._get(meeting_url)
            soup = BeautifulSoup(response.text, "lxml")

            # Remove navigation, scripts, styles, headers, footers
            for element in soup(["script", "style", "nav", "header", "footer",
                                "aside", "form", "iframe"]):
                element.decompose()

            # Try to find the main content area
            content = None
            for selector in ["main", "article", "#content", ".content",
                           "#main-content", ".main-content", "#minutes",
                           ".minutes-content", ".board-minutes"]:
                content = soup.select_one(selector)
                if content:
                    break

            if not content:
                # Fall back to body
                content = soup.find("body") or soup

            # Extract text preserving some structure
            text = self._extract_structured_text(content)

            if not text or len(text.strip()) < 100:
                logger.warning(f"Insufficient text from {meeting_url}")
                return None

            return MeetingMinutes(
                district_id=self.district_id,
                meeting_date=meeting_date,
                meeting_type=meeting_type,
                source_url=meeting_url,
                raw_text=text,
            )
        except Exception as e:
            logger.error(f"Failed to scrape HTML minutes {meeting_url}: {e}")
            return None

    def _extract_structured_text(self, element) -> str:
        """Extract text while preserving structure (headers, lists, paragraphs)."""
        parts = []
        for child in element.descendants:
            if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = child.get_text(strip=True)
                if text:
                    parts.append(f"\n{'='*40}\n{text}\n{'='*40}")
            elif child.name == "li":
                text = child.get_text(strip=True)
                if text:
                    parts.append(f"  - {text}")
            elif child.name in ("p", "div", "td", "tr"):
                text = child.get_text(strip=True)
                if text and len(text) > 5:
                    parts.append(text)
            elif child.name == "br":
                parts.append("")

        # Deduplicate consecutive identical lines
        result = []
        prev = None
        for line in parts:
            if line != prev:
                result.append(line)
                prev = line

        return "\n".join(result)

    @staticmethod
    def _extract_date(text: str) -> date:
        """Extract date from text."""
        if not text:
            return None

        # Month name + day + year
        match = re.search(
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})',
            text, re.IGNORECASE
        )
        if match:
            try:
                return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%B %d %Y").date()
            except ValueError:
                pass

        # Numeric
        match = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', text)
        if match:
            try:
                return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
            except ValueError:
                pass

        # YYYY-MM-DD
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        return None

    @staticmethod
    def _classify_type(text: str) -> str:
        text_lower = text.lower()
        if "special" in text_lower:
            return "special"
        if "work" in text_lower or "workshop" in text_lower:
            return "work_session"
        if "emergency" in text_lower:
            return "emergency"
        return "regular"

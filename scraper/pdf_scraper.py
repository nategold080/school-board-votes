"""Scraper for districts that post meeting minutes as PDFs."""

import re
import io
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper, MeetingMinutes

logger = logging.getLogger(__name__)


class PDFMinutesScraper(BaseScraper):
    """Scraper for districts posting minutes as PDF files."""

    def __init__(self, district_id: str, district_name: str, base_url: str,
                 pdf_url_pattern: str = None):
        super().__init__(district_id, district_name, base_url)
        self.pdf_url_pattern = pdf_url_pattern

    def discover_meetings(self, months_back: int = 12) -> list[dict]:
        """Find PDF meeting minutes links on the district page."""
        meetings = []
        cutoff = date.today() - timedelta(days=months_back * 30)

        try:
            response = self._get(self.base_url)
            soup = BeautifulSoup(response.text, "lxml")

            # Find all PDF links
            for link in soup.find_all("a", href=True):
                href = link["href"]
                text = link.get_text(strip=True)
                combined = f"{text} {href}"

                # Check if it's a PDF link related to minutes
                is_pdf = href.lower().endswith(".pdf") or "pdf" in href.lower()
                is_minutes = any(kw in combined.lower() for kw in
                               ["minute", "minutes", "meeting", "board"])

                if is_pdf and is_minutes:
                    meeting_date = self._extract_date(combined)
                    if meeting_date and meeting_date >= cutoff:
                        full_url = urljoin(self.base_url, href)
                        meetings.append({
                            "date": meeting_date,
                            "url": full_url,
                            "type": self._classify_type(text),
                        })

            # Also check for links to pages that might contain PDFs
            if not meetings:
                meetings = self._deep_search_for_pdfs(soup, cutoff)

        except Exception as e:
            logger.error(f"Failed to discover PDF minutes for {self.district_name}: {e}")

        # Deduplicate by date
        seen_dates = set()
        unique_meetings = []
        for m in meetings:
            if m["date"] not in seen_dates:
                seen_dates.add(m["date"])
                unique_meetings.append(m)

        return unique_meetings

    def _deep_search_for_pdfs(self, soup: BeautifulSoup, cutoff: date) -> list[dict]:
        """Search one level deeper for PDF links."""
        meetings = []
        # Look for links that might lead to meeting-specific pages
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True).lower()
            if any(kw in text for kw in ["minutes", "meeting", "archive", "past meeting"]):
                try:
                    sub_url = urljoin(self.base_url, link["href"])
                    if sub_url == self.base_url:
                        continue
                    sub_response = self._get(sub_url)
                    sub_soup = BeautifulSoup(sub_response.text, "lxml")

                    for sub_link in sub_soup.find_all("a", href=True):
                        href = sub_link["href"]
                        sub_text = sub_link.get_text(strip=True)
                        if href.lower().endswith(".pdf"):
                            meeting_date = self._extract_date(f"{sub_text} {href}")
                            if meeting_date and meeting_date >= cutoff:
                                full_url = urljoin(sub_url, href)
                                meetings.append({
                                    "date": meeting_date,
                                    "url": full_url,
                                    "type": self._classify_type(sub_text),
                                })
                except Exception:
                    continue
                if meetings:
                    break
        return meetings

    def scrape_meeting(self, meeting_url: str, meeting_date: date,
                       meeting_type: str = "regular") -> MeetingMinutes:
        """Download and extract text from a PDF."""
        try:
            response = self._get(meeting_url)

            # Try pdfplumber first
            text = self._extract_with_pdfplumber(response.content)

            # Fallback to pymupdf
            if not text or len(text.strip()) < 100:
                text = self._extract_with_pymupdf(response.content)

            if not text or len(text.strip()) < 50:
                logger.warning(f"Could not extract meaningful text from {meeting_url}")
                return None

            return MeetingMinutes(
                district_id=self.district_id,
                meeting_date=meeting_date,
                meeting_type=meeting_type,
                source_url=meeting_url,
                raw_text=text,
            )
        except Exception as e:
            logger.error(f"Failed to scrape PDF {meeting_url}: {e}")
            return None

    def _extract_with_pdfplumber(self, pdf_bytes: bytes) -> str:
        """Extract text using pdfplumber."""
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except ImportError:
            logger.warning("pdfplumber not installed, skipping")
            return ""
        except Exception as e:
            logger.debug(f"pdfplumber extraction failed: {e}")
            return ""

    def _extract_with_pymupdf(self, pdf_bytes: bytes) -> str:
        """Extract text using pymupdf (fitz)."""
        try:
            import fitz
            text_parts = []
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            return "\n\n".join(text_parts)
        except ImportError:
            logger.warning("pymupdf not installed, skipping")
            return ""
        except Exception as e:
            logger.debug(f"pymupdf extraction failed: {e}")
            return ""

    @staticmethod
    def _extract_date(text: str) -> date:
        """Extract a date from text or URL."""
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

        # Abbreviated month
        match = re.search(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{1,2}),?\s+(\d{4})',
            text, re.IGNORECASE
        )
        if match:
            try:
                return datetime.strptime(f"{match.group(1)} {match.group(2)} {match.group(3)}", "%b %d %Y").date()
            except ValueError:
                pass

        # Numeric formats in text
        match = re.search(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})', text)
        if match:
            try:
                return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
            except ValueError:
                pass

        # YYYY-MM-DD in URLs
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        # YYYYMMDD in URLs
        match = re.search(r'(\d{4})(\d{2})(\d{2})', text)
        if match:
            try:
                d = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                if 2024 <= d.year <= 2026:
                    return d
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

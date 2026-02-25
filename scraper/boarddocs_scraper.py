"""Scraper for districts using BoardDocs platform.

Uses the BD-GETMeetingsListForSEO endpoint (no auth required) for meeting discovery,
and Playwright for fetching meeting content (agenda, minutes).
"""

import re
import json
import time
import logging
import asyncio
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
import requests

from .base_scraper import BaseScraper, MeetingMinutes
from config.settings import SCRAPE_DELAY, USER_AGENT, RAW_MINUTES_DIR

logger = logging.getLogger(__name__)


class BoardDocsScraper(BaseScraper):
    """Scraper for BoardDocs-powered school board minutes."""

    def __init__(self, district_id: str, district_name: str, base_url: str,
                 boarddocs_org: str = None):
        super().__init__(district_id, district_name, base_url)
        self._extract_state_and_org()

    def _extract_state_and_org(self):
        match = re.search(r'boarddocs\.com/(\w+)/(\w+)', self.base_url)
        if match:
            self.bd_state = match.group(1)
            self.bd_org = match.group(2)
        else:
            self.bd_state = ""
            self.bd_org = ""

    @property
    def _nsf_base(self):
        return f"https://go.boarddocs.com/{self.bd_state}/{self.bd_org}/Board.nsf"

    def discover_meetings(self, months_back: int = 12) -> list[dict]:
        """Discover meetings via the SEO endpoint."""
        meetings = []
        cutoff = date.today() - timedelta(days=months_back * 30)

        try:
            url = f"{self._nsf_base}/BD-GETMeetingsListForSEO?open&0.123"
            response = self._get(url)
            if response.status_code == 200 and response.text:
                data = response.json()
                for item in data:
                    meeting_date = self._parse_seo_date(item.get("Date", ""))
                    if meeting_date and meeting_date >= cutoff:
                        name = item.get("Name", "")
                        meetings.append({
                            "date": meeting_date,
                            "url": f"{self._nsf_base}/goto?open&id={item.get('Unique', '')}",
                            "type": self._classify_meeting_type(name),
                            "meeting_id": item.get("Unique", ""),
                            "name": name,
                        })
        except Exception as e:
            logger.warning(f"SEO endpoint failed for {self.district_name}: {e}")

        logger.info(f"Discovered {len(meetings)} meetings for {self.district_name}")
        return meetings

    def scrape_meeting(self, meeting_url: str, meeting_date: date,
                       meeting_type: str = "regular") -> MeetingMinutes:
        """Scrape a single meeting using Playwright."""
        meeting_id = meeting_url.split("id=")[-1] if "id=" in meeting_url else ""
        if not meeting_id:
            return None

        try:
            raw_text = asyncio.run(self._scrape_single_meeting(meeting_id))
        except Exception as e:
            logger.error(f"Playwright scrape failed for {self.district_name} {meeting_date}: {e}")
            return None

        if not raw_text or len(raw_text.strip()) < 100:
            return None

        return MeetingMinutes(
            district_id=self.district_id,
            meeting_date=meeting_date,
            meeting_type=meeting_type,
            source_url=meeting_url,
            raw_text=raw_text,
        )

    def scrape_all(self, months_back: int = 12) -> list[MeetingMinutes]:
        """Override to batch meetings through a single browser session."""
        results = []
        try:
            meetings = self.discover_meetings(months_back)
            logger.info(f"Found {len(meetings)} meetings for {self.district_name}")
        except Exception as e:
            logger.error(f"Failed to discover meetings for {self.district_name}: {e}")
            return results

        # Limit to ~8 most recent meetings for efficiency
        meetings = meetings[:8]

        if not meetings:
            return results

        # Batch scrape through single browser session
        try:
            texts = asyncio.run(self._batch_scrape(meetings))
        except Exception as e:
            logger.error(f"Batch scrape failed for {self.district_name}: {e}")
            return results

        for meeting_info, raw_text in zip(meetings, texts):
            if raw_text and len(raw_text.strip()) > 100:
                minutes = MeetingMinutes(
                    district_id=self.district_id,
                    meeting_date=meeting_info["date"],
                    meeting_type=meeting_info.get("type", "regular"),
                    source_url=meeting_info["url"],
                    raw_text=raw_text,
                )
                self._save_raw(minutes)
                results.append(minutes)
                logger.info(f"Scraped {self.district_name} - {meeting_info['date']} ({len(raw_text)} chars)")
            else:
                logger.warning(f"Insufficient text for {self.district_name} - {meeting_info['date']}")

        return results

    async def _batch_scrape(self, meetings: list[dict]) -> list[str]:
        """Scrape multiple meetings using a single browser session."""
        from playwright.async_api import async_playwright

        results = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )

            for i, meeting_info in enumerate(meetings):
                meeting_id = meeting_info.get("meeting_id", "")
                if not meeting_id:
                    results.append("")
                    continue

                try:
                    text = await self._scrape_meeting_page(context, meeting_id)
                    results.append(text)
                    logger.debug(f"  Meeting {i+1}/{len(meetings)}: {len(text)} chars")
                except Exception as e:
                    logger.warning(f"  Meeting {i+1} failed: {e}")
                    results.append("")

                # Delay between meetings
                await asyncio.sleep(1)

            await browser.close()

        return results

    async def _scrape_meeting_page(self, context, meeting_id: str) -> str:
        """Scrape a single meeting page within an existing browser context."""
        page = await context.new_page()
        text_parts = []
        agenda_html = ""
        items_html = []

        async def capture_response(response):
            nonlocal agenda_html
            url = response.url
            try:
                if "BD-GetAgenda" in url and "AgendaItem" not in url:
                    agenda_html = await response.text()
                elif "BD-GetAgendaItem" in url:
                    body = await response.text()
                    items_html.append(body)
            except Exception as e:
                logger.warning(f"Error capturing response from {url}: {e}")

        page.on("response", capture_response)

        goto_url = f"{self._nsf_base}/goto?open&id={meeting_id}"
        await page.goto(goto_url, timeout=30000)
        await page.wait_for_timeout(4000)

        # Click on agenda items to load their content
        try:
            clickable = await page.query_selector_all('dd.item .item-title, dd .agenda-item-title')
            for elem in clickable[:25]:
                try:
                    await elem.click()
                    await page.wait_for_timeout(800)
                except Exception as e:
                    logger.debug(f"Error clicking agenda item: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Error querying agenda items: {e}")

        # Get the visible page text as well
        try:
            visible = await page.inner_text("#agenda-content, #wrap-agenda, .agenda-container, body")
            if visible:
                text_parts.append(visible)
        except Exception as e:
            logger.warning(f"Error getting visible page text: {e}")

        # Parse agenda HTML
        if agenda_html:
            soup = BeautifulSoup(agenda_html, "lxml")
            for elem in soup.find_all(["dt", "dd"]):
                t = elem.get_text(strip=True)
                if t and len(t) > 3:
                    if elem.name == "dt":
                        text_parts.append(f"\n== {t} ==")
                    else:
                        text_parts.append(t)

        # Parse agenda items
        for html in items_html:
            soup = BeautifulSoup(html, "lxml")
            t = soup.get_text(separator="\n", strip=True)
            if t and len(t) > 20:
                text_parts.append(f"\n--- Item ---\n{t}")

        await page.close()
        return "\n".join(text_parts)

    async def _scrape_single_meeting(self, meeting_id: str) -> str:
        """Scrape a single meeting (opens its own browser)."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            text = await self._scrape_meeting_page(context, meeting_id)
            await browser.close()
            return text

    @staticmethod
    def _parse_seo_date(date_str: str) -> date:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _classify_meeting_type(name: str) -> str:
        name_lower = name.lower()
        if "special" in name_lower:
            return "special"
        if "emergency" in name_lower:
            return "emergency"
        if "work" in name_lower or "workshop" in name_lower or "retreat" in name_lower:
            return "work_session"
        return "regular"

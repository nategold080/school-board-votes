"""Efficient batch scraper for all BoardDocs districts."""

import sys
import json
import asyncio
import logging
import time
import re
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from config.settings import RAW_MINUTES_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("scrape_all.log")],
)
logger = logging.getLogger(__name__)


def load_districts():
    with open(Path(__file__).parent.parent / "config" / "districts.json") as f:
        return json.load(f)


def parse_boarddocs_url(url):
    """Extract state_code and org_code from BoardDocs URL."""
    match = re.search(r'boarddocs\.com/(\w+)/(\w+)', url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def get_meeting_list(state_code, org_code, months_back=12):
    """Get meeting list via SEO endpoint (no browser needed)."""
    nsf_base = f"https://go.boarddocs.com/{state_code}/{org_code}/Board.nsf"
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 SchoolBoardResearch/1.0"})

    try:
        resp = session.get(f"{nsf_base}/BD-GETMeetingsListForSEO?open&0.1", timeout=15)
        if not resp.text:
            return []

        all_meetings = resp.json()
        cutoff = date.today() - timedelta(days=months_back * 30)

        meetings = []
        for m in all_meetings:
            try:
                d = datetime.fromisoformat(m["Date"].replace("Z", "+00:00")).date()
                if d >= cutoff:
                    meetings.append({
                        "id": m["Unique"],
                        "name": m["Name"],
                        "date": d,
                    })
            except:
                continue
        return meetings
    except Exception as e:
        logger.warning(f"Failed to get meeting list for {org_code}: {e}")
        return []


async def scrape_district_meetings(context, nsf_base, meetings, district_name,
                                    district_id, max_meetings=6):
    """Scrape meetings for one district using shared browser context."""
    # Prioritize business/regular meetings
    priority = [m for m in meetings if any(kw in m["name"].lower()
                for kw in ["business", "regular board", "board meeting"])]
    if len(priority) >= 3:
        meetings = priority
    meetings = meetings[:max_meetings]

    results = []
    for i, meeting in enumerate(meetings):
        try:
            page = await context.new_page()
            agenda_text = ""

            async def capture_agenda(response):
                nonlocal agenda_text
                if "BD-GetAgenda" in response.url and "Item" not in response.url:
                    try:
                        agenda_text = await response.text()
                    except:
                        pass

            page.on("response", capture_agenda)

            url = f"{nsf_base}/goto?open&id={meeting['id']}"
            await page.goto(url, timeout=25000)
            await page.wait_for_timeout(4000)

            body_text = ""
            try:
                body_text = await page.inner_text("body")
            except:
                pass

            # Parse agenda HTML
            agenda_structured = ""
            if agenda_text:
                soup = BeautifulSoup(agenda_text, "lxml")
                parts = []
                for elem in soup.find_all(["dt", "dd"]):
                    t = elem.get_text(strip=True)
                    if t:
                        if elem.name == "dt":
                            parts.append(f"\n=== {t} ===")
                        else:
                            parts.append(f"  {t}")
                agenda_structured = "\n".join(parts)

            full_text = f"District: {district_name}\nDate: {meeting['date']}\nMeeting: {meeting['name']}\n\n"
            if agenda_structured:
                full_text += "AGENDA:\n" + agenda_structured + "\n\n"
            full_text += "PAGE TEXT:\n" + body_text

            await page.close()

            if len(full_text.strip()) > 200:
                # Save to disk
                safe_name = district_name.replace(" ", "_")[:40]
                date_str = meeting["date"].strftime("%Y-%m-%d")
                dir_path = RAW_MINUTES_DIR / district_id
                dir_path.mkdir(parents=True, exist_ok=True)
                file_path = dir_path / f"{safe_name}_{date_str}.txt"
                file_path.write_text(full_text, encoding="utf-8")

                results.append({
                    "date": str(meeting["date"]),
                    "name": meeting["name"],
                    "chars": len(full_text),
                    "file": str(file_path),
                })

            await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"    Failed meeting {meeting['name']}: {e}")
            try:
                await page.close()
            except:
                pass

    return results


async def main():
    districts = load_districts()
    boarddocs_districts = [d for d in districts if d.get("platform") == "boarddocs"]

    logger.info(f"Starting batch scrape of {len(boarddocs_districts)} BoardDocs districts")

    total_meetings = 0
    total_chars = 0
    successful_districts = 0
    failed_districts = []
    all_results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )

        for i, district in enumerate(boarddocs_districts, 1):
            name = district["district_name"]
            did = district["district_id"]
            url = district["minutes_url"]
            state_code, org_code = parse_boarddocs_url(url)

            if not state_code:
                logger.warning(f"[{i}/{len(boarddocs_districts)}] Could not parse URL for {name}")
                failed_districts.append(name)
                continue

            logger.info(f"[{i}/{len(boarddocs_districts)}] {name} ({district['state']})")

            # Get meeting list
            meetings = get_meeting_list(state_code, org_code, months_back=12)
            if not meetings:
                logger.warning(f"  No meetings found")
                failed_districts.append(name)
                continue

            nsf_base = f"https://go.boarddocs.com/{state_code}/{org_code}/Board.nsf"

            try:
                results = await scrape_district_meetings(
                    context, nsf_base, meetings, name, did, max_meetings=6
                )

                if results:
                    successful_districts += 1
                    meeting_count = len(results)
                    char_count = sum(r["chars"] for r in results)
                    total_meetings += meeting_count
                    total_chars += char_count
                    all_results[did] = results
                    logger.info(f"  -> {meeting_count} meetings, {char_count:,} chars")
                else:
                    failed_districts.append(name)
                    logger.warning(f"  -> No content scraped")

            except Exception as e:
                failed_districts.append(name)
                logger.error(f"  -> Error: {e}")

            # Small delay between districts
            await asyncio.sleep(1)

        await browser.close()

    # Summary
    print(f"\n{'='*60}")
    print(f"SCRAPING COMPLETE")
    print(f"{'='*60}")
    print(f"Successful districts: {successful_districts}/{len(boarddocs_districts)}")
    print(f"Total meetings scraped: {total_meetings}")
    print(f"Total text: {total_chars:,} characters")
    print(f"Failed districts: {len(failed_districts)}")
    if failed_districts:
        for name in failed_districts[:10]:
            print(f"  - {name}")

    # Save summary
    with open("scrape_summary.json", "w") as f:
        json.dump({
            "successful": successful_districts,
            "total_meetings": total_meetings,
            "total_chars": total_chars,
            "failed": failed_districts,
            "results": {k: v for k, v in all_results.items()},
        }, f, indent=2, default=str)


if __name__ == "__main__":
    asyncio.run(main())

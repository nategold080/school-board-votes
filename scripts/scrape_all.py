"""Efficient batch scraper for all BoardDocs districts.

Enhanced with:
- Item-level detail capture (BD-GetAgendaItem responses)
- Individual agenda item clicking to trigger detail loading
- Resume support (tracks completed districts, skips on restart)
- 12 meetings per district, 24 months of history
"""

import sys
import json
import asyncio
import logging
import time
import re
import argparse
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

PROGRESS_FILE = Path(__file__).parent.parent / "data" / "scrape_progress.json"


def load_districts():
    with open(Path(__file__).parent.parent / "config" / "districts.json") as f:
        return json.load(f)


def parse_boarddocs_url(url):
    """Extract state_code and org_code from BoardDocs URL."""
    match = re.search(r'boarddocs\.com/(\w+)/(\w+)', url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def load_progress():
    """Load scrape progress tracking file."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": {}, "failed": []}


def save_progress(progress):
    """Save scrape progress tracking file."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2, default=str)


def get_meeting_list(state_code, org_code, months_back=24):
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
                                    district_id, max_meetings=12):
    """Scrape meetings for one district using shared browser context.

    Enhanced: captures BD-GetAgendaItem responses and clicks individual
    agenda items to trigger detail loading with vote blocks.
    """
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
            items_html = []

            async def capture_responses(response):
                nonlocal agenda_text
                url = response.url
                try:
                    if "BD-GetAgenda" in url and "Item" not in url:
                        agenda_text = await response.text()
                    elif "BD-GetAgendaItem" in url:
                        body = await response.text()
                        if body and len(body) > 10:
                            items_html.append(body)
                except:
                    pass

            page.on("response", capture_responses)

            url = f"{nsf_base}/goto?open&id={meeting['id']}"
            await page.goto(url, timeout=25000)
            await page.wait_for_timeout(4000)

            # Click individual agenda items to trigger BD-GetAgendaItem loading
            try:
                clickable = await page.query_selector_all(
                    'dd.item .item-title, dd .agenda-item-title, '
                    'dd.item a, dl dd[data-unique]'
                )
                click_count = 0
                for elem in clickable[:25]:
                    try:
                        await elem.click()
                        await page.wait_for_timeout(800)
                        click_count += 1
                    except:
                        continue
                if click_count > 0:
                    logger.debug(f"    Clicked {click_count} agenda items")
            except:
                pass

            body_text = ""
            try:
                body_text = await page.inner_text("body")
            except:
                pass

            # Try to load minutes view (contains actual vote results)
            minutes_text = ""
            minutes_html = []
            try:
                # Look for "View Minutes" or "Minutes" link
                minutes_link = await page.query_selector(
                    'a:has-text("Minutes"):not(:has-text("Approval")):not(:has-text("Approve"))'
                )
                if not minutes_link:
                    minutes_link = await page.query_selector(
                        'a[href*="minutes"], a[href*="Minutes"]'
                    )

                if minutes_link:
                    link_text = ""
                    try:
                        link_text = await minutes_link.inner_text()
                    except:
                        pass
                    # Only click if it looks like a "View Minutes" link, not an agenda item
                    if "minute" in link_text.lower() and len(link_text) < 30:
                        # Set up listener for minutes AJAX responses
                        async def capture_minutes_response(response):
                            url = response.url
                            try:
                                if "BD-GetMinutes" in url or "minutes" in url.lower():
                                    mbody = await response.text()
                                    if mbody and len(mbody) > 10:
                                        minutes_html.append(mbody)
                            except:
                                pass

                        page.on("response", capture_minutes_response)

                        await minutes_link.click()
                        await page.wait_for_timeout(4000)

                        try:
                            minutes_text = await page.inner_text("body")
                        except:
                            pass

                        # Remove the minutes response listener
                        page.remove_listener("response", capture_minutes_response)
            except Exception as e:
                logger.debug(f"    Minutes view not available: {e}")

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

            # Parse item detail HTML
            item_details = ""
            if items_html:
                detail_parts = []
                for html in items_html:
                    soup = BeautifulSoup(html, "lxml")
                    t = soup.get_text(separator="\n", strip=True)
                    if t and len(t) > 20:
                        detail_parts.append(f"\n--- Item Detail ---\n{t}")
                if detail_parts:
                    item_details = "\n".join(detail_parts)

            # Parse minutes AJAX HTML
            minutes_structured = ""
            if minutes_html:
                m_parts = []
                for html in minutes_html:
                    soup = BeautifulSoup(html, "lxml")
                    t = soup.get_text(separator="\n", strip=True)
                    if t and len(t) > 20:
                        m_parts.append(t)
                if m_parts:
                    minutes_structured = "\n".join(m_parts)

            full_text = f"District: {district_name}\nDate: {meeting['date']}\nMeeting: {meeting['name']}\n\n"
            if agenda_structured:
                full_text += "AGENDA:\n" + agenda_structured + "\n\n"
            if item_details:
                full_text += "ITEM DETAILS:" + item_details + "\n\n"
            full_text += "PAGE TEXT:\n" + body_text

            # Append minutes view content if captured
            if minutes_text and len(minutes_text) > 200:
                full_text += "\n\nMINUTES TEXT:\n" + minutes_text
            if minutes_structured:
                full_text += "\n\nMINUTES AJAX:\n" + minutes_structured

            await page.close()

            if len(full_text.strip()) > 200:
                # Save to disk
                safe_name = district_name.replace(" ", "_")[:40]
                date_str = meeting["date"].strftime("%Y-%m-%d")
                dir_path = RAW_MINUTES_DIR / district_id
                dir_path.mkdir(parents=True, exist_ok=True)
                file_path = dir_path / f"{safe_name}_{date_str}.txt"
                file_path.write_text(full_text, encoding="utf-8")

                item_count = len(items_html)
                results.append({
                    "date": str(meeting["date"]),
                    "name": meeting["name"],
                    "chars": len(full_text),
                    "items_captured": item_count,
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
    parser = argparse.ArgumentParser(description="Batch scrape BoardDocs districts")
    parser.add_argument("--state", type=str, help="Only scrape districts in this state")
    parser.add_argument("--district-id", type=str, help="Scrape a specific district")
    parser.add_argument("--max-meetings", type=int, default=12, help="Max meetings per district")
    parser.add_argument("--months-back", type=int, default=24, help="Months of history to scrape")
    parser.add_argument("--no-resume", action="store_true", help="Ignore progress file, rescrape all")
    parser.add_argument("--limit", type=int, help="Max districts to scrape")
    args = parser.parse_args()

    districts = load_districts()
    boarddocs_districts = [d for d in districts if d.get("platform") == "boarddocs"]

    if args.state:
        boarddocs_districts = [d for d in boarddocs_districts if d["state"] == args.state.upper()]
    if args.district_id:
        boarddocs_districts = [d for d in boarddocs_districts if d["district_id"] == args.district_id]
    if args.limit:
        boarddocs_districts = boarddocs_districts[:args.limit]

    # Load resume progress
    progress = load_progress() if not args.no_resume else {"completed": {}, "failed": []}

    # Filter out already-completed districts
    remaining = []
    skipped = 0
    for d in boarddocs_districts:
        if d["district_id"] in progress["completed"]:
            skipped += 1
        else:
            remaining.append(d)

    if skipped > 0:
        logger.info(f"Resuming: skipping {skipped} already-completed districts")

    logger.info(f"Starting batch scrape of {len(remaining)} BoardDocs districts "
                f"(max {args.max_meetings} meetings, {args.months_back} months back)")

    total_meetings = 0
    total_chars = 0
    total_items_captured = 0
    successful_districts = 0
    failed_districts = []
    all_results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )

        for i, district in enumerate(remaining, 1):
            name = district["district_name"]
            did = district["district_id"]
            url = district["minutes_url"]
            state_code, org_code = parse_boarddocs_url(url)

            if not state_code:
                logger.warning(f"[{i}/{len(remaining)}] Could not parse URL for {name}")
                failed_districts.append(name)
                continue

            logger.info(f"[{i}/{len(remaining)}] {name} ({district['state']})")

            # Get meeting list
            meetings = get_meeting_list(state_code, org_code, months_back=args.months_back)
            if not meetings:
                logger.warning(f"  No meetings found")
                failed_districts.append(name)
                continue

            nsf_base = f"https://go.boarddocs.com/{state_code}/{org_code}/Board.nsf"

            try:
                results = await scrape_district_meetings(
                    context, nsf_base, meetings, name, did,
                    max_meetings=args.max_meetings
                )

                if results:
                    successful_districts += 1
                    meeting_count = len(results)
                    char_count = sum(r["chars"] for r in results)
                    items_count = sum(r.get("items_captured", 0) for r in results)
                    total_meetings += meeting_count
                    total_chars += char_count
                    total_items_captured += items_count
                    all_results[did] = results
                    logger.info(f"  -> {meeting_count} meetings, {char_count:,} chars, "
                              f"{items_count} item details captured")

                    # Mark as completed in progress
                    progress["completed"][did] = {
                        "name": name,
                        "meetings": meeting_count,
                        "timestamp": datetime.now().isoformat(),
                    }
                    save_progress(progress)
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
    print(f"Successful districts: {successful_districts}/{len(remaining)}")
    print(f"Previously completed: {skipped}")
    print(f"Total meetings scraped: {total_meetings}")
    print(f"Total item details captured: {total_items_captured}")
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
            "total_items_captured": total_items_captured,
            "failed": failed_districts,
            "results": {k: v for k, v in all_results.items()},
        }, f, indent=2, default=str)


if __name__ == "__main__":
    asyncio.run(main())

"""CLI script to run scraping for specific districts or states."""

import sys
import json
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.district_discovery import load_districts, get_scraper_for_district
from config.settings import RAW_MINUTES_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log"),
    ]
)
logger = logging.getLogger(__name__)


def scrape_districts(districts: list[dict], months_back: int = 12) -> dict:
    """Scrape minutes for a list of districts."""
    results = {"success": [], "failed": [], "total_minutes": 0}

    for i, district in enumerate(districts, 1):
        name = district["district_name"]
        logger.info(f"\n[{i}/{len(districts)}] Scraping {name} ({district['state']})")

        try:
            scraper = get_scraper_for_district(district)
            minutes = scraper.scrape_all(months_back)

            if minutes:
                results["success"].append({
                    "district": name,
                    "state": district["state"],
                    "count": len(minutes),
                })
                results["total_minutes"] += len(minutes)
                logger.info(f"  -> Scraped {len(minutes)} meetings")
            else:
                results["failed"].append({
                    "district": name,
                    "reason": "No minutes found or extracted",
                })
                logger.warning(f"  -> No minutes found")
        except Exception as e:
            results["failed"].append({
                "district": name,
                "reason": str(e),
            })
            logger.error(f"  -> Failed: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Scrape school board meeting minutes")
    parser.add_argument("--state", type=str, help="Only scrape districts in this state")
    parser.add_argument("--platform", type=str, help="Only scrape districts using this platform")
    parser.add_argument("--district-id", type=str, help="Scrape a specific district by ID")
    parser.add_argument("--months", type=int, default=12, help="Months of history to scrape")
    parser.add_argument("--limit", type=int, help="Max number of districts to scrape")
    args = parser.parse_args()

    districts = load_districts()
    logger.info(f"Loaded {len(districts)} districts")

    if args.state:
        districts = [d for d in districts if d["state"] == args.state.upper()]
    if args.platform:
        districts = [d for d in districts if d.get("platform") == args.platform]
    if args.district_id:
        districts = [d for d in districts if d["district_id"] == args.district_id]
    if args.limit:
        districts = districts[:args.limit]

    if not districts:
        logger.error("No districts matched filters")
        return

    logger.info(f"Scraping {len(districts)} districts")
    results = scrape_districts(districts, args.months)

    print(f"\n{'='*60}")
    print(f"SCRAPING COMPLETE")
    print(f"{'='*60}")
    print(f"Successful: {len(results['success'])} districts, {results['total_minutes']} total minutes")
    print(f"Failed: {len(results['failed'])} districts")

    if results["failed"]:
        print(f"\nFailed districts:")
        for f in results["failed"]:
            print(f"  - {f['district']}: {f['reason']}")

    # Save results summary
    with open("scrape_results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()

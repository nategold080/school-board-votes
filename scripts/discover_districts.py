"""Discover and validate new BoardDocs districts across additional states.

Validates BoardDocs org codes via the SEO endpoint (GET, ~2 seconds each).
Adds validated districts to config/districts.json.

Usage:
    python scripts/discover_districts.py                    # Discover all target states
    python scripts/discover_districts.py --state PA         # Discover one state
    python scripts/discover_districts.py --validate-only    # Just validate, don't add
"""

import sys
import json
import time
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DISTRICTS_FILE = Path(__file__).parent.parent / "config" / "districts.json"

# Known BoardDocs org codes by state.
# These are publicly accessible BoardDocs organizations.
# Format: (org_code, district_name, estimated_enrollment, county)
CANDIDATE_DISTRICTS = {
    "PA": [
        ("phil", "School District of Philadelphia", 120000, "Philadelphia"),
        ("pitps", "Pittsburgh Public Schools", 20000, "Allegheny"),
        ("sdah", "School District of Abington Heights", 3500, "Lackawanna"),
        ("psdnj", "Pennsbury School District", 10000, "Bucks"),
        ("wssd", "West Shore School District", 8000, "Cumberland"),
        ("hasd", "Hatboro-Horsham School District", 5500, "Montgomery"),
        ("bcsd", "Bethlehem Area School District", 14000, "Northampton"),
        ("rcsd", "Reading School District", 18000, "Berks"),
    ],
    "CT": [
        ("nhps", "New Haven Public Schools", 20000, "New Haven"),
        ("hartfordct", "Hartford Public Schools", 18000, "Hartford"),
        ("brdgpt", "Bridgeport Public Schools", 19000, "Fairfield"),
        ("stam", "Stamford Public Schools", 16000, "Fairfield"),
        ("greenwich", "Greenwich Public Schools", 9000, "Fairfield"),
        ("danbury", "Danbury Public Schools", 12000, "Fairfield"),
    ],
    "NJ": [
        ("nwkboe", "Newark Board of Education", 36000, "Essex"),
        ("jcboe", "Jersey City Board of Education", 30000, "Hudson"),
        ("teaneck", "Teaneck Public Schools", 4000, "Bergen"),
        ("mtnsd", "Montclair Board of Education", 6500, "Essex"),
        ("eboe", "Elizabeth Board of Education", 28000, "Union"),
        ("wfield", "Westfield Public Schools", 6000, "Union"),
    ],
    "IL": [
        ("cps", "Chicago Public Schools", 330000, "Cook"),
        ("u46", "School District U-46 (Elgin)", 38000, "Kane"),
        ("dist214", "Township HSD 214", 12000, "Cook"),
        ("isd204", "Indian Prairie School District 204", 28000, "DuPage"),
        ("d300", "Community Unit School District 300", 21000, "Kane"),
        ("springfield", "Springfield SD 186", 14000, "Sangamon"),
    ],
    "MI": [
        ("dps", "Detroit Public Schools", 50000, "Wayne"),
        ("grps", "Grand Rapids Public Schools", 15000, "Kent"),
        ("aaps", "Ann Arbor Public Schools", 17000, "Washtenaw"),
        ("kps", "Kalamazoo Public Schools", 12000, "Kalamazoo"),
        ("lps", "Lansing School District", 11000, "Ingham"),
        ("bps", "Birmingham Public Schools", 8000, "Oakland"),
    ],
    "WI": [
        ("mps", "Milwaukee Public Schools", 69000, "Milwaukee"),
        ("mmsd", "Madison Metropolitan School District", 27000, "Dane"),
        ("ksd", "Kenosha Unified School District", 20000, "Kenosha"),
        ("gbaps", "Green Bay Area Public Schools", 20000, "Brown"),
        ("rsd", "Racine Unified School District", 17000, "Racine"),
    ],
    "GA": [
        ("aps", "Atlanta Public Schools", 52000, "Fulton"),
        ("gcps", "Gwinnett County Public Schools", 180000, "Gwinnett"),
        ("dekalbga", "DeKalb County School District", 94000, "DeKalb"),
        ("cobbk12", "Cobb County School District", 107000, "Cobb"),
        ("fcsboe", "Fulton County Schools", 95000, "Fulton"),
        ("ccsd", "Clayton County Public Schools", 56000, "Clayton"),
    ],
    "NC": [
        ("cms", "Charlotte-Mecklenburg Schools", 147000, "Mecklenburg"),
        ("wcpss", "Wake County Public Schools", 160000, "Wake"),
        ("gcsnc", "Guilford County Schools", 72000, "Guilford"),
        ("wsfcs", "Winston-Salem/Forsyth County Schools", 55000, "Forsyth"),
        ("dps", "Durham Public Schools", 33000, "Durham"),
        ("nhcs", "New Hanover County Schools", 28000, "New Hanover"),
    ],
    "MD": [
        ("bcps", "Baltimore County Public Schools", 111000, "Baltimore"),
        ("pgcps", "Prince George's County Public Schools", 130000, "Prince George's"),
        ("aacps", "Anne Arundel County Public Schools", 85000, "Anne Arundel"),
        ("mcps", "Montgomery County Public Schools", 160000, "Montgomery"),
        ("hcpss", "Howard County Public Schools", 58000, "Howard"),
        ("fcps", "Frederick County Public Schools", 44000, "Frederick"),
    ],
    "WA": [
        ("sps", "Seattle Public Schools", 50000, "King"),
        ("tpsd", "Tacoma Public Schools", 28000, "Pierce"),
        ("spokaneschools", "Spokane Public Schools", 30000, "Spokane"),
        ("bsd", "Bellevue School District", 20000, "King"),
        ("kent", "Kent School District", 27000, "King"),
        ("esd", "Everett Public Schools", 20000, "Snohomish"),
    ],
    "AZ": [
        ("tuhsd", "Tempe Union HSD", 13000, "Maricopa"),
        ("musd", "Mesa Unified School District", 60000, "Maricopa"),
        ("tusd", "Tucson Unified School District", 43000, "Pima"),
        ("dvusd", "Deer Valley Unified School District", 33000, "Maricopa"),
        ("pusd", "Peoria Unified School District", 35000, "Maricopa"),
        ("cusd", "Chandler Unified School District", 45000, "Maricopa"),
    ],
    "MO": [
        ("slps", "St. Louis Public Schools", 20000, "St. Louis City"),
        ("kcps", "Kansas City Public Schools", 14000, "Jackson"),
        ("lsr7", "Lee's Summit R-7", 18000, "Jackson"),
        ("fhsd", "Francis Howell School District", 17000, "St. Charles"),
        ("pkwy", "Parkway School District", 17000, "St. Louis"),
        ("rsd", "Rockwood School District", 21000, "St. Louis"),
    ],
    "ID": [
        ("boiseschools", "Boise School District", 25000, "Ada"),
        ("westada", "West Ada School District", 40000, "Ada"),
        ("d91", "Idaho Falls School District 91", 12000, "Bonneville"),
        ("d93", "Bonneville Joint School District 93", 13000, "Bonneville"),
        ("nsd", "Nampa School District", 15000, "Canyon"),
    ],
}


def validate_org_code(state_code, org_code, timeout=10):
    """Check if a BoardDocs org code is valid by hitting the SEO endpoint."""
    url = f"https://go.boarddocs.com/{state_code}/{org_code}/Board.nsf/BD-GETMeetingsListForSEO?open&0.1"
    try:
        resp = requests.get(url, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0 SchoolBoardResearch/1.0"})
        if resp.status_code == 200 and resp.text:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return True, len(data)
    except:
        pass
    return False, 0


def load_existing_districts():
    """Load current districts.json."""
    if DISTRICTS_FILE.exists():
        with open(DISTRICTS_FILE) as f:
            return json.load(f)
    return []


def save_districts(districts):
    """Save districts.json."""
    with open(DISTRICTS_FILE, "w") as f:
        json.dump(districts, f, indent=2)


def generate_district_id(state, index):
    """Generate a unique district ID for new discoveries."""
    state_prefix = {
        "PA": "42", "CT": "09", "NJ": "34", "IL": "17", "MI": "26",
        "WI": "55", "GA": "13", "NC": "37", "MD": "24", "WA": "53",
        "AZ": "04", "MO": "29", "ID": "16",
    }
    prefix = state_prefix.get(state, "99")
    return f"{prefix}90{index:03d}"


def discover_state(state, validate_only=False):
    """Discover valid BoardDocs districts for a state."""
    candidates = CANDIDATE_DISTRICTS.get(state, [])
    if not candidates:
        logger.warning(f"No candidates defined for state {state}")
        return []

    valid = []
    logger.info(f"Validating {len(candidates)} candidates for {state}...")

    for org_code, name, enrollment, county in candidates:
        is_valid, meeting_count = validate_org_code(state.lower(), org_code)
        time.sleep(1)  # Be polite

        if is_valid:
            logger.info(f"  VALID: {name} ({org_code}) - {meeting_count} meetings")
            valid.append({
                "org_code": org_code,
                "district_name": name,
                "enrollment": enrollment,
                "county": county,
                "meeting_count": meeting_count,
            })
        else:
            logger.info(f"  SKIP:  {name} ({org_code}) - not found on BoardDocs")

    logger.info(f"  {state}: {len(valid)}/{len(candidates)} valid")
    return valid


def main():
    parser = argparse.ArgumentParser(description="Discover new BoardDocs districts")
    parser.add_argument("--state", type=str, help="Only discover for this state")
    parser.add_argument("--validate-only", action="store_true",
                       help="Just validate, don't modify districts.json")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be added without modifying files")
    args = parser.parse_args()

    existing = load_existing_districts()
    existing_urls = {d["minutes_url"] for d in existing}
    existing_ids = {d["district_id"] for d in existing}

    target_states = [args.state.upper()] if args.state else list(CANDIDATE_DISTRICTS.keys())

    all_new = []
    for state in target_states:
        valid = discover_state(state, validate_only=args.validate_only)

        for i, d in enumerate(valid, 1):
            url = f"https://go.boarddocs.com/{state.lower()}/{d['org_code']}/Board.nsf/Public"
            if url in existing_urls:
                logger.info(f"  Already exists: {d['district_name']}")
                continue

            district_id = generate_district_id(state, i)
            while district_id in existing_ids:
                i += 10
                district_id = generate_district_id(state, i)

            new_district = {
                "district_id": district_id,
                "district_name": d["district_name"],
                "state": state,
                "enrollment": d["enrollment"],
                "county": d["county"],
                "minutes_url": url,
                "platform": "boarddocs",
            }
            all_new.append(new_district)
            existing_ids.add(district_id)
            existing_urls.add(url)

    print(f"\n{'='*60}")
    print(f"DISCOVERY COMPLETE")
    print(f"{'='*60}")
    print(f"New districts found: {len(all_new)}")
    for state in target_states:
        count = sum(1 for d in all_new if d["state"] == state)
        if count > 0:
            print(f"  {state}: {count}")

    if all_new and not args.validate_only and not args.dry_run:
        existing.extend(all_new)
        save_districts(existing)
        print(f"\nSaved {len(existing)} total districts to {DISTRICTS_FILE}")
    elif args.dry_run:
        print("\nDry run - no files modified. New districts would be:")
        for d in all_new:
            print(f"  [{d['state']}] {d['district_name']} ({d['minutes_url']})")


if __name__ == "__main__":
    main()

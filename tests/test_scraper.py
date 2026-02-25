"""Tests for the scraper module.

Tests URL construction, meeting type classification, date parsing,
and name validation without requiring network access or Playwright.
"""

import sys
import pytest
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.boarddocs_scraper import BoardDocsScraper
from scraper.base_scraper import MeetingMinutes


class TestBoardDocsURLConstruction:
    """Test BoardDocs URL construction from base URL."""

    def test_extract_state_and_org(self):
        scraper = BoardDocsScraper(
            district_id="001",
            district_name="Test District",
            base_url="https://go.boarddocs.com/ny/nrochelle/Board.nsf"
        )
        assert scraper.bd_state == "ny"
        assert scraper.bd_org == "nrochelle"

    def test_nsf_base_url(self):
        scraper = BoardDocsScraper(
            district_id="002",
            district_name="Test District 2",
            base_url="https://go.boarddocs.com/ca/sdusd/Board.nsf"
        )
        assert scraper._nsf_base == "https://go.boarddocs.com/ca/sdusd/Board.nsf"

    def test_invalid_url_empty_state_org(self):
        scraper = BoardDocsScraper(
            district_id="003",
            district_name="Bad URL District",
            base_url="https://example.com/not-boarddocs"
        )
        assert scraper.bd_state == ""
        assert scraper.bd_org == ""

    def test_texas_url(self):
        scraper = BoardDocsScraper(
            district_id="004",
            district_name="Houston ISD",
            base_url="https://go.boarddocs.com/tx/hisd/Board.nsf"
        )
        assert scraper.bd_state == "tx"
        assert scraper.bd_org == "hisd"


class TestMeetingTypeClassification:
    """Test _classify_meeting_type static method."""

    def test_regular_meeting(self):
        assert BoardDocsScraper._classify_meeting_type("Regular Board Meeting") == "regular"

    def test_special_meeting(self):
        assert BoardDocsScraper._classify_meeting_type("Special Board Meeting") == "special"

    def test_emergency_meeting(self):
        assert BoardDocsScraper._classify_meeting_type("Emergency Session") == "emergency"

    def test_work_session(self):
        assert BoardDocsScraper._classify_meeting_type("Board Work Session") == "work_session"

    def test_workshop(self):
        assert BoardDocsScraper._classify_meeting_type("Workshop Meeting") == "work_session"

    def test_retreat(self):
        assert BoardDocsScraper._classify_meeting_type("Board Retreat") == "work_session"

    def test_default_is_regular(self):
        assert BoardDocsScraper._classify_meeting_type("Monthly Meeting") == "regular"


class TestDateParsing:
    """Test _parse_seo_date static method."""

    def test_iso_date(self):
        result = BoardDocsScraper._parse_seo_date("2025-01-15T00:00:00Z")
        assert result == date(2025, 1, 15)

    def test_iso_date_no_z(self):
        result = BoardDocsScraper._parse_seo_date("2025-06-01T19:00:00")
        assert result == date(2025, 6, 1)

    def test_empty_string(self):
        result = BoardDocsScraper._parse_seo_date("")
        assert result is None

    def test_none_input(self):
        result = BoardDocsScraper._parse_seo_date(None)
        assert result is None

    def test_invalid_date(self):
        result = BoardDocsScraper._parse_seo_date("not-a-date")
        assert result is None


class TestMeetingMinutesDataclass:
    """Test the MeetingMinutes dataclass."""

    def test_create_meeting_minutes(self):
        mm = MeetingMinutes(
            district_id="001",
            meeting_date=date(2025, 1, 15),
            meeting_type="regular",
            source_url="https://example.com/meeting",
            raw_text="Meeting text content here",
        )
        assert mm.district_id == "001"
        assert mm.meeting_date == date(2025, 1, 15)
        assert mm.meeting_type == "regular"
        assert mm.file_path is None

    def test_default_file_path_none(self):
        mm = MeetingMinutes(
            district_id="002",
            meeting_date=date(2025, 2, 1),
            meeting_type="special",
            source_url="https://example.com",
            raw_text="Text",
        )
        assert mm.file_path is None

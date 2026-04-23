"""
tests/test_routing.py
---------------------
Verifies that:
  1. Tab names always follow "YYYY Type Month" format.
  2. Records with old/different dates route to the correct tab.
  3. _get_or_create_tab REUSES an existing worksheet — never creates a duplicate.
  4. Bulk inserts group records by month so only one API call per tab.
  5. Mixed-date bulk inserts create exactly the right set of tabs (no extras).
  6. Sales records route to "Sales" tabs; expenses to "Expenses" tabs.

Run with:
  cd Business_Tracker_Bot
  python -m pytest tests/test_routing.py -v
"""

import sys
import os

# Allow imports from parent directory without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from unittest.mock import MagicMock, patch, call
import pytest

import gspread

from message_parser import ExpenseRecord, SalesRecord
from sheets_manager import (
    _tab_name,
    _record_dt,
    _get_or_create_tab,
    _bulk_insert_grouped,
    SheetsManager,
)


# ─────────────────────────── Fixtures ─────────────────────────────────────────

def _make_expense(date: str, amount: float = 100.0) -> ExpenseRecord:
    return ExpenseRecord(
        date=date, name="Test Item", category="General",
        supplier="Supplier", amount=amount,
        invoice_no="#1", payment_method="Cash", notes="",
    )


def _make_sale(date: str, amount: float = 200.0) -> SalesRecord:
    return SalesRecord(
        date=date, name="Test Sale", category="General",
        customer="Customer", amount=amount,
        invoice_no="#2", payment_method="Cash", notes="",
    )


def _mock_sheet(existing_tabs: list[str] | None = None):
    """
    Return a fake gspread.Spreadsheet.

    existing_tabs: list of tab names that already exist.
      - worksheet(name) returns a mock if name is in existing_tabs,
        raises WorksheetNotFound otherwise.
    """
    existing = set(existing_tabs or [])
    sheet    = MagicMock(spec=gspread.Spreadsheet)
    sheet.url = "https://docs.google.com/spreadsheets/d/FAKE"

    def fake_worksheet(name):
        if name in existing:
            ws      = MagicMock(spec=gspread.Worksheet)
            ws.id   = 999
            ws.get_all_values.return_value = [["#", "Date"]]  # header row = 1 row
            ws.spreadsheet = sheet
            return ws
        raise gspread.WorksheetNotFound(name)

    sheet.worksheet.side_effect = fake_worksheet

    def fake_add_worksheet(title, rows, cols):
        existing.add(title)
        ws      = MagicMock(spec=gspread.Worksheet)
        ws.id   = 1000 + len(existing)
        ws.get_all_values.return_value = [["#", "Date"]]
        ws.spreadsheet = sheet
        return ws

    sheet.add_worksheet.side_effect = fake_add_worksheet
    return sheet


# ─────────────────────────── _tab_name ────────────────────────────────────────

class TestTabName:
    def test_expenses_current_month(self):
        now  = datetime.now()
        name = _tab_name("Expenses")
        assert name == f"{now.year} Expenses {now.strftime('%B')}"

    def test_sales_current_month(self):
        now  = datetime.now()
        name = _tab_name("Sales")
        assert name == f"{now.year} Sales {now.strftime('%B')}"

    def test_old_date_march(self):
        dt   = datetime(2026, 3, 15)
        name = _tab_name("Expenses", dt)
        assert name == "2026 Expenses March"

    def test_sales_old_date(self):
        dt   = datetime(2025, 11, 1)
        name = _tab_name("Sales", dt)
        assert name == "2025 Sales November"

    def test_format_is_year_type_month(self):
        dt   = datetime(2026, 4, 1)
        name = _tab_name("Expenses", dt)
        parts = name.split()
        assert parts[0] == "2026"
        assert parts[1] == "Expenses"
        assert parts[2] == "April"


# ─────────────────────────── _record_dt ───────────────────────────────────────

class TestRecordDt:
    def test_valid_date(self):
        dt = _record_dt("2026-03-15")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15

    def test_january(self):
        dt = _record_dt("2025-01-01")
        assert dt.month == 1

    def test_invalid_falls_back_to_now(self):
        dt  = _record_dt("not-a-date")
        now = datetime.now()
        assert dt.year == now.year
        assert dt.month == now.month

    def test_empty_falls_back_to_now(self):
        dt  = _record_dt("")
        now = datetime.now()
        assert dt.year == now.year


# ─────────────────────────── _get_or_create_tab ───────────────────────────────

class TestGetOrCreateTab:
    def test_reuses_existing_tab(self):
        """If the tab already exists, worksheet() is returned with NO add_worksheet call."""
        sheet = _mock_sheet(existing_tabs=["2026 Expenses March"])
        ws    = _get_or_create_tab(sheet, "2026 Expenses March", ExpenseRecord)
        assert ws is not None
        sheet.add_worksheet.assert_not_called()   # <── KEY assertion

    def test_creates_missing_tab(self):
        """If the tab is absent, add_worksheet is called exactly once."""
        sheet = _mock_sheet(existing_tabs=[])
        ws    = _get_or_create_tab(sheet, "2026 Expenses April", ExpenseRecord)
        assert ws is not None
        sheet.add_worksheet.assert_called_once()

    def test_existing_tab_called_with_correct_name(self):
        sheet = _mock_sheet(existing_tabs=["2026 Sales November"])
        _get_or_create_tab(sheet, "2026 Sales November", SalesRecord)
        sheet.worksheet.assert_called_with("2026 Sales November")

    def test_expense_tab_not_created_for_sales(self):
        """Expense tab and Sales tab are independent — one existing doesn't affect the other."""
        sheet = _mock_sheet(existing_tabs=["2026 Expenses March"])
        _get_or_create_tab(sheet, "2026 Sales March", SalesRecord)
        # Sales tab didn't exist, so add_worksheet must be called
        sheet.add_worksheet.assert_called_once()


# ─────────────────────────── SheetsManager.add_expense ───────────────────────

class TestAddExpense:
    def _make_sm(self, existing_tabs=None):
        sm = SheetsManager.__new__(SheetsManager)
        sm.spreadsheet = _mock_sheet(existing_tabs)
        return sm

    def test_old_date_routes_to_correct_tab(self):
        """An expense dated March routes to '2026 Expenses March', not the current month."""
        sm     = self._make_sm(existing_tabs=["2026 Expenses March"])
        record = _make_expense("2026-03-10")
        result = sm.add_expense(record)
        assert result["tab"] == "2026 Expenses March"

    def test_existing_tab_not_duplicated(self):
        sm     = self._make_sm(existing_tabs=["2026 Expenses March"])
        record = _make_expense("2026-03-10")
        sm.add_expense(record)
        # worksheet() was called (tab found), add_worksheet was NOT called
        sm.spreadsheet.worksheet.assert_called_with("2026 Expenses March")
        sm.spreadsheet.add_worksheet.assert_not_called()

    def test_new_tab_created_only_once_on_first_insert(self):
        sm     = self._make_sm(existing_tabs=[])
        record = _make_expense("2026-01-05")
        sm.add_expense(record)
        sm.spreadsheet.add_worksheet.assert_called_once()


# ─────────────────────────── SheetsManager.add_sale ──────────────────────────

class TestAddSale:
    def _make_sm(self, existing_tabs=None):
        sm = SheetsManager.__new__(SheetsManager)
        sm.spreadsheet = _mock_sheet(existing_tabs)
        return sm

    def test_routes_to_sales_tab(self):
        sm     = self._make_sm(existing_tabs=["2026 Sales March"])
        record = _make_sale("2026-03-20")
        result = sm.add_sale(record)
        assert "Sales" in result["tab"]
        assert "March" in result["tab"]

    def test_does_not_touch_expense_tab(self):
        sm = self._make_sm(existing_tabs=["2026 Expenses March"])
        record = _make_sale("2026-03-20")
        sm.add_sale(record)
        # Only "2026 Sales March" should be touched
        assert all("Sales" in str(c) for c in sm.spreadsheet.worksheet.call_args_list)


# ─────────────────────────── Bulk insert — dedup ──────────────────────────────

class TestBulkInsertDedup:
    def _make_sm(self, existing_tabs=None):
        sm = SheetsManager.__new__(SheetsManager)
        sm.spreadsheet = _mock_sheet(existing_tabs)
        return sm

    def test_same_month_records_use_one_tab(self):
        """10 records all in March → tab looked up once, append_rows called once."""
        sm      = self._make_sm(existing_tabs=["2026 Expenses March"])
        records = [_make_expense("2026-03-0" + str(d)) for d in range(1, 6)]
        records += [_make_expense("2026-03-1" + str(d)) for d in range(0, 5)]
        sm.add_expenses_bulk(records)
        # worksheet() called exactly once for "2026 Expenses March"
        sm.spreadsheet.worksheet.assert_called_once_with("2026 Expenses March")
        # add_worksheet never called (tab existed)
        sm.spreadsheet.add_worksheet.assert_not_called()

    def test_no_duplicate_tabs_on_repeated_bulk_insert(self):
        """Calling add_expenses_bulk twice for the same month must not create the tab twice."""
        sm      = self._make_sm(existing_tabs=[])
        records = [_make_expense("2026-04-01"), _make_expense("2026-04-02")]
        sm.add_expenses_bulk(records)
        # After first insert the tab now exists (mock updated existing set)
        sm.add_expenses_bulk(records)
        # add_worksheet should have been called once total (first insert), not twice
        assert sm.spreadsheet.add_worksheet.call_count == 1


# ─────────────────────────── Bulk insert — mixed months ───────────────────────

class TestBulkInsertMixedMonths:
    def _make_sm(self, existing_tabs=None):
        sm = SheetsManager.__new__(SheetsManager)
        sm.spreadsheet = _mock_sheet(existing_tabs)
        return sm

    def test_records_split_into_correct_tabs(self):
        """Records from March and April go to separate tabs."""
        sm = self._make_sm(existing_tabs=[
            "2026 Expenses March",
            "2026 Expenses April",
        ])
        records = [
            _make_expense("2026-03-10"),
            _make_expense("2026-03-15"),
            _make_expense("2026-04-01"),
            _make_expense("2026-04-05"),
        ]
        result = sm.add_expenses_bulk(records)
        assert result["count"] == 4
        # Both tabs should have been accessed
        accessed_tabs = {c.args[0] for c in sm.spreadsheet.worksheet.call_args_list}
        assert "2026 Expenses March" in accessed_tabs
        assert "2026 Expenses April" in accessed_tabs

    def test_three_months_creates_three_tabs(self):
        """40 invoices spanning Jan/Feb/Mar → exactly 3 tabs, no duplicates."""
        sm      = self._make_sm(existing_tabs=[])
        records = (
            [_make_expense("2026-01-0" + str(i)) for i in range(1, 8)] +
            [_make_expense("2026-02-0" + str(i)) for i in range(1, 8)] +
            [_make_expense("2026-03-0" + str(i)) for i in range(1, 8)]
        )
        sm.add_expenses_bulk(records)
        # Exactly 3 new tabs should have been created
        assert sm.spreadsheet.add_worksheet.call_count == 3
        created_names = {c.kwargs.get("title") or c.args[0]
                         for c in sm.spreadsheet.add_worksheet.call_args_list}
        assert "2026 Expenses January"  in created_names
        assert "2026 Expenses February" in created_names
        assert "2026 Expenses March"    in created_names

    def test_sales_and_expenses_never_share_tab(self):
        """Sales and expense records for the same month go to DIFFERENT tabs."""
        sm      = self._make_sm(existing_tabs=[])
        exp_rec = _make_expense("2026-04-01")
        sal_rec = _make_sale("2026-04-01")
        sm.add_expense(exp_rec)
        sm.add_sale(sal_rec)
        created = [c.kwargs.get("title") or c.args[0]
                   for c in sm.spreadsheet.add_worksheet.call_args_list]
        assert "2026 Expenses April" in created
        assert "2026 Sales April"    in created
        assert len(created) == 2   # No extras


# ─────────────────────────── Run summary ──────────────────────────────────────

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

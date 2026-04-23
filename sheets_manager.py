"""
sheets_manager.py
-----------------
Google Sheets operations.

Sheet tab naming convention:
  "2026 Expenses April"   ← expenses for April 2026
  "2026 Sales April"      ← sales for April 2026

Tab routing uses the DATE on the record, not today's date.
If an invoice from March is uploaded in April, it goes to "2026 Expenses March".
For multi-invoice PDFs that span multiple months, records are grouped per
month tab automatically.

SaaS mode: every call passes in the user's own credentials + spreadsheet ID.
Single-user fallback: reads from env vars / credentials.json (original behaviour).
"""

import base64
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from message_parser import ExpenseRecord, SalesRecord

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Tab / header colours
EXPENSE_HEADER_BG = {"red": 0.13, "green": 0.37, "blue": 0.64}   # blue
EXPENSE_TAB_COLOR = {"red": 0.13, "green": 0.37, "blue": 0.64}
SALES_HEADER_BG   = {"red": 0.13, "green": 0.55, "blue": 0.30}   # green
SALES_TAB_COLOR   = {"red": 0.13, "green": 0.55, "blue": 0.30}
HEADER_FONT       = {"red": 1.0,  "green": 1.0,  "blue": 1.0}    # white


# ─────────────────────────── Auth helpers ─────────────────────────────────────

def _client_from_dict(creds_dict: dict) -> gspread.Client:
    """Authorise using a service-account credentials dictionary."""
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _client_from_env() -> gspread.Client:
    """Authorise from environment variable or local file (legacy single-user)."""
    creds_json_b64 = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json_b64:
        info  = json.loads(base64.b64decode(creds_json_b64).decode())
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        path  = os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json")
        creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)


# ─────────────────────────── Tab name helpers ─────────────────────────────────

def _record_dt(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD record date string into a datetime. Falls back to now."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return datetime.now()


def _tab_name(sheet_type: str = "Expenses", dt: Optional[datetime] = None) -> str:
    """
    Returns a tab name like:  '2026 Expenses April'
                          or:  '2026 Sales April'
    Uses the record's actual date (not today) when dt is supplied.
    """
    dt = dt or datetime.now()
    return f"{dt.year} {sheet_type} {dt.strftime('%B')}"


def _get_or_create_tab(
    sheet: gspread.Spreadsheet,
    tab_name: str,
    record_cls=None,
) -> gspread.Worksheet:
    """Return the worksheet with tab_name, creating it (with headers) if absent."""
    if record_cls is None:
        record_cls = ExpenseRecord
    try:
        return sheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        headers  = record_cls.headers()
        ws       = sheet.add_worksheet(title=tab_name, rows=2000, cols=len(headers))
        is_sales = "Sales" in tab_name
        _write_headers(ws, headers, is_sales=is_sales)
        return ws


def _write_headers(ws: gspread.Worksheet, headers: list, is_sales: bool = False) -> None:
    header_bg = SALES_HEADER_BG if is_sales else EXPENSE_HEADER_BG
    tab_color = SALES_TAB_COLOR if is_sales else EXPENSE_TAB_COLOR

    ws.append_row(headers, value_input_option="USER_ENTERED")
    ws.freeze(rows=1)
    sid = ws.id
    ws.spreadsheet.batch_update({"requests": [
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": header_bg,
                "textFormat": {"bold": True, "foregroundColor": HEADER_FONT},
                "horizontalAlignment": "CENTER",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": sid, "tabColor": tab_color},
            "fields": "tabColor",
        }},
        {"autoResizeDimensions": {
            "dimensions": {"sheetId": sid, "dimension": "COLUMNS",
                           "startIndex": 0, "endIndex": len(headers)},
        }},
    ]})


def _next_row_number(ws: gspread.Worksheet) -> int:
    return len(ws.get_all_values())


def _bulk_insert_grouped(
    sheet: gspread.Spreadsheet,
    records: list,
    sheet_type: str,   # "Expenses" or "Sales"
    record_cls,
) -> dict:
    """
    Group records by their month tab (using each record's own date),
    then append_rows into the correct tab — one API call per tab.

    Returns a summary dict with count, tab(s), and url.
    """
    # Group by tab name so invoices from different months go to the right tab
    groups: dict[str, list] = defaultdict(list)
    for r in records:
        tab = _tab_name(sheet_type, _record_dt(r.date))
        groups[tab].append(r)

    tabs_written = []
    for tab_name, group in groups.items():
        ws       = _get_or_create_tab(sheet, tab_name, record_cls)
        start_no = _next_row_number(ws)
        rows     = [[start_no + i] + r.to_row() for i, r in enumerate(group)]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        tabs_written.append(tab_name)

    tab_label = tabs_written[0] if len(tabs_written) == 1 else f"{len(tabs_written)} tabs"
    return {
        "tab":   tab_label,
        "tabs":  tabs_written,
        "count": len(records),
        "url":   sheet.url,
    }


# ─────────────────────────── Summary helper ───────────────────────────────────

def _sum_tab(sheet: gspread.Spreadsheet, tab_name: str) -> tuple[float, int]:
    """Return (total_amount, row_count) for a given tab. Silently handles missing tabs."""
    try:
        ws    = sheet.worksheet(tab_name)
        rows  = ws.get_all_values()[1:]   # skip header
        total = 0.0
        count = 0
        for row in rows:
            if len(row) > 5 and row[5]:
                try:
                    total += float(str(row[5]).replace(",", ""))
                    count += 1
                except ValueError:
                    pass
        return total, count
    except gspread.WorksheetNotFound:
        return 0.0, 0


# ─────────────────────────── SheetsManager ────────────────────────────────────

class SheetsManager:
    """
    Wraps a single user's Google Spreadsheet.

    Usage (SaaS — per-user credentials from DB):
        sm = SheetsManager.for_user(user_row)

    Usage (legacy single-user — env/file credentials):
        sm = SheetsManager()
    """

    def __init__(self, creds_dict: Optional[dict] = None, spreadsheet_id: Optional[str] = None):
        if creds_dict:
            client = _client_from_dict(creds_dict)
        else:
            client = _client_from_env()

        if spreadsheet_id:
            self.spreadsheet = client.open_by_key(spreadsheet_id)
        else:
            title = os.environ.get("SPREADSHEET_TITLE", "Business Tracker 2026")
            sid   = os.environ.get("SPREADSHEET_ID", "")
            self.spreadsheet = (
                client.open_by_key(sid) if sid else client.open(title)
            )

    # ── Expense write operations ────────────────────────────────────────────

    def add_expense(self, record: ExpenseRecord) -> dict:
        """Insert one expense. Tab is determined by the record's own date."""
        dt       = _record_dt(record.date)
        tab_name = _tab_name("Expenses", dt)
        ws       = _get_or_create_tab(self.spreadsheet, tab_name, ExpenseRecord)
        row_no   = _next_row_number(ws)
        ws.append_row([row_no] + record.to_row(), value_input_option="USER_ENTERED")
        return {"tab": tab_name, "row": row_no, "url": self.spreadsheet.url}

    def add_expenses_bulk(self, records: list[ExpenseRecord]) -> dict:
        """
        Insert expense records. Each record goes to the tab matching ITS date.
        Records from different months end up in different tabs automatically.
        """
        if not records:
            return {"tab": "", "count": 0, "url": self.spreadsheet.url}
        return _bulk_insert_grouped(self.spreadsheet, records, "Expenses", ExpenseRecord)

    # ── Sales write operations ──────────────────────────────────────────────

    def add_sale(self, record: SalesRecord) -> dict:
        """Insert one sale. Tab is determined by the record's own date."""
        dt       = _record_dt(record.date)
        tab_name = _tab_name("Sales", dt)
        ws       = _get_or_create_tab(self.spreadsheet, tab_name, SalesRecord)
        row_no   = _next_row_number(ws)
        ws.append_row([row_no] + record.to_row(), value_input_option="USER_ENTERED")
        return {"tab": tab_name, "row": row_no, "url": self.spreadsheet.url}

    def add_sales_bulk(self, records: list[SalesRecord]) -> dict:
        """
        Insert sales records. Each record goes to the tab matching ITS date.
        """
        if not records:
            return {"tab": "", "count": 0, "url": self.spreadsheet.url}
        return _bulk_insert_grouped(self.spreadsheet, records, "Sales", SalesRecord)

    # ── Read / summary operations ───────────────────────────────────────────

    def get_monthly_summary(self, month_arg: Optional[str] = None) -> dict:
        """
        Return totals for the given month (both expenses and sales).

        month_arg examples: None (current), "April 2026", "2026 April"
        """
        now   = datetime.now()
        year  = now.year
        mname = now.strftime("%B")   # e.g. "April"

        if month_arg:
            for part in month_arg.split():
                if part.isdigit() and len(part) == 4:
                    year = int(part)
                elif len(part) > 2:
                    mname = part.capitalize()

        exp_tab  = f"{year} Expenses {mname}"
        sale_tab = f"{year} Sales {mname}"

        exp_total,  exp_count  = _sum_tab(self.spreadsheet, exp_tab)
        sale_total, sale_count = _sum_tab(self.spreadsheet, sale_tab)

        return {
            "month":      f"{mname} {year}",
            "exp_tab":    exp_tab,
            "sale_tab":   sale_tab,
            "exp_total":  exp_total,
            "exp_count":  exp_count,
            "sale_total": sale_total,
            "sale_count": sale_count,
        }

    @property
    def url(self) -> str:
        return self.spreadsheet.url

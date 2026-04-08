"""Export crawled data to CSV and Excel."""

import csv
import os
from datetime import datetime
from openpyxl import Workbook
from config import OUTPUT_DIR

FIELDS = [
    "tax_id",
    "company_name",
    "international_name",
    "short_name",
    "representative",
    "tax_address",
    "address",
    "phone",
    "status",
    "company_type",
    "start_date",
    "tax_authority",
    "main_business",
    "detail_url",
]

FIELD_LABELS = {
    "tax_id": "Mã số thuế",
    "company_name": "Tên công ty",
    "international_name": "Tên quốc tế",
    "short_name": "Tên viết tắt",
    "representative": "Người đại diện",
    "tax_address": "Địa chỉ thuế",
    "address": "Địa chỉ",
    "phone": "Điện thoại",
    "status": "Trạng thái",
    "company_type": "Loại doanh nghiệp",
    "start_date": "Ngày hoạt động",
    "tax_authority": "Cơ quan thuế",
    "main_business": "Ngành nghề chính",
    "detail_url": "URL",
}


def _ensure_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def _timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_csv(companies, filename=None):
    _ensure_dir()
    if not filename:
        filename = f"masothue_{_timestamp()}.csv"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writerow(FIELD_LABELS)
        for c in companies:
            writer.writerow(c)
    print(f"CSV saved: {path} ({len(companies)} records)")
    return path


def export_excel(companies, filename=None):
    _ensure_dir()
    if not filename:
        filename = f"masothue_{_timestamp()}.xlsx"
    path = os.path.join(OUTPUT_DIR, filename)
    wb = Workbook()
    ws = wb.active
    ws.title = "Companies"

    # Header
    headers = [FIELD_LABELS.get(f, f) for f in FIELDS]
    ws.append(headers)

    # Style header
    from openpyxl.styles import Font, PatternFill
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")

    # Data
    for c in companies:
        ws.append([c.get(f, "") for f in FIELDS])

    # Auto-width
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)

    wb.save(path)
    print(f"Excel saved: {path} ({len(companies)} records)")
    return path

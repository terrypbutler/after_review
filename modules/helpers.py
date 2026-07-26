# modules/helpers.py

from config import FIELD_MAP


def get_field(row, field_name):
    possible_columns = FIELD_MAP.get(field_name, [])

    for col in row.index:
        if col in possible_columns:
            value = str(row[col]).strip()
            if value:
                return value

    return "N/A"


def get_header_title(row, report_label):
    student_name = str(row.get("Full Name", "Unknown Student")).upper()
    dob = str(row.get("DoB", "")).strip()

    if dob:
        return f"{student_name} ({dob}) — {report_label}"

    return f"{student_name} — {report_label}"

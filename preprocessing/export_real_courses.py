"""Builds data/courses_real.csv from a Banner course-search JSON export
(e.g. data/courses_202690.json). Re-run whenever you redownload a new
export with the same shape:

    python preprocessing/export_real_courses.py data/courses_202710.json data/courses_real.csv

Standalone on purpose (plain json/csv, no regopt import) so it keeps
working even if the regopt package changes shape later.
"""

import csv
import json
import sys

DAY_ABBR = {
    "monday": "Mo", "tuesday": "Tu", "wednesday": "We",
    "thursday": "Th", "friday": "Fr", "saturday": "Sa", "sunday": "Su",
}

FIELDNAMES = [
    "id", "subject_course", "department", "title", "section",
    "credit_hours", "capacity", "enrolled", "seats_available",
    "instructors", "block", "days", "begin_time", "end_time", "meeting_time",
]


def meeting_time_str(section: dict) -> str:
    meetings = section["meetingsFaculty"]
    if not meetings:
        return "TBA"
    parts = []
    for m in meetings:
        mt = m["meetingTime"]
        if not mt["beginTime"] or not mt["endTime"]:
            parts.append("TBA")
            continue
        days = "".join(abbr for day, abbr in DAY_ABBR.items() if mt[day])
        where = f"{mt['building'] or ''} {mt['room'] or ''}".strip()
        part = f"{days} {mt['beginTime']}-{mt['endTime']}"
        if where:
            part += f" {where}"
        parts.append(part)
    return "; ".join(parts)


def first_meeting_fields(section: dict) -> tuple[str, str, str]:
    """(days, begin_time, end_time) for the section's first meeting only.
    Structured (not string-glued) so real overlap logic
    (max(start1,start2) < min(end1,end2)) can be written directly against
    these later without re-parsing meeting_time. A section with multiple
    meeting patterns (e.g. lecture + lab) only exposes its first one here
    — see meeting_time for the full list."""
    meetings = section["meetingsFaculty"]
    if not meetings:
        return "", "", ""
    mt = meetings[0]["meetingTime"]
    if not mt["beginTime"]:
        return "", "", ""
    days = "".join(abbr for day, abbr in DAY_ABBR.items() if mt[day])
    return days, mt["beginTime"], mt["endTime"]


def block_code(days: str, begin_time: str) -> str:
    """Compact days+start-time code, e.g. 'TuTh1245'. An approximation of
    a conflict "slot": two sections with the same block_code definitely
    conflict, but two sections can still genuinely overlap (e.g. TuTh1245
    vs TuTh1300, or TuTh0900 vs TuTh1000-1200 style partial overlaps)
    without matching exactly. Equality-based grouping (the approach from
    Milestone 2) only catches the first case — use the days/begin_time/
    end_time columns for real overlap logic instead. See
    IMPLEMENTATION_GUIDE.md, "Real data ingestion."""
    if not begin_time:
        return "TBA"
    return f"{days}{begin_time}"


def section_to_row(section: dict) -> dict:
    days, begin_time, end_time = first_meeting_fields(section)
    return {
        "id": section["courseReferenceNumber"],
        "subject_course": section["subjectCourse"],
        "department": section["subject"],
        "title": section["courseTitle"],
        "section": section["sequenceNumber"],
        "credit_hours": section["creditHours"],
        "capacity": section["maximumEnrollment"],
        "enrolled": section["enrollment"],
        "seats_available": section["seatsAvailable"],
        "instructors": "; ".join(f["displayName"] for f in section["faculty"]),
        "block": block_code(days, begin_time),
        "days": days,
        "begin_time": begin_time,
        "end_time": end_time,
        "meeting_time": meeting_time_str(section),
    }


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else "data/courses_202690.json"
    csv_path = sys.argv[2] if len(sys.argv) > 2 else "data/courses_real.csv"

    with open(json_path) as f:
        sections = json.load(f)

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for section in sections:
            writer.writerow(section_to_row(section))

    print(f"wrote {len(sections)} sections from {json_path} to {csv_path}")


if __name__ == "__main__":
    main()

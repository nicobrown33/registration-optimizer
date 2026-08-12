"""Loads real Middlebury registrar data (data/courses_202690.json), kept
deliberately separate from regopt/io.py, which only ever loads the
invented synthetic CSVs. Per Part VII of the assignment prompt: real and
simulated data must stay clearly distinguished, never merged silently —
this module boundary is that distinction.
"""

import json

from regopt.models import CourseSection, MeetingTime

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def load_real_sections(path: str) -> list[CourseSection]:
    """One CourseSection per section in the Banner course-search export
    (data/courses_202690.json is a flat JSON array of these records)."""
    with open(path) as f:
        raw_sections = json.load(f)

    sections = []
    for raw in raw_sections:
        meetings = [_parse_meeting(m["meetingTime"]) for m in raw["meetingsFaculty"]]
        instructors = [f["displayName"] for f in raw["faculty"]]

        sections.append(CourseSection(
            crn=raw["courseReferenceNumber"],
            subject_course=raw["subjectCourse"],
            subject=raw["subject"],
            course_number=raw["courseNumber"],
            section=raw["sequenceNumber"],
            title=raw["courseTitle"],
            credit_hours=raw["creditHours"],
            capacity=raw["maximumEnrollment"],
            enrolled=raw["enrollment"],
            seats_available=raw["seatsAvailable"],
            wait_capacity=raw["waitCapacity"],
            wait_count=raw["waitCount"],
            instructors=instructors,
            meetings=meetings,
        ))
    return sections


def _parse_meeting(mt: dict) -> MeetingTime:
    return MeetingTime(
        days=[day for day in _DAYS if mt[day]],
        begin_time=mt["beginTime"] or None,   # empty string -> None (async/TBA sections)
        end_time=mt["endTime"] or None,
        building=mt["building"],
        room=mt["room"],
        schedule_type=mt["meetingScheduleType"],
    )


if __name__ == "__main__":
    sections = load_real_sections("data/courses_202690.json")
    print(f"{len(sections)} sections loaded")

    subjects = sorted({s.subject for s in sections})
    print(f"{len(subjects)} subjects: {subjects}")

    unscheduled = [s for s in sections if not s.meetings]
    print(f"{len(unscheduled)} sections with no meeting time at all")

    zero_cap = [s for s in sections if s.capacity == 0]
    print(f"{len(zero_cap)} zero-capacity (reserved/by-arrangement) sections")

    econ150 = next(s for s in sections if s.subject_course == "ECON0150")
    print(f"\n{econ150.subject_course} {econ150.title}, section {econ150.section}")
    print(f"  capacity {econ150.capacity}, enrolled {econ150.enrolled}, instructors {econ150.instructors}")
    for m in econ150.meetings:
        print(f"  meets {m.days} {m.begin_time}-{m.end_time} in {m.building} {m.room}")

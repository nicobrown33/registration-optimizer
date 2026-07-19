from dataclasses import dataclass, field

# --- Course/Student shape used throughout Milestones 0-10 -----------------
# Populated from real Fall 2026 data by default (data/courses_real.csv,
# data/preferences_real.csv — see regopt/io.py). The originally-invented
# data/courses.csv and data/preferences.csv still exist but nothing routes
# to them anymore.

@dataclass
class Course:
    id: str
    subject_course: str  # e.g. "AMST0219"
    department: str
    title: str
    section: str      # e.g. "A" (sequenceNumber)
    credit_hours: float # e.g. 0.5, 1, 3 — real data has half-credit courses
    capacity: int     # maximumEnrollment
    enrolled: int     # currentEnrollment
    seats_available: int
    instructors: str
    block: str       # e.g. "TuTh1115"
    days: str         # e.g. "TuTh"
    begin_time: str      # e.g. "1115"
    end_time: str        # e.g. "1230"
    meeting_time: str  # e.g. "TuTh1115-1230" (for display only; not used in logic)

@dataclass
class Student:
    name: str
    class_year: str
    major: str
    prefs: list[str]   # course IDs in rank order; prefs[0] = 1st choice

# --- Real Middlebury data (data/courses_202690.json, Part VII) ------------
# Deliberately a separate shape from Course/Student above, not a drop-in
# replacement — real sections have properties (multiple meeting times,
# waitlists, cross-listing, zero-capacity reserved sections) the synthetic
# model was never designed to represent. See IMPLEMENTATION_GUIDE.md,
# "Real data ingestion," for how/when to bridge the two.

@dataclass
class MeetingTime:
    days: list[str]           # subset of ["monday", ..., "sunday"]; [] if unscheduled (e.g. independent study)
    begin_time: str | None    # "HHMM" 24-hour, e.g. "1330"; None if unscheduled
    end_time: str | None
    building: str | None
    room: str | None
    schedule_type: str        # e.g. "LCT", "LAB", "SEM", "IND" — see meetingScheduleType

@dataclass
class CourseSection:
    crn: str                  # courseReferenceNumber — unique per section, this term
    subject_course: str       # e.g. "AMST0219" — same style as synthetic Course.id, NOT the same values
    subject: str               # e.g. "AMST"
    course_number: str          # e.g. "0219"
    section: str                  # sequenceNumber, e.g. "A"
    title: str
    credit_hours: float
    capacity: int              # maximumEnrollment
    enrolled: int
    seats_available: int
    wait_capacity: int
    wait_count: int
    instructors: list[str] = field(default_factory=list)
    meetings: list[MeetingTime] = field(default_factory=list)
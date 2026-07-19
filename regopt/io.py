import pandas as pd
from regopt.models import Course, Student

# Real Middlebury Fall 2026 data (see preprocessing/export_real_courses.py
# and IMPLEMENTATION_GUIDE.md, "Real data ingestion") is the default now —
# data/courses.csv and data/preferences.csv (the invented 27-course
# catalog) still exist but nothing routes to them anymore.
DEFAULT_COURSES_PATH = "data/courses_real.csv"
DEFAULT_PREFERENCES_PATH = "data/preferences_real.csv"


def load_courses(path: str = DEFAULT_COURSES_PATH) -> dict[str, Course]:
    """Keyed by course id."""
    # dtype=str + keep_default_na=False: read every column as a plain string
    # and keep blank cells as "" instead of pandas' default NaN. Several
    # real columns (instructors, days, begin_time, end_time) are
    # legitimately blank for unscheduled/no-instructor sections — Course's
    # fields are typed str, not str | None, so NaN would be the wrong shape.
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    courses = {}
    for row in df.itertuples():
        course = Course(
            id=row.id,
            subject_course=row.subject_course,
            department=row.department,
            title=row.title,
            section=row.section,
            credit_hours=float(row.credit_hours) if row.credit_hours else 0.0,
            capacity=int(row.capacity),
            enrolled=int(row.enrolled),
            seats_available=int(row.seats_available),
            instructors=row.instructors,
            block=row.block,
            days=row.days,
            begin_time=row.begin_time,
            end_time=row.end_time,
            meeting_time=row.meeting_time,
        )
        courses[course.id] = course
    return courses

def load_students(path: str = DEFAULT_PREFERENCES_PATH) -> list[Student]:
    rank_cols = {f"rank{i}": str for i in range(1, 11)}
    df = pd.read_csv(path, dtype=rank_cols)
    students = []
    for row in df.to_dict("records"):
        prefs = [row[f"rank{i}"] for i in range(1, 11)]
        student = Student(row["name"], row["class_year"], row["major"], prefs)
        students.append(student)
    return students

if __name__ == "__main__":
    courses = load_courses()
    students = load_students()
    print(f"{len(courses)} courses, {len(students)} students")
    ava = next(s for s in students if s.name == "Ava Thompson")
    print(ava.prefs)
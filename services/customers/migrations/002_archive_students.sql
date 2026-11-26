-- 002: students are archived instead of deleted, so a lesson in the lessons
-- service never points at a student who no longer exists (ADR-7).
-- NOT NULL with a default fills the new column for every existing row:
-- all students that exist today are kept, with archived = 0.
ALTER TABLE students ADD archived BIT NOT NULL CONSTRAINT DF_students_archived DEFAULT 0;

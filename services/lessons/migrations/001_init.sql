-- 001: the lessons service's first schema, ported from the SQLite schema of
-- Assignment 1. Tutors and lessons live here; students live in the customers
-- service's own database.

CREATE TABLE tutors (
    id          INT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_tutors PRIMARY KEY,
    name        NVARCHAR(100) NOT NULL,
    email       NVARCHAR(254) NULL,
    subjects    NVARCHAR(500) NULL,
    hourly_rate DECIMAL(7, 2) NOT NULL CONSTRAINT CK_tutors_hourly_rate CHECK (hourly_rate >= 0)
);

CREATE TABLE lessons (
    id               INT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_lessons PRIMARY KEY,
    -- tutors are in this database, so this foreign key stays
    tutor_id         INT NOT NULL CONSTRAINT FK_lessons_tutors REFERENCES tutors (id),
    -- a plain id: the student lives in the customers database, which a foreign
    -- key cannot reach; the lessons service checks it over HTTP instead (ADR-7)
    student_id       INT NOT NULL,
    subject          NVARCHAR(100) NOT NULL,
    start_time       DATETIME2(0)  NOT NULL,
    duration_minutes INT NOT NULL CONSTRAINT CK_lessons_duration CHECK (duration_minutes > 0),
    status           NVARCHAR(20)  NOT NULL CONSTRAINT DF_lessons_status DEFAULT 'scheduled'
                     CONSTRAINT CK_lessons_status
                     CHECK (status IN ('scheduled', 'completed', 'cancelled'))
);

-- One row that /health updates (and rolls back) to prove the service can write.
CREATE TABLE health_check (
    id         INT       NOT NULL CONSTRAINT PK_health_check PRIMARY KEY,
    checked_at DATETIME2 NOT NULL
);
INSERT INTO health_check (id, checked_at) VALUES (1, SYSUTCDATETIME());

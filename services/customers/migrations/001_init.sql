-- 001: the customers service's first schema, ported from the SQLite schema of
-- Assignment 1. Students and the staff accounts used for login live here.

CREATE TABLE students (
    id             INT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_students PRIMARY KEY,
    name           NVARCHAR(100) NOT NULL,
    guardian_name  NVARCHAR(100) NULL,
    guardian_email NVARCHAR(254) NULL,
    guardian_phone NVARCHAR(20)  NULL
);

CREATE TABLE staff (
    id            INT IDENTITY(1, 1) NOT NULL CONSTRAINT PK_staff PRIMARY KEY,
    username      NVARCHAR(100) NOT NULL CONSTRAINT UQ_staff_username UNIQUE,
    password_hash NVARCHAR(255) NOT NULL
);

-- One row that /health updates (and rolls back) to prove the service can write.
CREATE TABLE health_check (
    id         INT       NOT NULL CONSTRAINT PK_health_check PRIMARY KEY,
    checked_at DATETIME2 NOT NULL
);
INSERT INTO health_check (id, checked_at) VALUES (1, SYSUTCDATETIME());

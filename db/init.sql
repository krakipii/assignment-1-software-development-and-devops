-- Creates one database and one login per service on the local SQL Server.
-- Safe to run more than once: every step checks first whether it is already done.
-- Run by the db-init service in docker-compose.yml, which passes the two
-- passwords in as sqlcmd variables, so no password is written in this file.

IF DB_ID(N'customers') IS NULL
    CREATE DATABASE customers;
GO
IF DB_ID(N'lessons') IS NULL
    CREATE DATABASE lessons;
GO

-- One login per service. Re-running the script resets the password to the one in .env.
IF SUSER_ID(N'customers_user') IS NULL
    CREATE LOGIN customers_user WITH PASSWORD = N'$(CUSTOMERS_DB_PASSWORD)', DEFAULT_DATABASE = customers;
ELSE
    ALTER LOGIN customers_user WITH PASSWORD = N'$(CUSTOMERS_DB_PASSWORD)';
GO
IF SUSER_ID(N'lessons_user') IS NULL
    CREATE LOGIN lessons_user WITH PASSWORD = N'$(LESSONS_DB_PASSWORD)', DEFAULT_DATABASE = lessons;
ELSE
    ALTER LOGIN lessons_user WITH PASSWORD = N'$(LESSONS_DB_PASSWORD)';
GO

-- Each login becomes a user in its own database only. It gets db_owner there so the
-- service can run its migrations, and it has no user in the other database,
-- so it cannot open it.
USE customers;
GO
IF USER_ID(N'customers_user') IS NULL
    CREATE USER customers_user FOR LOGIN customers_user;
GO
IF ISNULL(IS_ROLEMEMBER(N'db_owner', N'customers_user'), 0) = 0
    ALTER ROLE db_owner ADD MEMBER customers_user;
GO

USE lessons;
GO
IF USER_ID(N'lessons_user') IS NULL
    CREATE USER lessons_user FOR LOGIN lessons_user;
GO
IF ISNULL(IS_ROLEMEMBER(N'db_owner', N'lessons_user'), 0) = 0
    ALTER ROLE db_owner ADD MEMBER lessons_user;
GO

PRINT 'db-init finished: databases customers and lessons, logins customers_user and lessons_user.';
GO

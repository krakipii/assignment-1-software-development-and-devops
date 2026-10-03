# Tutoring Company Manager : Assignment 1 — Software Development and DevOps

A small application for an independent tutoring company. This system helps the company keep track of their customers,
the scheduled lessons, which tutor is teaching which lesson, and the state of the lessons (scheduled, cancelled, completed)
It is a single-process Flask application that stores all data in SQLite.

## Requirements

- Python 3.10 or newer
- pip

## Setup and run

```bash
git clone <your-repository-url>
cd <repository-folder>
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app listens on port 8000. Check that it is running by opening
http://localhost:8000/health, which returns `{"status": "ok"}`.

## Logging in

Every page except `/health` requires a staff login. When the app starts and
no staff account exists yet, it creates one called `admin` with a random
password and prints that password once in the terminal:

```
Created staff account 'admin' with password: ...
```

To choose the password yourself, set `ADMIN_PASSWORD` when starting the app,
for example `ADMIN_PASSWORD=my-password python app.py`. If the account already
exists, this resets its password.

The database tables are created automatically when the app starts; there is no
separate setup or migration step.

## Configuration

Everything is configured with environment variables. None of them are required.

| Variable     | Default                      | Purpose                                   |
|--------------|------------------------------|-------------------------------------------|
| `PORT`       | `8000`                       | Port the server listens on                |
| `DATA_DIR`   | `data/` next to `app.py`     | Folder that holds the SQLite file         |
| `SECRET_KEY` | random value on every start  | Signs session cookies; set a fixed value in production |
| `ADMIN_USERNAME` | `admin`                  | Username of the staff account created at start |
| `ADMIN_PASSWORD` | random, printed once     | Password of that account; setting it resets the password |

The SQLite database is always stored at `$DATA_DIR/tutoring.db`.

## Tests and coverage

Run the tests:

```bash
pytest
```

Run them with a coverage report:

```bash
pytest --cov=customers --cov=lessons --cov=auth --cov-report=term-missing
```

Coverage is measured on the business logic in each `service.py`.
The Flask routes only pass requests through to the services, so `.coveragerc`
leaves them out of the measurement.

Latest result: 76 tests passed, 100% coverage of `customers/service.py`,
`lessons/service.py` and `auth/service.py`.

## Project structure

```
app.py               entry point: creates the Flask app and starts the server
database.py          SQLite connection handling and schema
auth/                staff login (protects both domains)
customers/           Customer Management domain (students, guardians)
lessons/             Lesson Management domain (tutors, lessons, lesson status)
templates/, static/  HTML templates and CSS for the web pages
tests/               automated tests for the business logic
ADR.md               architecture decision records
AI_USAGE.md          log of AI assistance
```
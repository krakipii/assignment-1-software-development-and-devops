# Tutoring Company Manager

A system for an independent tutoring company. Office staff keep track of students and their
guardians' contact details, tutors, and lessons with their status (scheduled, completed,
cancelled). The scheduling rules from Assignment 1 still hold: no double bookings for a tutor or
a student, a tutor only teaches the subjects they list, and a lesson lasts 15 to 240 minutes.

**Live:** https://krakipiieu2024ui.z1.web.core.windows.net/ (log in as `admin`; the password is
shared with the graders separately). After a quiet period the first request can take about a
minute: the containers start and the databases resume.

## How it is built

Assignment 1 was one Flask process with one SQLite file. Assignment 2 splits it along the seam
of ADR-2 into two services, each with its own database, plus a static UI:

| Part | Folder | Owns | Locally | On Azure |
|---|---|---|---|---|
| customers service | `services/customers` | students, guardians, staff login | http://localhost:8001 | Container App `krakipi-ieu2024-customers` |
| lessons service | `services/lessons` | tutors, lessons, lesson status | http://localhost:8002 | Container App `krakipi-ieu2024-lessons` |
| UI | `ui` | nothing (static pages) | http://localhost:8080 | Storage static website `krakipiieu2024ui` |
| customers database | `services/customers/migrations` | | SQL Server container, database `customers` | `krakipi-ieu2024-customers-db` |
| lessons database | `services/lessons/migrations` | | SQL Server container, database `lessons` | `krakipi-ieu2024-lessons-db` |

- The browser loads the UI and calls both services directly; their addresses come from
  `ui/config.js`, which the pipeline writes at deploy time.
- Only student data crosses the seam, and only in one direction: the lessons service calls the
  customers service's `GET /students/{id}` (to check the student before scheduling) and
  `GET /students?include_archived=true` (for the names in the lesson list), with a timeout.
  If the customers service does not answer, scheduling is refused with a clear message and the
  lesson list is shown without student names (see ADR-6 and `system.yaml`).
- Logging in happens at the customers service, which returns a signed token; both services
  check it with the shared `AUTH_SECRET`.
- Each service applies its own numbered SQL migrations when it starts (`migrate.py`).

The whole system is described for machines in [`system.yaml`](system.yaml) (checked against
[`system.schema.json`](system.schema.json) in CI) and each API in its `openapi.yaml`. The
decisions are in [`ADR.md`](ADR.md); diagrams are in [`docs/`](docs).

## Run it locally with Docker Compose

Needs Docker Desktop. On an Apple Silicon Mac, turn on *Settings → General → Use Rosetta for
x86_64/amd64 emulation*, because SQL Server only exists for Intel processors.

```bash
cp .env.example .env    # then fill in your own local values (letters and digits only)
docker compose up --build
```

Open http://localhost:8080 and log in as `admin` with the `ADMIN_PASSWORD` from `.env`.
Compose starts SQL Server, runs `db/init.sql` once (one database and one login per service),
builds and starts both services, and serves the UI with nginx. Stop with `docker compose down`;
the data stays in the `mssql-data` volume (`docker compose down -v` deletes it).

To see the designed partial failure: `docker compose stop customers`, then reload the Lessons
page (lessons still shown, names unavailable) and try to schedule a lesson (refused with an
explanation). `docker compose start customers` brings it back.

## Run a single service

Start only the database, then run the service with Python 3.12:

```bash
docker compose up -d --wait db && docker compose run --rm db-init
python3 -m venv .venv && source .venv/bin/activate
cd services/customers
pip install -r requirements-dev.txt
export DATABASE_URL="mssql://customers_user:<CUSTOMERS_DB_PASSWORD from .env>@localhost:1433/customers"
export AUTH_SECRET="<AUTH_SECRET from .env>" ADMIN_PASSWORD="<a password>"
python app.py           # listens on port 8000 (PORT changes it)
```

The lessons service works the same way from `services/lessons`, with
`DATABASE_URL=mssql://lessons_user:<LESSONS_DB_PASSWORD>@localhost:1433/lessons`, the same
`AUTH_SECRET`, and `CUSTOMERS_URL` pointing at a running customers service (for example
`http://localhost:8001` while compose runs it). Without the customers service it still starts
and serves tutors and lessons; scheduling then answers 503. Every setting is listed, with its
default, in `system.yaml`.

## Run the tests and coverage

The tests run against a real SQL Server (the compose `db` container); they create their own
`*_test` databases and never touch the services' data. They read `MSSQL_SA_PASSWORD` from
`.env`.

```bash
docker compose up -d --wait db
cd services/customers && ruff check . && pytest --cov --cov-report=term-missing
cd ../lessons && ruff check . && pytest --cov --cov-report=term-missing
```

The lessons service's tests replace the customers service with a stub HTTP server, including
the cases where it is stopped or slower than the timeout (ADR-9). CI fails below 70% coverage
in either service.

## How deployment works

Everything after the initial setup is done by GitHub Actions; nothing is changed by hand in the
portal.

- **CI** (`.github/workflows/ci.yml`) runs on every pull request and every push to a branch:
  ruff, the tests of both services against a throwaway SQL Server container with a random
  password, the 70% coverage gate, validation of `system.yaml` and both OpenAPI documents, and
  a build of both images. Changes reach `main` only through pull requests.
- **CD** (`.github/workflows/cd.yml`) runs on every push to `main`: it first runs the whole CI
  workflow, which on `main` also pushes both images to GHCR tagged with the commit SHA
  (`ghcr.io/krakipii/tutoring-customers:<sha>`, `ghcr.io/krakipii/tutoring-lessons:<sha>`).
  Then it signs in to Azure with OIDC as the managed identity `krakipi-ieu2024-github`
  (Contributor on the resource group only, no stored Azure password), sets each Container App's
  secrets, points it at the new image, writes `ui/config.js` with the services' addresses,
  uploads the UI, and passes only when both `/health` endpoints report the new commit's SHA.
- Each service runs its migrations when it starts; at most one replica per service means they
  never run twice at the same time.
- GitHub **secrets**: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`,
  `CUSTOMERS_DB_PASSWORD`, `LESSONS_DB_PASSWORD`, `AUTH_SECRET`, `ADMIN_PASSWORD`.
  GitHub **variables**: `PREFIX`, `RESOURCE_GROUP`, `UI_STORAGE`, `SQL_SERVER`.

## Reproduce the initial Azure setup

Run once, in Azure Cloud Shell (Bash), signed in with the IE account. Passwords are generated
in the shell and go straight into GitHub secrets; the SQL admin password is kept in a password
manager. Nothing secret is written here.

```bash
# Names and subscription
PREFIX=krakipi-ieu2024; RG=rg-$PREFIX; UI_STORAGE=krakipiieu2024ui
GH_REPO=krakipii/assignment-1-software-development-and-devops
az account list -o table
az account set --subscription "<the enabled Azure for Students subscription id>"
gh auth login

# 1. Allowed regions (spaincentral, belgiumcentral, italynorth, austriaeast, germanywestcentral)
az policy assignment list --query "[].{name:displayName, regions:parameters.listOfAllowedLocations.value}" -o json
LOCATION=germanywestcentral

# 2. Providers and resource group
for p in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do az provider register --namespace $p; done
az group create -n $RG -l $LOCATION

# 3. UI: Storage static website (its web endpoint is the public URL)
az storage account create -n $UI_STORAGE -g $RG -l $LOCATION --sku Standard_LRS --kind StorageV2
az storage blob service-properties update --account-name $UI_STORAGE --static-website --index-document index.html --auth-mode key
az storage account show -n $UI_STORAGE -g $RG --query primaryEndpoints.web -o tsv

# 4. SQL server, two serverless databases, one contained user each.
#    germanywestcentral and italynorth refused new SQL servers (RegionDoesNotAllowProvisioning)
#    and the other regions have no free offer, so the server is in austriaeast and the
#    databases are serverless without the free offer (ADR-8).
SQL_SERVER=$PREFIX-sqlat
SQL_ADMIN_PASSWORD="Az$(openssl rand -hex 16)"   # saved in a password manager
az sql server create -n $SQL_SERVER -g $RG -l austriaeast --admin-user tutoringadmin --admin-password "$SQL_ADMIN_PASSWORD"
az sql server firewall-rule create -g $RG -s $SQL_SERVER -n AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
for svc in customers lessons; do
  az sql db create -g $RG -s $SQL_SERVER -n $PREFIX-$svc-db --edition GeneralPurpose --compute-model Serverless --family Gen5 --min-capacity 0.5 --capacity 1 --backup-storage-redundancy Local --auto-pause-delay 60 --max-size 2GB
done
CUSTOMERS_DB_PASSWORD="Cu$(openssl rand -hex 16)"; LESSONS_DB_PASSWORD="Le$(openssl rand -hex 16)"
MYIP=$(curl -s https://ifconfig.me)
az sql server firewall-rule create -g $RG -s $SQL_SERVER -n setup-temp --start-ip-address $MYIP --end-ip-address $MYIP
# sqlcmd was missing from Cloud Shell, so it was downloaded first:
mkdir -p ~/bin && curl -sL https://github.com/microsoft/go-sqlcmd/releases/latest/download/sqlcmd-linux-amd64.tar.bz2 | tar -xj -C ~/bin && export PATH=$HOME/bin:$PATH
sqlcmd -S $SQL_SERVER.database.windows.net -d $PREFIX-customers-db -U tutoringadmin -P "$SQL_ADMIN_PASSWORD" -Q "CREATE USER customers_user WITH PASSWORD = '$CUSTOMERS_DB_PASSWORD'; ALTER ROLE db_ddladmin ADD MEMBER customers_user; ALTER ROLE db_datareader ADD MEMBER customers_user; ALTER ROLE db_datawriter ADD MEMBER customers_user;"
sqlcmd -S $SQL_SERVER.database.windows.net -d $PREFIX-lessons-db -U tutoringadmin -P "$SQL_ADMIN_PASSWORD" -Q "CREATE USER lessons_user WITH PASSWORD = '$LESSONS_DB_PASSWORD'; ALTER ROLE db_ddladmin ADD MEMBER lessons_user; ALTER ROLE db_datareader ADD MEMBER lessons_user; ALTER ROLE db_datawriter ADD MEMBER lessons_user;"
gh secret set CUSTOMERS_DB_PASSWORD -R $GH_REPO -b "$CUSTOMERS_DB_PASSWORD"
gh secret set LESSONS_DB_PASSWORD -R $GH_REPO -b "$LESSONS_DB_PASSWORD"
gh variable set SQL_SERVER -R $GH_REPO -b "$SQL_SERVER"
az sql server firewall-rule delete -g $RG -s $SQL_SERVER -n setup-temp

# 5. Container Apps environment (with its Log Analytics workspace) and two apps,
#    0 to 1 replicas; the first CD run replaces the placeholder image and sets all settings.
az containerapp env create -n $PREFIX-env -g $RG -l $LOCATION
for svc in customers lessons; do
  az containerapp create -n $PREFIX-$svc -g $RG --environment $PREFIX-env --image mcr.microsoft.com/k8se/quickstart:latest --ingress external --target-port 8000 --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi
done

# 6. The pipeline's identity: Contributor on the resource group, trusted for pushes to main
az identity create -n $PREFIX-github -g $RG -l $LOCATION
PRINCIPAL_ID=$(az identity show -n $PREFIX-github -g $RG --query principalId -o tsv)
RG_ID=$(az group show -n $RG --query id -o tsv)
az role assignment create --assignee-object-id $PRINCIPAL_ID --assignee-principal-type ServicePrincipal --role Contributor --scope $RG_ID
OWNER_ID=$(gh api repos/$GH_REPO --jq .owner.id); REPO_ID=$(gh api repos/$GH_REPO --jq .id)
az identity federated-credential create --name github-main -g $RG --identity-name $PREFIX-github --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange --subject "repo:${GH_REPO}:ref:refs/heads/main"
az identity federated-credential create --name github-main-ids -g $RG --identity-name $PREFIX-github --issuer https://token.actions.githubusercontent.com --audiences api://AzureADTokenExchange --subject "repo:${GH_REPO%/*}@${OWNER_ID}/${GH_REPO#*/}@${REPO_ID}:ref:refs/heads/main"

# 7. GitHub secrets and variables for the pipeline
gh secret set AZURE_CLIENT_ID -R $GH_REPO -b "$(az identity show -n $PREFIX-github -g $RG --query clientId -o tsv)"
gh secret set AZURE_TENANT_ID -R $GH_REPO -b "$(az account show --query tenantId -o tsv)"
gh secret set AZURE_SUBSCRIPTION_ID -R $GH_REPO -b "$(az account show --query id -o tsv)"
gh secret set AUTH_SECRET -R $GH_REPO -b "$(openssl rand -hex 32)"
gh secret set ADMIN_PASSWORD -R $GH_REPO -b "<the UI admin password>"
gh variable set PREFIX -R $GH_REPO -b $PREFIX
gh variable set RESOURCE_GROUP -R $GH_REPO -b $RG
gh variable set UI_STORAGE -R $GH_REPO -b $UI_STORAGE

# 9. Read access for the professors
for p in amartini@faculty.ie.edu bserra@faculty.ie.edu; do az role assignment create --assignee $p --role Reader --scope $RG_ID; done
```

The first deploy is then a merge to `main`.

## Evidence

**Pipeline**

- Successful CD run on `main` (first deploy, commit `e64da82`):
  https://github.com/krakipii/assignment-1-software-development-and-devops/actions/runs/45640507896
- Failed run that was fixed: [link to the failed run] — cause: [what failed] — fixed by:
  [commit or pull request that fixed it].

**Migration on Azure (§4.6).** The live database held data before migration 002 was deployed
and kept it afterwards:

- Data before 002: ![Students and lessons before migration 002](docs/evidence/data-before-002.png)
- Startup log after the deploy of 002: the customers service reports
  `Database schema is up to date (2 migrations applied)`, where the previous start on the
  same database reported 1: ![Startup log line](docs/evidence/migration-log.png)
- Data after 002, every student still there: ![Students after migration 002](docs/evidence/data-after-002.png)

The first deploy of commit 14 went out without `002_archive_students.sql`, because the file had
never been added to the repository; the startup log showed "1 migrations applied", and the
follow-up pull request "Add migration 002" added the file and its code.

**Partial failure.** With the customers service stopped, the lesson list still loads, without
student names, and scheduling is refused with an explanation:
![Lessons page with the customers service stopped](docs/evidence/partial-failure.png)

## Security incidents

- **2026-11-16: local database passwords committed.** Commit d631302, pushed on 2026-11-16, put the three local development passwords (SQL Server `sa`, `customers_user` and `lessons_user`) in `.env.example` instead of the Git-ignored `.env`. They only protected the SQL Server container on my own laptop; no Azure or GitHub credential was involved. On 2026-11-17, within 24 hours, I rotated all three: I deleted and recreated the local database with new passwords in `.env`, and emptied `.env.example` again. The old values remain in the Git history but no longer work anywhere, so I did not rewrite the history.

## Repository layout

```
services/customers/   customers service: app.py, routes.py, service.py, auth.py, db.py,
                      migrate.py, migrations/, tests/, openapi.yaml, Dockerfile
services/lessons/     lessons service: the same, plus customers_client.py (the seam)
ui/                   static UI: index.html, app.js, style.css, config.js
db/init.sql           local only: one database and one login per service
docker-compose.yml    the whole system locally
system.yaml           machine-readable description, checked against system.schema.json
.github/workflows/    ci.yml and cd.yml
ADR.md                architecture decisions 1-10
AI_USAGE.md           log of AI assistance
docs/                 diagrams and evidence
```

## AI disclosure statement

I acknowledge the use of Claude (Anthropic, through claude.ai) in this assignment: to plan the
commits against the assignment's requirements, to write most of the code of both services, the
tests, the Dockerfiles, the compose file, the CI and CD workflows, the UI and this README, to
draft ADR-6 to ADR-10, and to guide me through Git, Docker, GitHub and the Azure setup. Every
meaningful interaction, what I accepted or changed, and my own explanation of how each part
works are logged in [AI_USAGE.md](AI_USAGE.md). I ran and tested each part before committing
it, chose and checked the Azure regions and settings myself, and drew the diagrams myself.

# Architecture Decision

## Decision

The platform uses SQL Server Developer as its permanent local engineering
database. Azure SQL Database and Azure Database for PostgreSQL are excluded
from the architecture. Azure App Service is used only to host the public web
application.

This decision protects the Azure for Students allowance while retaining the
T SQL, SQL Server, SSIS, SSRS, Power BI and Microsoft Fabric experience that
the project is intended to demonstrate.

## Permanent Engineering Path

| Component | Responsibility | Location |
|---|---|---|
| TfGM GTFS | Published timetable source | TfGM |
| Python ingestion | Download, checksum, validation and raw preservation | Local or Codespaces |
| SQL Server Developer | Staging, governance, dimensional warehouse and analytics | Local container |
| SQLite serving database | Approved dashboard data only | Deployment artefact |
| FastAPI and dashboard | Public analytical application | Azure App Service |
| GitHub Actions | Tests, build validation and application deployment | GitHub |

The SQL Server database is not exposed publicly and is not required by the
running Azure application. The application receives a compact, read only
SQLite export during deployment.

## Microsoft Fabric Role

Microsoft Fabric remains an agreed part of the project. During the Fabric
trial it will demonstrate:

* Data Factory pipeline orchestration
* Copy and validation activities
* Pipeline parameters and repeatable execution
* Monitoring, failure handling and audit evidence
* A controlled implementation of the same logical processing stages

Fabric can connect directly to a local SQL Server through an on premises data
gateway when a suitable Windows gateway host is available. The current Linux
Codespace cannot host that gateway.

If a Windows gateway is not available during the trial, Fabric will ingest a
controlled TfGM publication directly into the temporary Fabric workspace and
execute the equivalent orchestration stages there. This is a demonstration
environment, not a second permanent source of truth. It can be removed when
the trial ends without affecting the local warehouse or public application.

## Later Microsoft Tooling

SSIS will demonstrate a traditional package based orchestration path against
the local SQL Server database. SSRS will consume approved analytical views.
Power BI Desktop will use the governed analytical model and may publish a
report where the available licence permits it.

These implementations share the same table definitions, quality rules and
business measures. They are not separate competing warehouses.

## Cost and Subscription Guardrails

The following controls apply:

1. Do not create Azure SQL Database for this project.
2. Do not create Azure Database for PostgreSQL for this project.
3. Do not configure the public application to query the engineering warehouse.
4. Do not place passwords, connection strings or downloaded GTFS data in Git.
5. Keep the Azure App Service application read only with respect to analytical
   data.
6. Build the SQLite serving database before deployment.
7. Treat Fabric capacity as temporary unless a funded capacity is explicitly
   approved later.

## Data Freshness

Phase 1 is nightly timetable intelligence. A local pipeline run downloads and
processes the latest TfGM GTFS publication, refreshes the approved analytical
views and exports a new SQLite serving database. GitHub Actions validates and
deploys the resulting application artefact.

The dashboard must display the source publication timestamp and the last
successful pipeline timestamp. It must not describe the data as live vehicle
movement, actual punctuality or an official TfGM operational warning.

Phase 2 will add Bus Open Data Service vehicle monitoring as a separate real
time data path. BODS observations will have their own ingestion frequency,
raw retention, staging tables, quality rules and freshness indicators. They
will not overwrite or be presented as part of the nightly timetable feed.

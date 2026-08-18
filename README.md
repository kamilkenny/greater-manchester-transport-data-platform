# Greater Manchester Transport Data Platform

[![Quality gate][quality-gate-badge]][quality-gate-workflow]

[quality-gate-badge]: https://github.com/kamilkenny/greater-manchester-transport-data-platform/actions/workflows/quality-gate.yml/badge.svg
[quality-gate-workflow]: https://github.com/kamilkenny/greater-manchester-transport-data-platform/actions/workflows/quality-gate.yml

An end to end Greater Manchester public transport data engineering and
service quality platform built from TfGM GTFS publications.

The permanent engineering database is SQL Server Developer running locally.
Microsoft Fabric Data Factory remains part of the project as a controlled
orchestration and monitoring implementation during the Fabric trial. Azure
App Service is reserved for the public application and does not host the
engineering warehouse.

## Architecture

1. Python downloads, validates and preserves TfGM GTFS publications.
2. Local SQL Server Developer stores staging, governance, warehouse and
   analytical data.
3. T SQL procedures build dimensions, facts, publication comparisons and
   approved analytical views.
4. Microsoft Fabric demonstrates pipeline orchestration, monitoring and
   equivalent processing during the Fabric trial.
5. A compact, read only SQLite database is exported from approved analytical
   views for the public application.
6. FastAPI and the dashboard read SQLite on Azure App Service.
7. SSIS, SSRS and Power BI use the same governed model for their agreed
   project demonstrations.
8. GitHub Actions provides an independent quality gate for linting, automated
   tests and orchestration dry run evidence.

This design avoids Azure SQL Database consumption while preserving the
Microsoft data platform skills targeted by the project.

See [Architecture decision](docs/architecture.md) for the environment roles,
cost controls and Fabric connectivity options.

## Local database setup

Prerequisites:

* Docker with Compose support
* Python 3.12 or later
* Microsoft ODBC Driver 18 for SQL Server

Copy the example configuration and choose a strong local password:

```bash
cp .env.example .env
```

Start SQL Server Developer:

```bash
docker compose up -d sqlserver
```

The Compose configuration limits SQL Server to 2,048 MB by default, leaving
memory available for Python, Docker and the Codespaces development services.
Set `SQL_SERVER_MEMORY_LIMIT_MB` in `.env` only when the host has a different
memory budget.

Install the project and create the database objects:

```bash
python -m pip install -e .
python -m transport_platform.database.initialise
```

The initialiser creates the configured local database when necessary and
applies every ordered script in `sql/ddl`. It is safe to run the current
idempotent DDL scripts again.

## Load GTFS reference staging

The first staging loader registers an immutable source snapshot and loads
`agency.txt`, `calendar.txt`, `calendar_dates.txt` and `feed_info.txt` in one
audited transaction. It streams source records in bounded batches and does
not load the complete files into memory.

Find the latest preserved snapshot:

```bash
find data/raw/gtfs -type f -name '*.zip' | sort | tail -n 1
```

Pass that path to the loader:

```bash
python -m transport_platform.ingestion.load_reference_tables \
  data/raw/gtfs/YYYY/MM/DD/tfgm_gtfs_TIMESTAMP_CHECKSUM.zip
```

Reprocessing the same checksum reuses its snapshot key and replaces only
that snapshot's reference staging rows. Each attempt is recorded in
`governance.pipeline_run`.

## Load GTFS network staging

After the reference tables succeed, load `routes.txt`, `stops.txt` and
`trips.txt` from the same preserved snapshot:

```bash
python -m transport_platform.ingestion.load_network_tables \
  data/raw/gtfs/YYYY/MM/DD/tfgm_gtfs_TIMESTAMP_CHECKSUM.zip
```

The loader uses the same immutable snapshot registration, bounded batching,
row hashing and pipeline auditing as the reference loader. Reprocessing the
same snapshot replaces only its network staging rows and creates a new audit
run.

## Load GTFS high volume staging

After the network tables succeed, load `stop_times.txt` and `shapes.txt` from
the same preserved snapshot:

```bash
python -m transport_platform.ingestion.load_high_volume_tables \
  data/raw/gtfs/YYYY/MM/DD/tfgm_gtfs_TIMESTAMP_CHECKSUM.zip
```

These files contain the largest staging datasets. The loader streams records
through Microsoft's native TDS bulk copy protocol in bounded batches, without
holding either complete file in memory. Each bulk batch uses its own database
transaction. These two high volume staging tables are rolling work tables.
Reprocessing truncates them before loading the selected immutable raw snapshot,
so an interrupted attempt can be restarted without performing a multi million
row delete. They retain only their sequential clustered lineage key during
ingestion. Analytical secondary indexes are created on typed warehouse tables,
not maintained across millions of raw staging writes. Historical source
publications remain preserved in the raw layer, while approved history is
promoted into the warehouse. A successful run marks the registered snapshot as
`LOADED`.

## Load core warehouse dimensions

After all staging groups have loaded successfully, build the shared date
dimension and the Type 2 operator dimension for that snapshot:

```bash
python -m transport_platform.warehouse.load_core_dimensions 1
```

The argument is the `snapshot_key` recorded in
`governance.source_snapshot`. The set based SQL procedure validates that the
snapshot has `LOADED` status, derives the complete published service date
range, inserts missing calendar dates and maintains current and historical
operator versions. Reprocessing the same snapshot does not duplicate date or
operator rows. Each attempt is recorded in `governance.pipeline_run`.

## Load network warehouse dimensions

After the core dimensions succeed, build the Type 2 route and stop dimensions
for the same snapshot:

```bash
python -m transport_platform.warehouse.load_network_dimensions 1
```

The set based SQL procedure validates route identifiers, operator references,
route types, route colours, stop identifiers, coordinates and coded stop
attributes before changing warehouse history. Routes resolve to the current
operator version. Changed or removed route and stop versions are closed while
new current versions are inserted. Reprocessing the same snapshot is
idempotent, and every attempt is recorded in `governance.pipeline_run`.

## Load service calendars

After the core dimensions succeed, build the snapshot specific service
dimension and active service date bridge:

```bash
python -m transport_platform.warehouse.load_service_calendar 1
```

The loader validates weekday flags, calendar ranges, exception types and
natural key uniqueness. It expands normal weekday operation against the shared
date dimension, removes cancelled dates and adds exceptional operating dates.
Services published only through added date exceptions are also supported.
Reprocessing the same immutable snapshot does not duplicate service or bridge
rows, and each attempt is recorded in `governance.pipeline_run`.

## Load trip dimensions

After the network dimensions and service calendars succeed, build the
snapshot specific trip dimension:

```bash
python -m transport_platform.warehouse.load_trip_dimension 1
```

The loader validates trip identifiers, direction and accessibility codes,
then resolves each trip to the service belonging to the snapshot and the
route version valid when that snapshot was published. Referenced shapes must
also exist in the high volume staging data. Reprocessing the same immutable
snapshot inserts no duplicate trips, and every attempt is recorded in
`governance.pipeline_run`.

## Load geographical shape points

After high volume staging succeeds, validate and promote the geographical
shape points into their typed warehouse table:

```bash
python -m transport_platform.warehouse.load_shape_points 1
```

The loader validates identifiers, coordinates, point sequences, travelled
distances and business key uniqueness before writing any rows. It then commits
bounded batches of 50,000 rows to limit memory and transaction log pressure.
Completed batches can be safely reused after an interrupted attempt, and a
complete rerun inserts no duplicate shape points. Every attempt is recorded in
`governance.pipeline_run`.

## Load scheduled stop events

After trips and network dimensions succeed, validate and promote scheduled
stop events into the central timetable fact table:

```bash
python -m transport_platform.warehouse.load_scheduled_stop_events 1
```

The loader validates trip and stop relationships, stop sequences, optional
codes, travelled distances and GTFS times, including services running beyond
midnight. Times are converted into seconds after the service day begins. The
validated source is committed in resumable batches of 50,000 rows, limiting
memory and transaction log pressure. A complete rerun inserts no duplicates,
and every attempt is recorded in `governance.pipeline_run`.

## Build daily service facts

After service calendars, trips and scheduled stop events succeed, build the
route and stop service day analytical facts:

```bash
python -m transport_platform.warehouse.load_daily_service_facts 1
```

The loader aggregates trip and service patterns once before expanding them
through active service dates. Route facts describe scheduled trips, stop
events, distinct stops, operating span and average scheduled headway. Stop
facts describe scheduled trips, served routes, operating span and average
scheduled headway. By default, it materialises 366 days beginning on the
snapshot download date, avoiding the expansion of long term placeholder
calendar ranges that are not useful to the nightly timetable product. The
start date and horizon remain configurable through explicit command options.
Bounded date batches limit transaction log pressure and are committed
independently. Existing rows are compared with the complete derived result,
so interrupted attempts can resume and a complete rerun inserts no
duplicates. Every attempt is recorded in `governance.pipeline_run`.

## Build publication changes

After the entity dimensions for a snapshot succeed, compare the publication
with the most recent eligible predecessor:

```bash
python -m transport_platform.warehouse.load_publication_changes 1
```

The first snapshot is treated as a successful bootstrap and produces no
change facts. From the second snapshot onwards, the loader compares operators,
routes, stops, services and trips using their governed business identifiers
and row hashes. Added, removed and modified entities are written once to
`warehouse.fact_publication_change`. Existing results are verified before any
new rows are inserted, making complete reruns idempotent. An explicit previous
snapshot can be supplied with `--previous-snapshot-key` when controlled
backfills are required.

## Approved analytics

DDL scripts `022` through `038` create the approved reporting contract used by
the serving export, FastAPI, the dashboard, SSRS and Power BI. The contract
contains a one row platform and freshness summary, route level daily service,
compact route and stop summaries, publication changes, recent pipeline runs
and recent data quality results. It also provides network trends, operator and
transport mode comparisons, ranked scheduled service intelligence, geographic
coverage, accessibility, stop coordinate changes, executive dashboard KPIs
and recent health for every pipeline. Application consumers do not query
staging tables or the multi million row warehouse facts directly.

Reapply the idempotent DDL whenever the view definitions change:

```bash
python -m transport_platform.database.initialise
```

Pipeline health is recovery aware. A latest failed run is marked
`ACTION REQUIRED`, an active run is `RUNNING`, and a successful run following
one or more recent failures is `RECOVERED`. Historical failure rates remain
available without presenting a recovered service as currently unstable.

## SQLite serving export

The public application reads a compact, read only SQLite artefact rather than
connecting to the engineering SQL Server database. Export all 17 approved
analytics views with:

```bash
python -m transport_platform.serving.export_analytics
```

The exporter streams large results in bounded batches, creates dashboard
indexes, writes freshness and row count metadata, runs SQLite integrity
validation and publishes the completed file atomically. The default output is
`data/serving/transport_dashboard.db`, configurable with
`SERVING_SQLITE_PATH` or the `--output` option. Every completed or failed
export is recorded in `governance.pipeline_run`.

## FastAPI intelligence dashboard

The public application reads only the generated SQLite serving database. It
provides an executive overview, daily network trends, bus and tram comparison,
ranked route and stop intelligence, a geographical stop map, operator
contribution, publication change monitoring, pipeline health and data quality
through governed JSON endpoints.

Start the application locally after generating the serving database:

```bash
uvicorn transport_platform.api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

Open `/` for the dashboard, `/health` for the deployment health probe and
`/api/docs` for the interactive API contract. The user interface clearly
identifies the indicators as scheduled timetable intelligence rather than
live vehicle performance, punctuality, reliability or passenger demand.

## Azure App Service deployment

The production web package contains only the application source, lightweight
web dependencies, the governed read only SQLite serving snapshot and a
deployment manifest. SQL Server, raw GTFS files and engineering credentials
are never included in the public application artefact.

Build and validate the deployment package after exporting the latest approved
analytics:

```bash
python -m transport_platform.deployment.build_azure_package
```

The command validates SQLite integrity before atomically publishing
`dist/gm_transport_dashboard_azure.zip`. Azure App Service runs the package
with `deploy/azure/startup.sh`, serving the FastAPI application from `src` and
opening the analytical database in read only mode. The intended production
application name is `gm-transport-intelligence-kamil`.

## Governed orchestration and continuous integration

The production orchestration entry point coordinates the complete 16 stage
source to serving workflow. It records stage timings and outcomes in an atomic
JSON manifest, uses SHA256 publication identity to skip unchanged snapshots,
supports recovery of incomplete snapshots and preserves strict dependency
ordering across ingestion, validation, staging, warehouse, analytics and
serving operations.

Preview the ordered execution plan without connecting to SQL Server, building
an Azure package or changing platform state:

```bash
python -m transport_platform.orchestration.refresh_platform \
  --dry-run \
  --skip-package \
  --manifest data/processed/orchestration/dry_run.json
```

Run a governed local refresh when SQL Server and the required environment
settings are available:

```bash
python -m transport_platform.orchestration.refresh_platform \
  --manifest data/processed/orchestration/latest_refresh.json
```

The optional `--force` flag reprocesses an existing publication, while
`--skip-package` completes the analytical export without rebuilding the Azure
deployment package. The orchestrator never deploys to Azure automatically.

The GitHub Actions quality gate runs automatically for changes to `main` and
for pull requests targeting `main`, and it can also be started manually. It
uses an independent Ubuntu runner with Python 3.12 to perform these checks:

1. Installs the project and development dependencies.
2. Runs Ruff across the repository.
3. Runs the complete automated test suite.
4. Executes the orchestration dry run.
5. Validates that all 16 stages are planned and Azure deployment is disabled.
6. Retains the validated orchestration manifest as workflow evidence for 14
   days.

The workflow has read only repository permission and contains no Azure login,
SQL Server credential or web application deployment step. This separation
allows continuous integration to verify code and orchestration behaviour
without consuming production hosting allowance or exposing engineering data.

## Data layers

| Layer | Responsibility |
|---|---|
| Raw | Preserved GTFS ZIP files and download metadata |
| Staging | Source shaped GTFS records with snapshot lineage |
| Warehouse | Typed dimensions, bridges, facts and publication history |
| Analytics | Approved reporting and application views |
| Governance | Snapshot, pipeline and data quality audit records |
| Serving | Compact SQLite export containing approved dashboard data only |

Detailed source mappings are recorded in
[Source to warehouse mapping](docs/source_to_warehouse_mapping.md).

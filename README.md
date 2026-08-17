# Greater Manchester Transport Data Platform

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
applies `sql/ddl/001` through `sql/ddl/011` in order. It is safe to run the
current idempotent DDL scripts again.

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

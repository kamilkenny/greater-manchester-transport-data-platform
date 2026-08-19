# Greater Manchester Transport Intelligence Platform

[![Quality gate](https://github.com/kamilkenny/greater-manchester-transport-data-platform/actions/workflows/quality-gate.yml/badge.svg)](https://github.com/kamilkenny/greater-manchester-transport-data-platform/actions/workflows/quality-gate.yml)
[![Production refresh](https://github.com/kamilkenny/greater-manchester-transport-data-platform/actions/workflows/refresh-production.yml/badge.svg)](https://github.com/kamilkenny/greater-manchester-transport-data-platform/actions/workflows/refresh-production.yml)

A cloud based public transport data engineering and service intelligence platform built from Transport for Greater Manchester (TfGM) GTFS timetable publications.

The platform preserves source publications, validates and models transport data in Azure SQL, creates governed analytical datasets and publishes a FastAPI dashboard through Azure App Service.

**Live dashboard:**  
https://gm-transport-intelligence-kamil.azurewebsites.net/

> This platform analyses scheduled public transport services. It is not a real time vehicle tracking, passenger demand or punctuality system.

## Architecture

```mermaid
flowchart LR
    A[TfGM GTFS] --> B[GitHub Actions]
    B --> C{New publication?}
    C -->|No| D[Stop safely]
    C -->|Yes| E[Raw Snapshot]
    E --> F[Staging]
    F --> G[Azure SQL Warehouse]
    G --> H[Governed Analytics]
    H --> I[SQLite Serving Layer]
    I --> J[FastAPI]
    J --> K[Azure App Service]
    L[Microsoft Fabric Data Factory] -. Orchestration .-> G

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class AnalyticsRepository:
    """Read only access to the governed SQLite serving contract."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise FileNotFoundError(
                f"Serving database is unavailable: {self.database_path}"
            )
        connection = sqlite3.connect(
            f"file:{self.database_path}?mode=ro",
            uri=True,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON;")
        return connection

    def _one(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
        return None if row is None else dict(row)

    def _all(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def health(self) -> dict[str, Any]:
        """Return serving database availability and integrity metadata."""

        with self._connect() as connection:
            integrity = connection.execute("PRAGMA quick_check;").fetchone()[0]
            metadata_rows = connection.execute(
                "SELECT metadata_key, metadata_value FROM serving_metadata;"
            ).fetchall()
        metadata = {row[0]: row[1] for row in metadata_rows}
        return {
            "status": "ok" if integrity == "ok" else "degraded",
            "database_integrity": integrity,
            "database_size_bytes": self.database_path.stat().st_size,
            **metadata,
        }

    def overview(self) -> dict[str, Any]:
        """Return the compact executive dashboard payload."""

        kpis = self._one("SELECT * FROM dashboard_kpis LIMIT 1;")
        platform = self._one("SELECT * FROM platform_summary LIMIT 1;")
        metadata_rows = self._all(
            "SELECT metadata_key, metadata_value FROM serving_metadata;"
        )
        metadata = {
            str(row["metadata_key"]): row["metadata_value"]
            for row in metadata_rows
        }
        return {
            "kpis": kpis or {},
            "platform": platform or {},
            "metadata": metadata,
            "methodology": (
                "Scheduled comparative intelligence derived from published "
                "GTFS timetable data. Scores do not measure live punctuality, "
                "reliability, disruption or passenger demand."
            ),
        }

    def network_trends(
        self,
        *,
        days: int,
        mode: str | None,
    ) -> list[dict[str, Any]]:
        """Return daily scheduled network activity for charting."""

        bounded_days = max(7, min(days, 366))
        parameters: list[object] = [f"-{bounded_days - 1} days"]
        mode_filter = ""
        if mode:
            mode_filter = "AND transport_mode = ?"
            parameters.append(mode)

        return self._all(
            f"""
            SELECT
                service_date,
                SUM(active_route_count) AS active_route_count,
                SUM(scheduled_trip_count) AS scheduled_trip_count,
                SUM(scheduled_stop_event_count) AS scheduled_stop_event_count,
                ROUND(AVG(average_headway_minutes), 2)
                    AS average_headway_minutes
            FROM network_daily_summary
            WHERE
                service_date >= date(
                    (SELECT MAX(service_date) FROM network_daily_summary),
                    ?
                )
                {mode_filter}
            GROUP BY service_date
            ORDER BY service_date;
            """,
            tuple(parameters),
        )

    def modes(self) -> list[dict[str, Any]]:
        """Return transport mode comparisons."""

        return self._all(
            """
            SELECT
                transport_mode,
                route_count,
                operator_count,
                total_scheduled_trips,
                total_scheduled_stop_events,
                average_route_daily_trips,
                average_route_stop_coverage,
                average_service_span_minutes,
                average_headway_minutes
            FROM transport_mode_summary
            ORDER BY total_scheduled_trips DESC;
            """
        )

    def routes(
        self,
        *,
        limit: int,
        mode: str | None,
        sort_by: str,
    ) -> list[dict[str, Any]]:
        """Return ranked scheduled route intelligence."""

        order_columns = {
            "service": "network_service_rank ASC",
            "trips": "average_daily_trips DESC",
            "frequency": "average_headway_minutes ASC",
            "coverage": "average_daily_unique_stops DESC",
        }
        order_by = order_columns.get(sort_by, order_columns["service"])
        bounded_limit = max(1, min(limit, 100))
        parameters: list[object] = []
        mode_filter = ""
        if mode:
            mode_filter = "WHERE transport_mode = ?"
            parameters.append(mode)
        parameters.append(bounded_limit)

        return self._all(
            f"""
            SELECT
                network_service_rank,
                route_id,
                route_display_name,
                operator_name,
                transport_mode,
                route_colour,
                route_text_colour,
                scheduled_service_score,
                scheduled_service_band,
                frequency_band,
                average_daily_trips,
                average_daily_unique_stops,
                average_service_span_minutes,
                average_headway_minutes,
                total_scheduled_trips
            FROM route_service_intelligence
            {mode_filter}
            ORDER BY {order_by}, route_id
            LIMIT ?;
            """,
            tuple(parameters),
        )

    def stops(
        self,
        *,
        limit: int,
        search: str | None,
    ) -> list[dict[str, Any]]:
        """Return ranked stop and interchange intelligence."""

        bounded_limit = max(1, min(limit, 250))
        parameters: list[object] = []
        search_filter = ""
        if search:
            search_filter = "WHERE stop_name LIKE ? OR stop_code LIKE ?"
            pattern = f"%{search.strip()}%"
            parameters.extend((pattern, pattern))
        parameters.append(bounded_limit)

        return self._all(
            f"""
            SELECT
                network_activity_rank,
                stop_id,
                stop_code,
                stop_name,
                stop_latitude,
                stop_longitude,
                zone_id,
                accessibility_status,
                scheduled_activity_score,
                scheduled_activity_band,
                average_daily_trips,
                average_daily_routes,
                average_service_span_minutes,
                average_headway_minutes,
                total_scheduled_trips
            FROM stop_service_intelligence
            {search_filter}
            ORDER BY network_activity_rank, stop_id
            LIMIT ?;
            """,
            tuple(parameters),
        )

    def map_stops(self, *, limit: int) -> list[dict[str, Any]]:
        """Return the strongest geocoded stops for the network map."""

        bounded_limit = max(100, min(limit, 5_000))
        return self._all(
            """
            SELECT
                stop_id,
                stop_name,
                stop_latitude,
                stop_longitude,
                accessibility_status,
                scheduled_activity_score,
                scheduled_activity_band,
                average_daily_trips,
                average_daily_routes
            FROM stop_service_intelligence
            WHERE stop_latitude IS NOT NULL AND stop_longitude IS NOT NULL
            ORDER BY network_activity_rank, stop_id
            LIMIT ?;
            """,
            (bounded_limit,),
        )

    def operators(self, *, limit: int) -> list[dict[str, Any]]:
        """Return operator level scheduled network summaries."""

        bounded_limit = max(1, min(limit, 100))
        return self._all(
            """
            SELECT
                agency_id,
                operator_name,
                route_count,
                total_scheduled_trips,
                total_scheduled_stop_events,
                average_route_daily_trips,
                average_route_stop_coverage,
                average_service_span_minutes,
                average_headway_minutes
            FROM operator_summary
            ORDER BY total_scheduled_trips DESC, operator_name
            LIMIT ?;
            """,
            (bounded_limit,),
        )

    def locations(self) -> list[dict[str, Any]]:
        """Return grouped geographical coverage and accessibility."""

        return self._all(
            """
            SELECT
                location_group,
                stop_count,
                total_scheduled_trips,
                average_stop_daily_trips,
                average_route_choice,
                accessible_stop_count,
                inaccessible_stop_count,
                unknown_accessibility_count,
                centre_latitude,
                centre_longitude
            FROM location_summary
            ORDER BY total_scheduled_trips DESC;
            """
        )

    def publication_changes(self, *, limit: int) -> dict[str, Any]:
        """Return publication comparison summaries and recent changes."""

        bounded_limit = max(1, min(limit, 200))
        summary = self._all(
            """
            SELECT
                previous_snapshot_key,
                previous_downloaded_at_utc,
                current_snapshot_key,
                current_downloaded_at_utc,
                entity_type,
                change_type,
                change_count,
                first_detected_at_utc,
                last_detected_at_utc
            FROM publication_change_summary
            ORDER BY current_snapshot_key DESC, change_count DESC;
            """
        )
        changes = self._all(
            """
            SELECT
                current_snapshot_key,
                current_downloaded_at_utc,
                entity_type,
                entity_id,
                change_type,
                changed_fields,
                detected_at_utc
            FROM publication_changes
            ORDER BY detected_at_utc DESC, publication_change_key DESC
            LIMIT ?;
            """,
            (bounded_limit,),
        )
        return {"summary": summary, "changes": changes}

    def pipelines(self) -> dict[str, Any]:
        """Return current pipeline health and recent execution history."""

        health = self._all(
            """
            SELECT
                pipeline_name,
                latest_pipeline_run_key,
                latest_run_status,
                latest_started_at_utc,
                latest_completed_at_utc,
                latest_duration_milliseconds,
                latest_rows_read,
                latest_rows_loaded,
                latest_rows_rejected,
                latest_error_message,
                recent_run_count,
                recent_success_count,
                recent_failure_count,
                recent_success_rate_pct,
                pipeline_health_status
            FROM pipeline_health
            ORDER BY
                CASE pipeline_health_status
                    WHEN 'ACTION REQUIRED' THEN 1
                    WHEN 'RUNNING' THEN 2
                    WHEN 'WATCH' THEN 3
                    WHEN 'RECOVERED' THEN 4
                    ELSE 5
                END,
                pipeline_name;
            """
        )
        recent = self._all(
            """
            SELECT
                pipeline_run_key,
                pipeline_name,
                run_status,
                started_at_utc,
                completed_at_utc,
                duration_milliseconds,
                rows_read,
                rows_loaded,
                rows_rejected,
                error_message
            FROM recent_pipeline_runs
            ORDER BY started_at_utc DESC, pipeline_run_key DESC
            LIMIT 40;
            """
        )
        return {"health": health, "recent_runs": recent}

    def data_quality(self, *, limit: int) -> dict[str, Any]:
        """Return recent governed data quality observations."""

        bounded_limit = max(1, min(limit, 500))
        results = self._all(
            """
            SELECT
                pipeline_name,
                check_name,
                check_category,
                table_name,
                check_status,
                records_checked,
                failed_records,
                threshold_value,
                observed_value,
                details,
                checked_at_utc
            FROM data_quality_results
            ORDER BY checked_at_utc DESC, data_quality_result_key DESC
            LIMIT ?;
            """,
            (bounded_limit,),
        )
        counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for result in results:
            status = str(result.get("check_status", ""))
            if status in counts:
                counts[status] += 1
        return {"counts": counts, "results": results}

/*
Builds route and stop service day analytical facts from validated timetable
warehouse records.

Trip and stop patterns are aggregated once, then expanded through active
service dates in bounded date batches. Each batch is committed independently
when the procedure is executed on an autocommit connection.

The default reporting window begins on the snapshot download date and covers
366 days. Explicit parameters can select another controlled window.

Prerequisites:
    002_create_governance_tables.sql
    006_create_warehouse_core_dimensions.sql
    007_create_warehouse_network_dimensions.sql
    008_create_warehouse_service_dimensions.sql
    009_create_warehouse_schedule_tables.sql
    010_create_warehouse_daily_facts.sql
    014_create_service_calendar_loader.sql
    015_create_trip_dimension_loader.sql
    018_validate_scheduled_stop_event_source.sql
    019_create_scheduled_stop_event_batch_loader.sql
*/

CREATE OR ALTER PROCEDURE warehouse.load_daily_service_facts
    @snapshot_key BIGINT,
    @date_batch_days INT = 31,
    @reporting_start_date DATE = NULL,
    @reporting_horizon_days INT = 366
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @stop_event_rows_read BIGINT;
    DECLARE @service_date_rows_read BIGINT;
    DECLARE @route_fact_rows_derived BIGINT = 0;
    DECLARE @route_fact_rows_inserted BIGINT = 0;
    DECLARE @stop_fact_rows_derived BIGINT = 0;
    DECLARE @stop_fact_rows_inserted BIGINT = 0;
    DECLARE @batches_completed INT = 0;
    DECLARE @snapshot_date DATE;
    DECLARE @source_minimum_service_date DATE;
    DECLARE @source_maximum_service_date DATE;
    DECLARE @minimum_service_date DATE;
    DECLARE @maximum_service_date DATE;
    DECLARE @batch_start_date DATE;
    DECLARE @batch_end_date DATE;
    DECLARE @batch_route_rows BIGINT;
    DECLARE @batch_stop_rows BIGINT;
    DECLARE @target_route_rows BIGINT;
    DECLARE @target_stop_rows BIGINT;

    IF
        @date_batch_days IS NULL
        OR @date_batch_days < 1
        OR @date_batch_days > 366
    BEGIN
        THROW 50601, 'The date batch size must be between 1 and 366 days.', 1;
    END;

    IF
        @reporting_horizon_days IS NULL
        OR @reporting_horizon_days < 1
        OR @reporting_horizon_days > 3660
    BEGIN
        THROW 50616, 'The reporting horizon must be between 1 and 3660 days.', 1;
    END;

    SELECT
        @snapshot_date = CONVERT(DATE, downloaded_at_utc)
    FROM governance.source_snapshot
    WHERE
        snapshot_key = @snapshot_key
        AND snapshot_status = 'LOADED';

    IF @snapshot_date IS NULL
    BEGIN
        THROW 50602, 'The snapshot must exist and have LOADED status.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_service_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50603, 'The service calendar warehouse must load first.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_trip_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50604, 'The trip warehouse dimension must load first.', 1;
    END;

    IF NOT EXISTS (
        SELECT 1
        FROM governance.pipeline_run
        WHERE
            snapshot_key = @snapshot_key
            AND pipeline_name = 'load_gtfs_scheduled_stop_event_warehouse'
            AND run_status = 'SUCCEEDED'
    )
    BEGIN
        THROW 50605, 'The scheduled stop event warehouse must load first.', 1;
    END;

    SELECT
        @source_minimum_service_date = MIN(service_date.full_date),
        @source_maximum_service_date = MAX(service_date.full_date)
    FROM warehouse.bridge_service_date AS bridge
    INNER JOIN warehouse.dim_date AS service_date
        ON service_date.date_key = bridge.date_key
    WHERE bridge.snapshot_key = @snapshot_key;

    IF @source_minimum_service_date IS NULL
    BEGIN
        THROW 50607, 'The snapshot has no active service dates.', 1;
    END;

    SET @minimum_service_date = COALESCE(
        @reporting_start_date,
        @snapshot_date
    );

    IF @minimum_service_date < @source_minimum_service_date
    BEGIN
        SET @minimum_service_date = @source_minimum_service_date;
    END;

    IF @minimum_service_date > @source_maximum_service_date
    BEGIN
        THROW 50617, 'The reporting window begins after all service dates.', 1;
    END;

    SET @maximum_service_date = DATEADD(
        DAY,
        @reporting_horizon_days - 1,
        @minimum_service_date
    );

    IF @maximum_service_date > @source_maximum_service_date
    BEGIN
        SET @maximum_service_date = @source_maximum_service_date;
    END;

    CREATE TABLE #participating_service (
        service_key BIGINT NOT NULL,
        PRIMARY KEY CLUSTERED (service_key)
    );

    INSERT INTO #participating_service (service_key)
    SELECT DISTINCT
        bridge.service_key
    FROM warehouse.bridge_service_date AS bridge
    INNER JOIN warehouse.dim_date AS service_date
        ON service_date.date_key = bridge.date_key
    WHERE
        bridge.snapshot_key = @snapshot_key
        AND service_date.full_date BETWEEN
            @minimum_service_date AND @maximum_service_date;

    SELECT
        @service_date_rows_read = COUNT_BIG(*)
    FROM warehouse.bridge_service_date AS bridge
    INNER JOIN warehouse.dim_date AS service_date
        ON service_date.date_key = bridge.date_key
    WHERE
        bridge.snapshot_key = @snapshot_key
        AND service_date.full_date BETWEEN
            @minimum_service_date AND @maximum_service_date;

    SELECT
        @stop_event_rows_read = COUNT_BIG(*)
    FROM warehouse.fact_scheduled_stop_event AS event
    INNER JOIN warehouse.dim_trip AS trip
        ON trip.snapshot_key = @snapshot_key
        AND trip.trip_key = event.trip_key
    INNER JOIN #participating_service AS participating
        ON participating.service_key = trip.service_key
    WHERE event.snapshot_key = @snapshot_key;

    IF @stop_event_rows_read = 0
    BEGIN
        THROW 50606, 'The reporting window has no scheduled stop events.', 1;
    END;

    IF @service_date_rows_read = 0
    BEGIN
        THROW 50618, 'The reporting window has no active service dates.', 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM warehouse.fact_scheduled_stop_event AS event
        INNER JOIN warehouse.dim_trip AS trip
            ON trip.snapshot_key = @snapshot_key
            AND trip.trip_key = event.trip_key
        INNER JOIN #participating_service AS participating
            ON participating.service_key = trip.service_key
        WHERE event.snapshot_key = @snapshot_key
        GROUP BY event.trip_key
        HAVING MAX(event.arrival_seconds) < MIN(event.departure_seconds)
    )
    BEGIN
        THROW 50609, 'A trip has an invalid derived service span.', 1;
    END;

    CREATE TABLE #trip_event_metric (
        trip_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        service_key BIGINT NOT NULL,
        stop_event_count BIGINT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_departure_seconds INT NOT NULL,
        last_arrival_seconds INT NOT NULL,
        PRIMARY KEY CLUSTERED (trip_key)
    );

    INSERT INTO #trip_event_metric (
        trip_key,
        route_key,
        service_key,
        stop_event_count,
        first_departure_seconds,
        last_departure_seconds,
        last_arrival_seconds
    )
    SELECT
        trip.trip_key,
        trip.route_key,
        trip.service_key,
        COUNT_BIG(*),
        MIN(event.departure_seconds),
        MAX(event.departure_seconds),
        MAX(event.arrival_seconds)
    FROM warehouse.dim_trip AS trip
    INNER JOIN warehouse.fact_scheduled_stop_event AS event
        ON event.snapshot_key = @snapshot_key
        AND event.trip_key = trip.trip_key
    INNER JOIN #participating_service AS participating
        ON participating.service_key = trip.service_key
    WHERE trip.snapshot_key = @snapshot_key
    GROUP BY
        trip.trip_key,
        trip.route_key,
        trip.service_key;

    CREATE INDEX IX_trip_event_metric_service_route
        ON #trip_event_metric (
            service_key,
            route_key
        );

    CREATE TABLE #trip_stop_metric (
        trip_key BIGINT NOT NULL,
        stop_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        service_key BIGINT NOT NULL,
        departure_seconds INT NOT NULL,
        PRIMARY KEY CLUSTERED (
            trip_key,
            stop_key
        )
    );

    INSERT INTO #trip_stop_metric (
        trip_key,
        stop_key,
        route_key,
        service_key,
        departure_seconds
    )
    SELECT
        trip.trip_key,
        event.stop_key,
        trip.route_key,
        trip.service_key,
        MIN(event.departure_seconds)
    FROM warehouse.dim_trip AS trip
    INNER JOIN warehouse.fact_scheduled_stop_event AS event
        ON event.snapshot_key = @snapshot_key
        AND event.trip_key = trip.trip_key
    INNER JOIN #participating_service AS participating
        ON participating.service_key = trip.service_key
    WHERE trip.snapshot_key = @snapshot_key
    GROUP BY
        trip.trip_key,
        event.stop_key,
        trip.route_key,
        trip.service_key;

    CREATE INDEX IX_trip_stop_metric_service_stop
        ON #trip_stop_metric (
            service_key,
            stop_key,
            route_key
        )
        INCLUDE (
            trip_key,
            departure_seconds
        );

    CREATE TABLE #service_route_metric (
        service_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        scheduled_trip_count BIGINT NOT NULL,
        scheduled_stop_event_count BIGINT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_departure_seconds INT NOT NULL,
        last_arrival_seconds INT NOT NULL,
        PRIMARY KEY CLUSTERED (
            service_key,
            route_key
        )
    );

    INSERT INTO #service_route_metric (
        service_key,
        route_key,
        scheduled_trip_count,
        scheduled_stop_event_count,
        first_departure_seconds,
        last_departure_seconds,
        last_arrival_seconds
    )
    SELECT
        service_key,
        route_key,
        COUNT_BIG(*),
        SUM(stop_event_count),
        MIN(first_departure_seconds),
        MAX(last_departure_seconds),
        MAX(last_arrival_seconds)
    FROM #trip_event_metric
    GROUP BY
        service_key,
        route_key;

    CREATE TABLE #service_route_stop (
        service_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        stop_key BIGINT NOT NULL,
        PRIMARY KEY CLUSTERED (
            service_key,
            route_key,
            stop_key
        )
    );

    INSERT INTO #service_route_stop (
        service_key,
        route_key,
        stop_key
    )
    SELECT DISTINCT
        service_key,
        route_key,
        stop_key
    FROM #trip_stop_metric;

    CREATE TABLE #service_stop_metric (
        service_key BIGINT NOT NULL,
        stop_key BIGINT NOT NULL,
        scheduled_trip_count BIGINT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_departure_seconds INT NOT NULL,
        PRIMARY KEY CLUSTERED (
            service_key,
            stop_key
        )
    );

    INSERT INTO #service_stop_metric (
        service_key,
        stop_key,
        scheduled_trip_count,
        first_departure_seconds,
        last_departure_seconds
    )
    SELECT
        service_key,
        stop_key,
        COUNT_BIG(*),
        MIN(departure_seconds),
        MAX(departure_seconds)
    FROM #trip_stop_metric
    GROUP BY
        service_key,
        stop_key;

    CREATE TABLE #service_stop_route (
        service_key BIGINT NOT NULL,
        stop_key BIGINT NOT NULL,
        route_key BIGINT NOT NULL,
        PRIMARY KEY CLUSTERED (
            service_key,
            stop_key,
            route_key
        )
    );

    INSERT INTO #service_stop_route (
        service_key,
        stop_key,
        route_key
    )
    SELECT DISTINCT
        service_key,
        stop_key,
        route_key
    FROM #trip_stop_metric;

    CREATE TABLE #desired_route_fact (
        snapshot_key BIGINT NOT NULL,
        date_key INT NOT NULL,
        route_key BIGINT NOT NULL,
        operator_key BIGINT NOT NULL,
        scheduled_trip_count INT NOT NULL,
        scheduled_stop_event_count INT NOT NULL,
        unique_stop_count INT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_arrival_seconds INT NOT NULL,
        service_span_minutes DECIMAL(12, 2) NOT NULL,
        average_headway_minutes DECIMAL(12, 2) NULL,
        PRIMARY KEY CLUSTERED (
            snapshot_key,
            date_key,
            route_key
        )
    );

    CREATE TABLE #desired_stop_fact (
        snapshot_key BIGINT NOT NULL,
        date_key INT NOT NULL,
        stop_key BIGINT NOT NULL,
        scheduled_trip_count INT NOT NULL,
        scheduled_route_count INT NOT NULL,
        first_departure_seconds INT NOT NULL,
        last_departure_seconds INT NOT NULL,
        service_span_minutes DECIMAL(12, 2) NOT NULL,
        average_headway_minutes DECIMAL(12, 2) NULL,
        PRIMARY KEY CLUSTERED (
            snapshot_key,
            date_key,
            stop_key
        )
    );

    SET @batch_start_date = @minimum_service_date;

    WHILE @batch_start_date <= @maximum_service_date
    BEGIN
        SET @batch_end_date = DATEADD(
            DAY,
            @date_batch_days - 1,
            @batch_start_date
        );

        IF @batch_end_date > @maximum_service_date
        BEGIN
            SET @batch_end_date = @maximum_service_date;
        END;

        TRUNCATE TABLE #desired_route_fact;
        TRUNCATE TABLE #desired_stop_fact;

        ;WITH route_base AS (
            SELECT
                bridge.date_key,
                metric.route_key,
                SUM(metric.scheduled_trip_count) AS scheduled_trip_count,
                SUM(metric.scheduled_stop_event_count)
                    AS scheduled_stop_event_count,
                MIN(metric.first_departure_seconds)
                    AS first_departure_seconds,
                MAX(metric.last_departure_seconds)
                    AS last_departure_seconds,
                MAX(metric.last_arrival_seconds)
                    AS last_arrival_seconds
            FROM #service_route_metric AS metric
            INNER JOIN warehouse.bridge_service_date AS bridge
                ON bridge.snapshot_key = @snapshot_key
                AND bridge.service_key = metric.service_key
            INNER JOIN warehouse.dim_date AS service_date
                ON service_date.date_key = bridge.date_key
            WHERE service_date.full_date BETWEEN
                @batch_start_date AND @batch_end_date
            GROUP BY
                bridge.date_key,
                metric.route_key
        ),
        route_stop_count AS (
            SELECT
                bridge.date_key,
                source.route_key,
                COUNT(DISTINCT source.stop_key) AS unique_stop_count
            FROM #service_route_stop AS source
            INNER JOIN warehouse.bridge_service_date AS bridge
                ON bridge.snapshot_key = @snapshot_key
                AND bridge.service_key = source.service_key
            INNER JOIN warehouse.dim_date AS service_date
                ON service_date.date_key = bridge.date_key
            WHERE service_date.full_date BETWEEN
                @batch_start_date AND @batch_end_date
            GROUP BY
                bridge.date_key,
                source.route_key
        )
        INSERT INTO #desired_route_fact (
            snapshot_key,
            date_key,
            route_key,
            operator_key,
            scheduled_trip_count,
            scheduled_stop_event_count,
            unique_stop_count,
            first_departure_seconds,
            last_arrival_seconds,
            service_span_minutes,
            average_headway_minutes
        )
        SELECT
            @snapshot_key,
            base.date_key,
            base.route_key,
            route.operator_key,
            CONVERT(INT, base.scheduled_trip_count),
            CONVERT(INT, base.scheduled_stop_event_count),
            stop_count.unique_stop_count,
            base.first_departure_seconds,
            base.last_arrival_seconds,
            CONVERT(
                DECIMAL(12, 2),
                (base.last_arrival_seconds - base.first_departure_seconds)
                    / 60.0
            ),
            CASE
                WHEN base.scheduled_trip_count > 1 THEN
                    CONVERT(
                        DECIMAL(12, 2),
                        (
                            base.last_departure_seconds
                            - base.first_departure_seconds
                        ) / (60.0 * (base.scheduled_trip_count - 1))
                    )
                ELSE NULL
            END
        FROM route_base AS base
        INNER JOIN route_stop_count AS stop_count
            ON stop_count.date_key = base.date_key
            AND stop_count.route_key = base.route_key
        INNER JOIN warehouse.dim_route AS route
            ON route.route_key = base.route_key;

        SET @batch_route_rows = @@ROWCOUNT;
        SET @route_fact_rows_derived += @batch_route_rows;

        ;WITH stop_base AS (
            SELECT
                bridge.date_key,
                metric.stop_key,
                SUM(metric.scheduled_trip_count) AS scheduled_trip_count,
                MIN(metric.first_departure_seconds)
                    AS first_departure_seconds,
                MAX(metric.last_departure_seconds)
                    AS last_departure_seconds
            FROM #service_stop_metric AS metric
            INNER JOIN warehouse.bridge_service_date AS bridge
                ON bridge.snapshot_key = @snapshot_key
                AND bridge.service_key = metric.service_key
            INNER JOIN warehouse.dim_date AS service_date
                ON service_date.date_key = bridge.date_key
            WHERE service_date.full_date BETWEEN
                @batch_start_date AND @batch_end_date
            GROUP BY
                bridge.date_key,
                metric.stop_key
        ),
        stop_route_count AS (
            SELECT
                bridge.date_key,
                source.stop_key,
                COUNT(DISTINCT source.route_key) AS scheduled_route_count
            FROM #service_stop_route AS source
            INNER JOIN warehouse.bridge_service_date AS bridge
                ON bridge.snapshot_key = @snapshot_key
                AND bridge.service_key = source.service_key
            INNER JOIN warehouse.dim_date AS service_date
                ON service_date.date_key = bridge.date_key
            WHERE service_date.full_date BETWEEN
                @batch_start_date AND @batch_end_date
            GROUP BY
                bridge.date_key,
                source.stop_key
        )
        INSERT INTO #desired_stop_fact (
            snapshot_key,
            date_key,
            stop_key,
            scheduled_trip_count,
            scheduled_route_count,
            first_departure_seconds,
            last_departure_seconds,
            service_span_minutes,
            average_headway_minutes
        )
        SELECT
            @snapshot_key,
            base.date_key,
            base.stop_key,
            CONVERT(INT, base.scheduled_trip_count),
            route_count.scheduled_route_count,
            base.first_departure_seconds,
            base.last_departure_seconds,
            CONVERT(
                DECIMAL(12, 2),
                (base.last_departure_seconds - base.first_departure_seconds)
                    / 60.0
            ),
            CASE
                WHEN base.scheduled_trip_count > 1 THEN
                    CONVERT(
                        DECIMAL(12, 2),
                        (
                            base.last_departure_seconds
                            - base.first_departure_seconds
                        ) / (60.0 * (base.scheduled_trip_count - 1))
                    )
                ELSE NULL
            END
        FROM stop_base AS base
        INNER JOIN stop_route_count AS route_count
            ON route_count.date_key = base.date_key
            AND route_count.stop_key = base.stop_key;

        SET @batch_stop_rows = @@ROWCOUNT;
        SET @stop_fact_rows_derived += @batch_stop_rows;

        BEGIN TRY
            BEGIN TRANSACTION;

            IF EXISTS (
                SELECT 1
                FROM #desired_route_fact AS desired
                INNER JOIN warehouse.fact_route_service_day AS target
                    ON target.snapshot_key = desired.snapshot_key
                    AND target.date_key = desired.date_key
                    AND target.route_key = desired.route_key
                WHERE
                    target.operator_key <> desired.operator_key
                    OR target.scheduled_trip_count <>
                        desired.scheduled_trip_count
                    OR target.scheduled_stop_event_count <>
                        desired.scheduled_stop_event_count
                    OR target.unique_stop_count <> desired.unique_stop_count
                    OR target.first_departure_seconds <>
                        desired.first_departure_seconds
                    OR target.last_arrival_seconds <>
                        desired.last_arrival_seconds
                    OR target.service_span_minutes <>
                        desired.service_span_minutes
                    OR ISNULL(target.average_headway_minutes, -1) <>
                        ISNULL(desired.average_headway_minutes, -1)
            )
            BEGIN
                THROW 50610, 'Existing route service day facts conflict.', 1;
            END;

            IF EXISTS (
                SELECT 1
                FROM warehouse.fact_route_service_day AS target
                INNER JOIN warehouse.dim_date AS target_date
                    ON target_date.date_key = target.date_key
                LEFT JOIN #desired_route_fact AS desired
                    ON desired.snapshot_key = target.snapshot_key
                    AND desired.date_key = target.date_key
                    AND desired.route_key = target.route_key
                WHERE
                    target.snapshot_key = @snapshot_key
                    AND target_date.full_date BETWEEN
                        @batch_start_date AND @batch_end_date
                    AND desired.route_key IS NULL
            )
            BEGIN
                THROW 50611, 'Existing route facts are absent from the source.', 1;
            END;

            INSERT INTO warehouse.fact_route_service_day (
                snapshot_key,
                date_key,
                route_key,
                operator_key,
                scheduled_trip_count,
                scheduled_stop_event_count,
                unique_stop_count,
                first_departure_seconds,
                last_arrival_seconds,
                service_span_minutes,
                average_headway_minutes
            )
            SELECT
                desired.snapshot_key,
                desired.date_key,
                desired.route_key,
                desired.operator_key,
                desired.scheduled_trip_count,
                desired.scheduled_stop_event_count,
                desired.unique_stop_count,
                desired.first_departure_seconds,
                desired.last_arrival_seconds,
                desired.service_span_minutes,
                desired.average_headway_minutes
            FROM #desired_route_fact AS desired
            LEFT JOIN warehouse.fact_route_service_day AS target
                ON target.snapshot_key = desired.snapshot_key
                AND target.date_key = desired.date_key
                AND target.route_key = desired.route_key
            WHERE target.route_key IS NULL;

            SET @route_fact_rows_inserted += @@ROWCOUNT;

            IF EXISTS (
                SELECT 1
                FROM #desired_stop_fact AS desired
                INNER JOIN warehouse.fact_stop_service_day AS target
                    ON target.snapshot_key = desired.snapshot_key
                    AND target.date_key = desired.date_key
                    AND target.stop_key = desired.stop_key
                WHERE
                    target.scheduled_trip_count <>
                        desired.scheduled_trip_count
                    OR target.scheduled_route_count <>
                        desired.scheduled_route_count
                    OR target.first_departure_seconds <>
                        desired.first_departure_seconds
                    OR target.last_departure_seconds <>
                        desired.last_departure_seconds
                    OR target.service_span_minutes <>
                        desired.service_span_minutes
                    OR ISNULL(target.average_headway_minutes, -1) <>
                        ISNULL(desired.average_headway_minutes, -1)
            )
            BEGIN
                THROW 50612, 'Existing stop service day facts conflict.', 1;
            END;

            IF EXISTS (
                SELECT 1
                FROM warehouse.fact_stop_service_day AS target
                INNER JOIN warehouse.dim_date AS target_date
                    ON target_date.date_key = target.date_key
                LEFT JOIN #desired_stop_fact AS desired
                    ON desired.snapshot_key = target.snapshot_key
                    AND desired.date_key = target.date_key
                    AND desired.stop_key = target.stop_key
                WHERE
                    target.snapshot_key = @snapshot_key
                    AND target_date.full_date BETWEEN
                        @batch_start_date AND @batch_end_date
                    AND desired.stop_key IS NULL
            )
            BEGIN
                THROW 50613, 'Existing stop facts are absent from the source.', 1;
            END;

            INSERT INTO warehouse.fact_stop_service_day (
                snapshot_key,
                date_key,
                stop_key,
                scheduled_trip_count,
                scheduled_route_count,
                first_departure_seconds,
                last_departure_seconds,
                service_span_minutes,
                average_headway_minutes
            )
            SELECT
                desired.snapshot_key,
                desired.date_key,
                desired.stop_key,
                desired.scheduled_trip_count,
                desired.scheduled_route_count,
                desired.first_departure_seconds,
                desired.last_departure_seconds,
                desired.service_span_minutes,
                desired.average_headway_minutes
            FROM #desired_stop_fact AS desired
            LEFT JOIN warehouse.fact_stop_service_day AS target
                ON target.snapshot_key = desired.snapshot_key
                AND target.date_key = desired.date_key
                AND target.stop_key = desired.stop_key
            WHERE target.stop_key IS NULL;

            SET @stop_fact_rows_inserted += @@ROWCOUNT;

            COMMIT TRANSACTION;
        END TRY
        BEGIN CATCH
            IF XACT_STATE() <> 0
            BEGIN
                ROLLBACK TRANSACTION;
            END;
            THROW;
        END CATCH;

        SET @batches_completed += 1;
        SET @batch_start_date = DATEADD(DAY, 1, @batch_end_date);
    END;

    SELECT
        @target_route_rows = COUNT_BIG(*)
    FROM warehouse.fact_route_service_day
    WHERE snapshot_key = @snapshot_key;

    SELECT
        @target_stop_rows = COUNT_BIG(*)
    FROM warehouse.fact_stop_service_day
    WHERE snapshot_key = @snapshot_key;

    IF @target_route_rows <> @route_fact_rows_derived
    BEGIN
        THROW 50614, 'The route fact target count is incomplete.', 1;
    END;

    IF @target_stop_rows <> @stop_fact_rows_derived
    BEGIN
        THROW 50615, 'The stop fact target count is incomplete.', 1;
    END;

    SELECT
        @minimum_service_date AS reporting_start_date,
        @maximum_service_date AS reporting_end_date,
        @stop_event_rows_read AS stop_event_rows_read,
        @service_date_rows_read AS service_date_rows_read,
        @route_fact_rows_derived AS route_fact_rows_derived,
        @route_fact_rows_inserted AS route_fact_rows_inserted,
        @stop_fact_rows_derived AS stop_fact_rows_derived,
        @stop_fact_rows_inserted AS stop_fact_rows_inserted,
        @batches_completed AS batches_completed;
END;

"use strict";

const AUTO_REFRESH_MS = 15 * 60 * 1000;

const state = {
    networkChart: null,
    modeChart: null,
    operatorChart: null,
    map: null,
    markers: null,
    overview: null,
};

const colours = {
    yellow: "#ffd400",
    mint: "#5cf2be",
    cyan: "#4ed7f2",
    violet: "#b59cff",
    orange: "#ff9e61",
    grid: "rgba(211, 235, 224, 0.09)",
    text: "#9db0a9",
};

const element = (id) => document.getElementById(id);

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function number(value, maximumFractionDigits = 0) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    return new Intl.NumberFormat("en-GB", { maximumFractionDigits }).format(numeric);
}

function compact(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    return new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 }).format(numeric);
}

function dateTime(value) {
    if (!value) return "Unavailable";
    const raw = String(value).replace(" ", "T");
    const normalised = /(?:Z|[+-]\d{2}:\d{2})$/.test(raw) ? raw : `${raw}Z`;
    const parsed = new Date(normalised);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
        timeZoneName: "short",
    }).format(parsed);
}

function duration(milliseconds) {
    const value = Number(milliseconds);
    if (!Number.isFinite(value)) return "Duration unavailable";
    if (value < 60_000) return `${number(value / 1000, 0)} seconds`;
    return `${number(value / 60_000, 1)} minutes`;
}

async function fetchJson(url) {
    const separator = url.includes("?") ? "&" : "?";
    const response = await fetch(`${url}${separator}refresh=${Date.now()}`, {
        headers: { Accept: "application/json" },
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `Request failed with status ${response.status}`);
    }
    return response.json();
}

function showToast(message) {
    const toast = element("toast");
    toast.textContent = message;
    toast.classList.add("visible");
    window.clearTimeout(showToast.timeout);
    showToast.timeout = window.setTimeout(() => toast.classList.remove("visible"), 3000);
}

function setGlobalStatus(status, label) {
    const statusElement = element("global-status");
    statusElement.className = `status-chip ${status}`;
    statusElement.innerHTML = `<i></i>${escapeHtml(label)}`;
}

function chartOptions() {
    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: "#152822",
                titleColor: "#ffffff",
                bodyColor: "#c6d3ce",
                borderColor: "rgba(211,235,224,.16)",
                borderWidth: 1,
                padding: 12,
            },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: { color: colours.text, maxTicksLimit: 7, font: { size: 10 } },
                border: { display: false },
            },
            y: {
                grid: { color: colours.grid },
                ticks: { color: colours.text, callback: (value) => compact(value), font: { size: 10 } },
                border: { display: false },
            },
        },
    };
}

function renderOverview(payload) {
    state.overview = payload;
    const kpis = payload.kpis || {};
    const platform = payload.platform || {};
    const metadata = payload.metadata || {};

    element("kpi-operators").textContent = number(kpis.operator_count);
    element("kpi-routes").textContent = number(kpis.route_count);
    element("kpi-high-frequency").textContent = number(kpis.high_frequency_route_count);
    element("kpi-stops").textContent = number(kpis.stop_count);
    element("kpi-hubs").textContent = number(kpis.major_hub_count);
    element("kpi-trips").textContent = compact(kpis.trip_count);
    element("kpi-events").textContent = compact(kpis.scheduled_stop_event_count);
    element("kpi-freshness").textContent = kpis.freshness_status || "Unknown";
    element("kpi-age").textContent = `${number(kpis.data_age_hours, 1)} hours since publication`;
    element("source-publication").textContent = dateTime(kpis.downloaded_at_utc);
    element("reporting-window").textContent = `${kpis.reporting_start_date || "—"} to ${kpis.reporting_end_date || "—"}`;
    element("serving-refresh").textContent = dateTime(metadata.exported_at_utc);
    element("methodology-note").textContent = payload.methodology;

    const ready = Number(kpis.service_ready_pipeline_count || 0);
    const monitored = Number(kpis.monitored_pipeline_count || 0);
    element("hero-health-count").textContent = `${ready}/${monitored}`;

    const freshness = String(kpis.freshness_status || "").toUpperCase();
    if (["CURRENT", "FRESH"].includes(freshness)) {
        setGlobalStatus("healthy", "Data current");
    } else if (freshness === "DELAYED") {
        setGlobalStatus("delayed", "Data delayed");
    } else {
        setGlobalStatus("healthy", "Serving online");
    }

    element("leading-route").textContent = kpis.leading_route || "—";
    element("leading-route-score").textContent = number(kpis.leading_route_score, 1);
}

function renderNetworkChart(rows) {
    if (!window.Chart) return;
    if (state.networkChart) state.networkChart.destroy();
    const context = element("network-chart");
    const options = chartOptions();
    options.scales.y1 = {
        position: "right",
        grid: { display: false },
        ticks: { color: colours.text, font: { size: 10 } },
        border: { display: false },
    };
    state.networkChart = new Chart(context, {
        type: "line",
        data: {
            labels: rows.map((row) => row.service_date),
            datasets: [
                {
                    label: "Scheduled trips",
                    data: rows.map((row) => row.scheduled_trip_count),
                    borderColor: colours.yellow,
                    backgroundColor: "rgba(255,212,0,.09)",
                    fill: true,
                    tension: .32,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
                {
                    label: "Active routes",
                    data: rows.map((row) => row.active_route_count),
                    borderColor: colours.mint,
                    backgroundColor: colours.mint,
                    yAxisID: "y1",
                    tension: .32,
                    borderWidth: 1.5,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                },
            ],
        },
        options,
    });
}

function renderModes(rows) {
    if (!window.Chart) return;
    const total = rows.reduce((sum, row) => sum + Number(row.total_scheduled_trips || 0), 0);
    element("mode-total").textContent = compact(total);
    element("mode-breakdown").innerHTML = rows.map((row, index) => {
        const share = total ? (Number(row.total_scheduled_trips) / total) * 100 : 0;
        const colour = [colours.yellow, colours.cyan, colours.violet][index % 3];
        return `<div class="mode-row"><i class="mode-dot" style="background:${colour}"></i><span>${escapeHtml(row.transport_mode)}</span><strong>${number(share, 1)}%</strong></div>`;
    }).join("");
    if (state.modeChart) state.modeChart.destroy();
    state.modeChart = new Chart(element("mode-chart"), {
        type: "doughnut",
        data: {
            labels: rows.map((row) => row.transport_mode),
            datasets: [{
                data: rows.map((row) => row.total_scheduled_trips),
                backgroundColor: [colours.yellow, colours.cyan, colours.violet],
                borderColor: "#10231e",
                borderWidth: 5,
                hoverOffset: 4,
            }],
        },
        options: {
            responsive: true,
            cutout: "74%",
            plugins: { legend: { display: false }, tooltip: chartOptions().plugins.tooltip },
        },
    });
}

function renderRoutes(rows) {
    const body = element("route-table");
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="6" class="loading-cell">No routes match this selection</td></tr>';
        return;
    }
    body.innerHTML = rows.map((row) => {
        const routeColour = /^([0-9a-f]{6})$/i.test(row.route_colour || "") ? `#${row.route_colour}` : colours.yellow;
        return `<tr>
            <td><span class="rank-number">${number(row.network_service_rank)}</span></td>
            <td><div class="route-cell"><i class="route-swatch" style="background:${routeColour}"></i><div><strong>${escapeHtml(row.route_display_name)}</strong><small>${escapeHtml(row.operator_name)}</small></div></div></td>
            <td><span class="mode-pill">${escapeHtml(row.transport_mode)}</span></td>
            <td><div class="score-cell"><strong>${number(row.scheduled_service_score, 1)}</strong><span class="mini-track"><span style="width:${Math.min(100, Number(row.scheduled_service_score || 0))}%"></span></span></div></td>
            <td>${number(row.average_daily_trips, 1)}</td>
            <td>${number(row.average_headway_minutes, 1)} min</td>
        </tr>`;
    }).join("");

    const leading = rows[0];
    element("leading-route").textContent = leading.route_display_name || leading.route_id;
    element("leading-route-mode").textContent = leading.transport_mode || "Mode unavailable";
    element("leading-route-operator").textContent = leading.operator_name || "Operator unavailable";
    element("leading-route-score").textContent = number(leading.scheduled_service_score, 1);
    element("leading-route-frequency").textContent = leading.frequency_band || "Unavailable";
    element("leading-route-trips").textContent = number(leading.average_daily_trips, 1);
    element("leading-route-coverage").textContent = number(leading.average_daily_unique_stops, 1);
}

function renderStops(rows) {
    const container = element("stop-list");
    if (!rows.length) {
        container.innerHTML = '<div class="loading-cell">No stops match this search</div>';
        return;
    }
    container.innerHTML = rows.map((row) => `<article class="stop-item">
        <span class="stop-rank">${number(row.network_activity_rank)}</span>
        <div class="stop-copy"><strong title="${escapeHtml(row.stop_name)}">${escapeHtml(row.stop_name)}</strong><span>${escapeHtml(row.scheduled_activity_band)} · ${number(row.average_daily_routes, 1)} routes</span></div>
        <div class="stop-score"><strong>${number(row.scheduled_activity_score, 1)}</strong><span>score</span></div>
    </article>`).join("");
}

function renderMap(rows) {
    element("map-count").textContent = `${number(rows.length)} leading stops`;
    if (!window.L) return;
    if (!state.map) {
        state.map = L.map("network-map", { zoomControl: false, preferCanvas: true }).setView([53.48, -2.24], 10);
        L.control.zoom({ position: "bottomright" }).addTo(state.map);
        L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
            attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
            maxZoom: 19,
        }).addTo(state.map);
        state.markers = L.layerGroup().addTo(state.map);
    }
    state.markers.clearLayers();
    const bounds = [];
    rows.forEach((row) => {
        const latitude = Number(row.stop_latitude);
        const longitude = Number(row.stop_longitude);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
        const score = Number(row.scheduled_activity_score || 0);
        const size = Math.max(7, Math.min(20, 6 + score / 9));
        const marker = L.circleMarker([latitude, longitude], {
            radius: size / 2,
            color: "rgba(255,255,255,.42)",
            weight: 1,
            fillColor: score >= 80 ? colours.yellow : score >= 60 ? colours.mint : colours.cyan,
            fillOpacity: .72,
        });
        marker.bindPopup(`<strong>${escapeHtml(row.stop_name)}</strong><br><span>Activity score ${number(score, 1)}</span><br><span>${number(row.average_daily_trips, 1)} average daily trips</span>`);
        marker.addTo(state.markers);
        bounds.push([latitude, longitude]);
    });
    if (bounds.length) state.map.fitBounds(bounds, { padding: [24, 24], maxZoom: 12 });
}

function renderOperators(rows) {
    if (!window.Chart) return;
    if (state.operatorChart) state.operatorChart.destroy();
    const options = chartOptions();
    options.indexAxis = "y";
    options.scales.x.ticks.callback = (value) => compact(value);
    options.scales.y.ticks.color = "#c6d3ce";
    state.operatorChart = new Chart(element("operator-chart"), {
        type: "bar",
        data: {
            labels: rows.map((row) => row.operator_name),
            datasets: [{
                data: rows.map((row) => row.total_scheduled_trips),
                backgroundColor: rows.map((_, index) => index === 0 ? colours.yellow : "rgba(92,242,190,.58)"),
                borderRadius: 7,
                borderSkipped: false,
                barThickness: 15,
            }],
        },
        options,
    });
}

function renderAccessibility(locations, overview) {
    const totalStops = Number(overview.kpis?.stop_count || 0);
    const accessible = locations.reduce((sum, row) => sum + Number(row.accessible_stop_count || 0), 0);
    const unknown = locations.reduce((sum, row) => sum + Number(row.unknown_accessibility_count || 0), 0);
    const share = totalStops ? (accessible / totalStops) * 100 : 0;
    element("accessible-stops").textContent = number(accessible);
    element("accessibility-progress").style.width = `${Math.max(1, share)}%`;
    element("accessibility-detail").textContent = `${number(share, 2)}% are explicitly reported accessible. ${number(unknown)} stops have unknown accessibility status in the source publication.`;
}

function statusClass(status) {
    return String(status || "").toLowerCase().replaceAll(" ", "-");
}

function humanPipelineName(name) {
    return String(name || "").replace(/^build_gtfs_|^load_gtfs_|^export_gtfs_/, "").replaceAll("_", " ");
}

function renderPipelines(payload) {
    const rows = payload.health || [];
    const ready = rows.filter((row) => ["HEALTHY", "RECOVERED"].includes(row.pipeline_health_status)).length;
    element("pipeline-count").textContent = `${number(rows.length)} pipelines`;
    element("operations-summary").textContent = `${ready} of ${rows.length} pipelines are service ready`;
    element("pipeline-grid").innerHTML = rows.map((row) => `<article class="pipeline-item ${statusClass(row.pipeline_health_status)}">
        <i class="pipeline-light"></i>
        <div class="pipeline-copy"><strong title="${escapeHtml(row.pipeline_name)}">${escapeHtml(humanPipelineName(row.pipeline_name))}</strong><span>${escapeHtml(row.pipeline_health_status)} · ${escapeHtml(duration(row.latest_duration_milliseconds))}</span></div>
        <span class="pipeline-rate">${number(row.recent_success_rate_pct, 0)}%</span>
    </article>`).join("");
}

function renderPublication(payload) {
    const container = element("publication-content");
    const changes = payload.changes || [];
    if (!changes.length) {
        container.className = "empty-state";
        container.innerHTML = '<span class="empty-icon">✓</span><strong>Baseline publication established</strong><p>No predecessor exists yet, so there are no added, removed or modified entities to report. Change intelligence activates with the next snapshot.</p>';
        return;
    }
    container.className = "change-list";
    container.innerHTML = changes.slice(0, 8).map((row) => `<article class="change-item"><strong>${escapeHtml(row.change_type)} ${escapeHtml(row.entity_type)}</strong><p>${escapeHtml(row.entity_id)} · ${escapeHtml(row.changed_fields || "Entity state changed")}</p></article>`).join("");
}

function renderDataQuality(payload) {
    const counts = payload.counts || {};
    const results = payload.results || [];
    element("quality-pass").textContent = number(counts.PASS || 0);
    element("quality-warn").textContent = number(counts.WARN || 0);
    element("quality-fail").textContent = number(counts.FAIL || 0);
    element("quality-total").textContent = `${number(results.length)} recent checks`;
    const container = element("quality-results");
    if (!results.length) {
        container.innerHTML = "<p>No governed data quality result records are published in this snapshot yet. The platform reports this absence explicitly rather than interpreting it as a pass.</p>";
        return;
    }
    container.innerHTML = `<div class="quality-list">${results.slice(0, 5).map((row) => `<div class="quality-result"><span><strong>${escapeHtml(row.check_name)}</strong><br>${escapeHtml(row.table_name || row.check_category)}</span><span class="band-pill">${escapeHtml(row.check_status)}</span></div>`).join("")}</div>`;
}

async function loadTrend() {
    const days = element("trend-days").value;
    const mode = element("trend-mode").value;
    const query = new URLSearchParams({ days });
    if (mode) query.set("mode", mode);
    renderNetworkChart(await fetchJson(`/api/network-trends?${query}`));
}

async function loadRoutes() {
    const query = new URLSearchParams({
        limit: "10",
        sort_by: element("route-sort").value,
    });
    const mode = element("route-mode").value;
    if (mode) query.set("mode", mode);
    renderRoutes(await fetchJson(`/api/routes?${query}`));
}

let searchTimer;
async function loadStops() {
    const query = new URLSearchParams({ limit: "12" });
    const search = element("stop-search").value.trim();
    if (search) query.set("search", search);
    renderStops(await fetchJson(`/api/stops?${query}`));
}

async function loadDashboard() {
    const refreshButton = element("refresh-button");
    refreshButton.classList.add("spinning");
    setGlobalStatus("loading", "Refreshing");
    try {
        const [overview, trends, modes, routes, stops, mapStops, operators, locations, publication, pipelines, quality] = await Promise.all([
            fetchJson("/api/overview"),
            fetchJson("/api/network-trends?days=90"),
            fetchJson("/api/modes"),
            fetchJson("/api/routes?limit=10"),
            fetchJson("/api/stops?limit=12"),
            fetchJson("/api/map-stops?limit=1500"),
            fetchJson("/api/operators?limit=10"),
            fetchJson("/api/locations"),
            fetchJson("/api/publication-changes?limit=50"),
            fetchJson("/api/pipelines"),
            fetchJson("/api/data-quality?limit=100"),
        ]);
        renderOverview(overview);
        renderNetworkChart(trends);
        renderModes(modes);
        renderRoutes(routes);
        renderStops(stops);
        renderMap(mapStops);
        renderOperators(operators);
        renderAccessibility(locations, overview);
        renderPublication(publication);
        renderPipelines(pipelines);
        renderDataQuality(quality);
        showToast("Dashboard refreshed from governed analytics");
    } catch (error) {
        console.error(error);
        setGlobalStatus("error", "Service unavailable");
        showToast(error.message || "Unable to refresh dashboard");
    } finally {
        refreshButton.classList.remove("spinning");
    }
}

function observeSections() {
    if (!("IntersectionObserver" in window)) {
        document.querySelectorAll(".reveal").forEach((item) => item.classList.add("visible"));
        return;
    }
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("visible");
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: .08 });
    document.querySelectorAll(".reveal").forEach((item) => observer.observe(item));
}

document.addEventListener("DOMContentLoaded", () => {
    observeSections();
    element("refresh-button").addEventListener("click", loadDashboard);
    element("trend-days").addEventListener("change", () => loadTrend().catch((error) => showToast(error.message)));
    element("trend-mode").addEventListener("change", () => loadTrend().catch((error) => showToast(error.message)));
    element("route-mode").addEventListener("change", () => loadRoutes().catch((error) => showToast(error.message)));
    element("route-sort").addEventListener("change", () => loadRoutes().catch((error) => showToast(error.message)));
    element("stop-search").addEventListener("input", () => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => loadStops().catch((error) => showToast(error.message)), 280);
    });
    loadDashboard();

    window.setInterval(() => {
        if (document.visibilityState === "visible") {
            loadDashboard();
        }
    }, AUTO_REFRESH_MS);
});

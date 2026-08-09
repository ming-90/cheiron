/** Shared client-side state for monitoring filters and live ECharts instances. */
const state = { runs: [], activeStatus: "", charts: [] };
const $ = (selector) => document.querySelector(selector);

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => {
      item.classList.toggle("active", item === tab);
      item.setAttribute("aria-selected", item === tab ? "true" : "false");
    });
    document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
    $(`#${tab.dataset.tab}`).classList.add("active");
    window.setTimeout(() => state.charts.forEach((chart) => chart.resize()), 0);
  });
});

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit"
  }).format(new Date(value));
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

/** Escape untrusted API or log text before interpolating it into HTML. */
function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function fieldLabel(field) {
  return ({ year: "연도", phase: "임상 단계", status: "상태", intervention: "중재",
    intervention_type: "중재 유형", sponsor: "스폰서", sponsor_class: "스폰서 분류",
    country: "국가", trial_count: "임상시험 수" })[field] || field;
}

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------

/** Refresh monitoring summaries without disturbing the currently selected tab. */
async function loadRuns() {
  const button = $("#refresh");
  button.classList.add("loading");
  try {
    const params = new URLSearchParams({ limit: "100" });
    if (state.activeStatus) params.set("status", state.activeStatus);
    const response = await fetch(`/v1/monitoring/runs?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.runs = payload.runs;
    renderStats(payload.stats);
    renderRuns(payload.runs);
    $("#last-updated").textContent = `Synced ${new Date().toLocaleTimeString("ko-KR")}`;
  } catch (error) {
    showToast(`로그를 불러오지 못했습니다: ${error.message}`);
  } finally {
    button.classList.remove("loading");
  }
}

function renderStats(stats) {
  $("#total-runs").textContent = stats.total_runs.toLocaleString();
  $("#success-rate").textContent = `${stats.success_rate}%`;
  $("#api-calls").textContent = stats.api_calls.toLocaleString();
  $("#avg-duration").textContent = formatDuration(stats.average_duration_ms);
  $("#success-meter").style.width = `${stats.success_rate}%`;
}

function renderRuns(runs) {
  const body = $("#runs-body");
  const empty = $("#empty-state");
  body.innerHTML = "";
  empty.hidden = runs.length > 0;
  if (!runs.length) return;
  body.innerHTML = runs.map((run) => `
    <tr data-id="${escapeHtml(run.request_id)}" tabindex="0">
      <td><span class="status-chip ${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></td>
      <td class="query-cell" title="${escapeHtml(run.query)}">${escapeHtml(run.query)}</td>
      <td class="param-cell"><div class="param-list">${renderParamPills(run.request_params)}</div></td>
      <td class="mono">${formatTime(run.started_at)}</td>
      <td>${run.api_call_count}</td>
      <td>${Number(run.records_used || 0).toLocaleString()} <span class="mono">/ ${Number(run.records_retrieved || 0).toLocaleString()}</span></td>
      <td class="mono">${formatDuration(run.duration_ms)}</td>
      <td><button type="button" class="result-button" data-result-id="${escapeHtml(run.request_id)}">View result</button></td>
    </tr>`).join("");
  body.querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (!event.target.closest("[data-result-id]")) openRun(row.dataset.id);
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") openRun(row.dataset.id);
    });
  });
  body.querySelectorAll("[data-result-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      showRunResult(button.dataset.resultId);
    });
  });
}

/** Load a saved backend response and render it in the User App tab. */
async function showRunResult(requestId) {
  const button = document.querySelector(`[data-result-id="${CSS.escape(requestId)}"]`);
  if (button) button.disabled = true;
  try {
    const response = await fetch(`/v1/monitoring/runs/${encodeURIComponent(requestId)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const run = await response.json();
    if (!run.response_output) {
      showToast("이전 형식의 로그에는 다시 표시할 결과 JSON이 없습니다.");
      return;
    }
    document.querySelector('[data-tab="user-app"]').click();
    renderQueryResult(run.response_output);
  } catch (error) {
    showToast(`결과를 불러오지 못했습니다: ${error.message}`);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderParamPills(params = {}) {
  const hidden = new Set(["format", "fields", "pageSize", "countTotal", "pageToken"]);
  const entries = Object.entries(params).filter(([key]) => !hidden.has(key));
  if (!entries.length) return '<span class="mono">No query params</span>';
  return entries.map(([key, value]) => `<span class="param-pill" title="${escapeHtml(`${key}=${value}`)}"><b>${escapeHtml(key)}</b>=${escapeHtml(value)}</span>`).join("");
}

async function openRun(requestId) {
  openDrawer(`<div class="empty-state"><span class="empty-glyph">⌁</span><p>실행 기록을 불러오는 중...</p></div>`);
  try {
    const response = await fetch(`/v1/monitoring/runs/${encodeURIComponent(requestId)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderRunDetail(await response.json());
  } catch (error) {
    $("#drawer-content").innerHTML = `<div class="empty-state"><h3>불러오기 실패</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function renderRunDetail(run) {
  const calls = run.api_calls || [];
  const request = run.user_request || {};
  const result = run.result_summary || {};
  $("#drawer-title").textContent = run.status === "success" ? "Successful run" : "Failed run";
  $("#drawer-content").innerHTML = `
    <section class="detail-section">
      <div class="detail-grid">
        <div class="detail-stat"><span>Request ID</span><strong class="mono">${escapeHtml(run.request_id?.slice(0, 12))}…</strong></div>
        <div class="detail-stat"><span>Status</span><strong>${escapeHtml(run.status)}</strong></div>
        <div class="detail-stat"><span>Records used</span><strong>${Number(result.records_used || 0).toLocaleString()}</strong></div>
        <div class="detail-stat"><span>API calls</span><strong>${calls.length}</strong></div>
      </div>
    </section>
    <section class="detail-section"><h3>User question</h3><div class="detail-card">${escapeHtml(request.query || "")}</div></section>
    <section class="detail-section"><h3>Structured request</h3><pre>${escapeHtml(JSON.stringify(request, null, 2))}</pre></section>
    <section class="detail-section"><h3>Validated analysis plan</h3><pre>${escapeHtml(JSON.stringify(run.analysis_plan, null, 2))}</pre></section>
    <section class="detail-section"><h3>Outgoing API requests · ${calls.length}</h3>${calls.map(renderApiCall).join("") || '<div class="detail-card">기록된 외부 API 호출이 없습니다.</div>'}</section>
    <section class="detail-section"><h3>Pipeline events</h3><pre>${escapeHtml(JSON.stringify(run.pipeline_events, null, 2))}</pre></section>
    ${run.error ? `<section class="detail-section"><h3>Error</h3><pre>${escapeHtml(JSON.stringify(run.error, null, 2))}</pre></section>` : ""}`;
}

/** Render one audited external request, including its exact replay parameters. */
function renderApiCall(call) {
  const request = call.request || { url: call.url, params: call.params || {}, param_list: Object.entries(call.params || {}).map(([name, value]) => ({ name, value })) };
  const params = request.param_list || Object.entries(request.params || {}).map(([name, value]) => ({ name, value }));
  const curl = request.replay_curl || `curl -fsS '${request.url || ""}'`;
  return `<article class="detail-card request-card">
    <div class="api-head"><span><b class="method">${escapeHtml(call.method)}</b> <span class="api-path">${escapeHtml(call.path)}</span></span><span class="mono">attempt ${call.attempt || 1} · ${call.status_code || "ERR"} · ${formatDuration(call.duration_ms)}</span></div>
    <div class="request-url">${escapeHtml(request.url || call.url || "")}</div>
    <div class="request-toolbar"><span class="mono">${params.length} query parameters</span><button class="copy-button" data-copy="${escapeHtml(curl)}">Copy cURL</button></div>
    <div class="params-table">${params.map((param) => `<div class="param-row"><span>${escapeHtml(param.name)}</span><span>${escapeHtml(typeof param.value === "object" ? JSON.stringify(param.value) : param.value)}</span></div>`).join("") || '<div class="param-row"><span>—</span><span>No parameters</span></div>'}</div>
    <details style="margin-top:12px"><summary class="mono">View response summary</summary><pre style="margin-top:10px">${escapeHtml(JSON.stringify({ response: call.response, error: call.error }, null, 2))}</pre></details>
  </article>`;
}

function openDrawer(content) {
  $("#drawer-content").innerHTML = content;
  $("#drawer-backdrop").hidden = false;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
}

$("#drawer-content").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    showToast("cURL 요청을 복사했습니다.");
  } catch (_) {
    showToast("클립보드에 복사하지 못했습니다.");
  }
});

function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#drawer-backdrop").hidden = true;
  document.body.style.overflow = "";
}

let toastTimer;
function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}

$("#refresh").addEventListener("click", loadRuns);
$("#status-filter").addEventListener("change", (event) => {
  state.activeStatus = event.target.value;
  loadRuns();
});
$("#close-drawer").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDrawer(); });

// ---------------------------------------------------------------------------
// Query execution and result rendering
// ---------------------------------------------------------------------------

/** Submit a natural-language query and manage the user-visible request lifecycle. */
async function submitQuery(event) {
  event.preventDefault();
  const query = $("#query-input").value.trim();
  if (query.length < 3) return;
  const button = $("#ask-button");
  const status = $("#query-status");
  button.disabled = true;
  button.classList.add("loading");
  status.hidden = false;
  status.className = "query-status loading";
  status.innerHTML = '<span class="status-spinner"></span><div><strong>임상시험 데이터를 분석하고 있습니다.</strong><small>검색·집계·차트 설계를 순서대로 수행합니다.</small></div>';
  $("#query-results").hidden = true;
  try {
    const response = await fetch("/v1/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, include_citations: $("#include-citations").checked })
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `HTTP ${response.status}`);
    renderQueryResult(payload);
    status.hidden = true;
    loadRuns();
  } catch (error) {
    status.className = "query-status error";
    status.innerHTML = `<div><strong>분석하지 못했습니다.</strong><small>${escapeHtml(error.message)}</small></div>`;
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
  }
}

/** Render a complete response; reveal containers before ECharts measures them. */
function renderQueryResult(payload) {
  const results = $("#query-results");
  $("#result-title").textContent = payload.query;
  const meta = payload.meta || {};
  $("#result-meta").innerHTML = `<span>${Number(meta.records_used || 0).toLocaleString()} studies</span><span>${payload.visualizations.length} charts</span><span>${escapeHtml(meta.data_timestamp || "latest data")}</span>`;
  $("#visualizations").innerHTML = payload.visualizations.map(renderVisualization).join("");
  $("#result-json").textContent = JSON.stringify(payload, null, 2);
  results.hidden = false;
  // ECharts must measure a visible container. Initializing while `hidden`
  // makes it fall back to a 100px canvas and clips the graph to the left.
  window.requestAnimationFrame(() => mountVisualizations(payload.visualizations));
  results.scrollIntoView({ behavior: "smooth", block: "start" });
  if (!Number(meta.records_used || 0)) {
    showToast("검색 결과가 없습니다. 질문 또는 검색 조건을 확인해 주세요.");
  }
}

/** Create the chart card shell and its provenance controls. */
function renderVisualization(visualization) {
  const source = visualization.metadata?.design_source || "unknown";
  const citations = collectCitations(visualization.data);
  const chartId = `chart-${String(visualization.id).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  return `<article class="visualization-card ${visualization.type === "network_graph" ? "network-card" : ""}">
    <header><div><span class="chart-type">${escapeHtml(visualization.type)}</span><h3>${escapeHtml(visualization.title)}</h3></div><span class="design-chip">${source === "llm" ? "AI selected" : "Rule selected"}</span></header>
    <div class="chart-surface"><div id="${chartId}" class="echarts-chart" role="img" aria-label="${escapeHtml(visualization.title)}"></div></div>
    ${citations.length ? `<details class="chart-citations"><summary>원본 연구 ${citations.length}개 보기</summary><div>${citations.slice(0, 30).map((item) => `<button type="button" data-study-id="${escapeHtml(item.nct_id)}"><b>${escapeHtml(item.nct_id)}</b><span>${escapeHtml(item.title || item.value || "연구 상세")}</span></button>`).join("")}</div></details>` : ""}
  </article>`;
}

/** Dispose stale charts and mount one ECharts instance per backend specification. */
function mountVisualizations(visualizations) {
  state.charts.forEach((chart) => chart.dispose());
  state.charts = [];
  if (!window.echarts) {
    document.querySelectorAll(".echarts-chart").forEach((element) => {
      element.innerHTML = '<div class="no-chart-data">차트 라이브러리를 불러오지 못했습니다.</div>';
    });
    return;
  }
  visualizations.forEach((visualization) => {
    const chartId = `chart-${String(visualization.id).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
    const element = document.getElementById(chartId);
    if (!element) return;
    const chart = window.echarts.init(element, null, { renderer: "canvas" });
    chart.setOption(toEChartsOption(visualization), { notMerge: true });
    chart.on("click", (params) => {
      const citation = params.data?.citations?.[0] || params.data?.raw?.citations?.[0];
      if (citation?.nct_id) openStudyDetail(citation.nct_id);
    });
    state.charts.push(chart);
  });
}

/** Dispatch the renderer-independent backend contract to an ECharts adapter. */
function toEChartsOption(visualization) {
  if (visualization.type === "network_graph") return networkOption(visualization);
  const rows = visualization.data || [];
  if (!rows.length) return {
    title: { text: "조건에 맞는 데이터가 없습니다.", left: "center", top: "middle", textStyle: { color: "#6b7770", fontSize: 12, fontWeight: 400 } }
  };
  if (visualization.type === "time_series") return timeSeriesOption(visualization);
  return barOption(visualization);
}

function baseChartOption() {
  return {
    animationDuration: 500,
    color: ["#1d6b50", "#84a85e", "#d1a24c", "#557f94", "#9a6d83", "#6e806f"],
    textStyle: { fontFamily: "Manrope, sans-serif", color: "#17221d" },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "#17221d",
      borderWidth: 0,
      textStyle: { color: "#fff", fontSize: 11 },
      extraCssText: "border-radius:8px;box-shadow:0 8px 30px rgba(0,0,0,.16)"
    },
    grid: { left: 58, right: 26, top: 36, bottom: 55, containLabel: true }
  };
}

// ECharts adapters intentionally consume only `type`, `encoding`, and `data`.
// Keeping this translation in the frontend prevents renderer-specific options
// from leaking into the backend response contract.

/** Translate tabular bar/grouped-bar data and encoding into ECharts options. */
function barOption(visualization) {
  const rows = visualization.data || [];
  const encoding = visualization.encoding || {};
  const horizontal = visualization.type === "horizontal_bar_chart";
  const categoryField = horizontal ? encoding.y?.field : encoding.x?.field;
  const countField = horizontal ? encoding.x?.field : encoding.y?.field;
  const seriesField = encoding.series?.field || encoding.color?.field;
  const option = baseChartOption();
  const categories = [...new Set(rows.map((row) => String(row[categoryField] ?? "—")))];
  const seriesNames = seriesField ? [...new Set(rows.map((row) => String(row[seriesField] ?? "—")))] : [fieldLabel(countField)];
  const lookup = new Map(rows.map((row) => [`${row[seriesField] ?? ""}\u0000${row[categoryField] ?? "—"}`, row]));
  option.tooltip.trigger = "axis";
  option.tooltip.axisPointer = { type: "shadow" };
  option.legend = seriesField ? { top: 0, type: "scroll", textStyle: { fontSize: 10 } } : undefined;
  option.xAxis = horizontal
    ? { type: "value", name: fieldLabel(countField), splitLine: { lineStyle: { color: "#e8e8e1" } } }
    : { type: "category", data: categories, name: fieldLabel(categoryField), axisLabel: { rotate: categories.length > 8 ? 35 : 0 } };
  option.yAxis = horizontal
    ? { type: "category", data: categories, name: fieldLabel(categoryField), inverse: true, axisLabel: { width: 130, overflow: "truncate" } }
    : { type: "value", name: fieldLabel(countField), splitLine: { lineStyle: { color: "#e8e8e1" } } };
  option.series = seriesNames.map((seriesName) => ({
    name: seriesName,
    type: "bar",
    barMaxWidth: 42,
    emphasis: { focus: "series" },
    itemStyle: { borderRadius: horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0] },
    data: categories.map((category) => {
      const row = lookup.get(`${seriesField ? seriesName : ""}\u0000${category}`);
      return { value: Number(row?.[countField] || 0), raw: row, citations: row?.citations || [] };
    })
  }));
  return option;
}

/** Translate temporal aggregates into one or more ECharts line series. */
function timeSeriesOption(visualization) {
  const rows = visualization.data || [];
  const encoding = visualization.encoding || {};
  const xField = encoding.x?.field || "year";
  const yField = encoding.y?.field || "trial_count";
  const seriesField = encoding.series?.field || encoding.color?.field;
  const years = [...new Set(rows.map((row) => row[xField]))].sort((a, b) => Number(a) - Number(b));
  const seriesNames = seriesField ? [...new Set(rows.map((row) => String(row[seriesField] ?? "—")))] : [fieldLabel(yField)];
  const lookup = new Map(rows.map((row) => [`${row[seriesField] ?? ""}\u0000${row[xField]}`, row]));
  const option = baseChartOption();
  option.tooltip.trigger = "axis";
  option.legend = seriesField ? { top: 0, type: "scroll", textStyle: { fontSize: 10 } } : undefined;
  option.xAxis = { type: "category", data: years, boundaryGap: false, name: fieldLabel(xField) };
  option.yAxis = { type: "value", name: fieldLabel(yField), splitLine: { lineStyle: { color: "#e8e8e1" } } };
  option.dataZoom = years.length > 15 ? [{ type: "inside" }, { type: "slider", height: 18 }] : [];
  option.series = seriesNames.map((seriesName) => ({
    name: seriesName,
    type: "line",
    smooth: true,
    symbolSize: 8,
    emphasis: { focus: "series" },
    areaStyle: seriesNames.length === 1 ? { opacity: .08 } : undefined,
    data: years.map((year) => {
      const row = lookup.get(`${seriesField ? seriesName : ""}\u0000${year}`);
      return { value: Number(row?.[yField] || 0), raw: row, citations: row?.citations || [] };
    })
  }));
  return option;
}

/** Keep dense networks readable while preserving the complete backend JSON. */
function readableNetwork(graph, maxNodes = 50, maxEdges = 90) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  if (nodes.length <= maxNodes && edges.length <= maxEdges) {
    return { nodes, edges, truncated: false };
  }
  const scores = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((edge) => {
    const weight = Number(edge.weight || 1);
    scores.set(edge.source, (scores.get(edge.source) || 0) + weight);
    scores.set(edge.target, (scores.get(edge.target) || 0) + weight);
  });
  const groups = [...new Set(nodes.map((node) => node.group))];
  const selected = new Set();
  groups.forEach((group) => {
    const groupNodes = nodes
      .filter((node) => node.group === group)
      .sort((a, b) => (scores.get(b.id) || 0) - (scores.get(a.id) || 0));
    const quota = Math.max(1, Math.floor(maxNodes / groups.length));
    groupNodes.slice(0, quota).forEach((node) => selected.add(node.id));
  });
  const visibleEdges = edges
    .filter((edge) => selected.has(edge.source) && selected.has(edge.target))
    .sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0))
    .slice(0, maxEdges);
  const connected = new Set(visibleEdges.flatMap((edge) => [edge.source, edge.target]));
  return {
    nodes: nodes.filter((node) => connected.has(node.id)),
    edges: visibleEdges,
    truncated: true
  };
}

/** Detect sponsor–intervention style networks that benefit from two columns. */
function isBipartiteNetwork(nodes, edges) {
  const groupById = new Map(nodes.map((node) => [node.id, node.group]));
  const groups = [...new Set(nodes.map((node) => node.group))];
  return groups.length === 2 && edges.every((edge) => groupById.get(edge.source) !== groupById.get(edge.target));
}

/** Position two entity groups in opposing columns instead of a circular ring. */
function bipartiteNodes(nodes) {
  const groups = [...new Set(nodes.map((node) => node.group))];
  const byGroup = new Map(groups.map((group) => [
    group,
    nodes
      .filter((node) => node.group === group)
      .sort((a, b) => Number(b.trial_count || 0) - Number(a.trial_count || 0))
  ]));
  return nodes.map((node) => {
    const groupIndex = groups.indexOf(node.group);
    const siblings = byGroup.get(node.group) || [];
    const row = siblings.findIndex((item) => item.id === node.id);
    return {
      ...node,
      x: groupIndex === 0 ? 80 : 920,
      y: 40 + ((row + 1) / (siblings.length + 1)) * 920,
      label: {
        show: row < 10,
        position: groupIndex === 0 ? "left" : "right",
        align: groupIndex === 0 ? "right" : "left"
      }
    };
  });
}

/** Translate backend nodes and edges into an interactive ECharts graph. */
function networkOption(visualization) {
  const original = visualization.data?.[0] || { nodes: [], edges: [] };
  const graph = readableNetwork(original);
  const bipartite = isBipartiteNetwork(graph.nodes, graph.edges);
  const displayNodes = bipartite ? bipartiteNodes(graph.nodes) : graph.nodes;
  const showAllLabels = displayNodes.length <= 26;
  const option = baseChartOption();
  option.tooltip.formatter = (params) => params.dataType === "edge"
    ? `${escapeHtml(params.data.source)} ↔ ${escapeHtml(params.data.target)}<br><b>${Number(params.data.value || 0).toLocaleString()} studies</b>`
    : `${escapeHtml(params.data.name)}<br><b>${Number(params.data.value || 0).toLocaleString()} studies</b>`;
  option.legend = [{ data: [...new Set(displayNodes.map((node) => node.group))], bottom: 0 }];
  if (graph.truncated) {
    option.graphic = [{
      type: "text", right: 12, top: 8,
      style: {
        text: `가독성을 위해 주요 관계 ${graph.edges.length}개 표시 · 전체 데이터는 JSON에 유지`,
        fill: "#6b7770", font: "10px Manrope, sans-serif"
      }
    }];
  }
  option.series = [{
    type: "graph",
    layout: bipartite ? "none" : "force",
    left: bipartite ? 170 : 85,
    right: bipartite ? 170 : 85,
    top: 45,
    bottom: 70,
    roam: true,
    draggable: true,
    force: bipartite ? undefined : {
      initLayout: "none", repulsion: [180, 520], edgeLength: [75, 190], gravity: .08, friction: .62
    },
    label: {
      show: showAllLabels, position: "right", distance: 6, formatter: "{b}", fontSize: 9,
      width: 120, overflow: "truncate", color: "#435249"
    },
    labelLayout: { hideOverlap: true },
    emphasis: {
      focus: "adjacency",
      label: { show: true, fontSize: 11, fontWeight: 600 },
      lineStyle: { width: 5, opacity: .8 }
    },
    categories: [...new Set(displayNodes.map((node) => node.group))].map((name) => ({ name })),
    data: displayNodes.map((node) => ({
      id: node.id, name: node.id, value: node.trial_count,
      symbolSize: Math.min(28, 9 + Math.sqrt(Number(node.trial_count || 1)) * 2),
      category: node.group, x: node.x, y: node.y, label: node.label
    })),
    links: graph.edges.map((edge) => ({
      source: edge.source, target: edge.target, value: edge.weight,
      citations: edge.citations || [], lineStyle: {
        width: Math.min(8, 1 + Math.sqrt(Number(edge.weight || 1))),
        opacity: .3, curveness: bipartite ? .06 : .12
      }
    }))
  }];
  return option;
}

/** Collect unique NCT references nested anywhere in visualization data. */
function collectCitations(data) {
  const found = new Map();
  const visit = (value) => {
    if (Array.isArray(value)) value.forEach(visit);
    else if (value && typeof value === "object") {
      (value.citations || []).forEach((item) => { if (item.nct_id) found.set(item.nct_id, item); });
      Object.values(value).forEach(visit);
    }
  };
  visit(data);
  return [...found.values()];
}

/** Fetch and display the full record for a citation selected by the user. */
async function openStudyDetail(nctId) {
  openDrawer('<div class="empty-state"><span class="empty-glyph">⌁</span><p>연구 상세 정보를 불러오는 중...</p></div>');
  $("#drawer-title").textContent = nctId;
  try {
    const response = await fetch(`/v1/studies/${encodeURIComponent(nctId)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    const identification = payload.protocolSection?.identificationModule || {};
    const status = payload.protocolSection?.statusModule || {};
    $("#drawer-content").innerHTML = `<section class="detail-section"><h3>Study overview</h3><div class="detail-card study-overview"><b>${escapeHtml(identification.briefTitle || nctId)}</b><span>${escapeHtml(status.overallStatus || "상태 정보 없음")}</span><a href="https://clinicaltrials.gov/study/${escapeHtml(nctId)}" target="_blank" rel="noreferrer">ClinicalTrials.gov에서 보기 ↗</a></div></section><section class="detail-section"><h3>Full API response</h3><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre></section>`;
  } catch (error) {
    $("#drawer-content").innerHTML = `<div class="empty-state"><h3>상세 조회 실패</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}

$("#query-form").addEventListener("submit", submitQuery);
document.querySelectorAll(".example-queries button").forEach((button) => button.addEventListener("click", () => {
  $("#query-input").value = button.textContent.trim();
  $("#query-input").focus();
}));
$("#visualizations").addEventListener("click", (event) => {
  const button = event.target.closest("[data-study-id]");
  if (button) openStudyDetail(button.dataset.studyId);
});
window.addEventListener("resize", () => state.charts.forEach((chart) => chart.resize()));

loadRuns();
setInterval(loadRuns, 30000);

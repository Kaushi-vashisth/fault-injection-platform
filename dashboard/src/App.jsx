import { useState, useEffect } from "react"
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  LineChart, Line, RadarChart, Radar, PolarGrid,
  PolarAngleAxis, ResponsiveContainer, PieChart, Pie, Cell
} from "recharts"

const COLORS = {
  cpu:     "#ef4444",
  memory:  "#f97316",
  network: "#3b82f6",
  crash:   "#8b5cf6",
  default: "#6b7280"
}

const SERVICE_COLORS = {
  service_a: "#3b82f6",
  service_b: "#ef4444",
  service_c: "#10b981"
}

export default function App() {
  const [data, setData] = useState(null)
  const [selectedRun, setSelectedRun] = useState(null)
  const [activeTab, setActiveTab] = useState("overview")
  const [liveData, setLiveData] = useState(null)

  useEffect(() => {
    fetch("./data.json")
      .then(r => r.json())
      .then(d => {
        setData(d)
        if (d.scores?.length > 0) setSelectedRun(d.scores[0].run_id)
      })
  }, [])

  useEffect(() => {
    const fetchLive = () => {
      fetch("http://localhost:5000/api/live/status")
       .then(r => r.json())
       .then(d => setLiveData(d))
       .catch(() => setLiveData(null))
    }
    fetchLive()
    const interval = setInterval(fetchLive, 5000)
    return () => clearInterval(interval)
  }, [])

  if (!data) return (
    <div style={styles.loading}>Loading dashboard data...</div>
  )

  const selectedScore = data.scores?.find(s => s.run_id === selectedRun)
  const selectedFault = data.faults?.find(f => f.run_id === selectedRun)
  const selectedDeg   = data.degradations?.find(d => d.run_id === selectedRun)
  const selectedProp  = data.propagations?.find(p => p.run_id === selectedRun)

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <h1 style={styles.title}>
          Fault Injection & Resilience Analytics Platform
        </h1>
        <p style={styles.subtitle}>
          Distributed Systems Fault Analysis Dashboard
        </p>
      </div>
      

      {/* Summary Cards */}
      <div style={styles.cardRow}>
        <SummaryCard
          label="Total Experiments"
          value={data.summary?.total_experiments}
          color="#3b82f6"
        />
        <SummaryCard
          label="Total Faults Injected"
          value={data.summary?.total_faults}
          color="#ef4444"
        />
        <SummaryCard
          label="Avg Resilience Score"
          value={data.summary?.avg_resilience_score}
          color="#10b981"
        />
        <SummaryCard
          label="Fault Types Tested"
          value={Object.keys(data.summary?.fault_type_distribution || {}).length}
          color="#8b5cf6"
        />
      </div>

      {/* Tabs */}
      <div style={styles.tabs}>
        {["overview", "resilience", "ml", "propagation","live"].map(tab => (
          <button
            key={tab}
            style={{
              ...styles.tab,
              ...(activeTab === tab ? styles.tabActive : {})
            }}
            onClick={() => setActiveTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "overview" && (
        <OverviewTab data={data} />
      )}
      {activeTab === "resilience" && (
        <ResilienceTab
          data={data}
          selectedRun={selectedRun}
          setSelectedRun={setSelectedRun}
          selectedScore={selectedScore}
          selectedFault={selectedFault}
          selectedDeg={selectedDeg}
        />
      )}
      {activeTab === "ml" && (
        <MLTab data={data} />
      )}
      {activeTab === "propagation" && (
        <PropagationTab
          data={data}
          selectedRun={selectedRun}
          setSelectedRun={setSelectedRun}
          selectedProp={selectedProp}
          selectedFault={selectedFault}
        />
      )}
      {activeTab === "live" && (
        <LiveTab liveData={liveData} />
      )}
    </div>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────
function OverviewTab({ data }) {
  const faultDist = Object.entries(
    data.summary?.fault_type_distribution || {}
  ).map(([name, value]) => ({ name, value }))

  const scoreTimeline = [...(data.scores || [])]
    .reverse()
    .map((s, i) => ({
      index: i + 1,
      score: s.final_resilience_score,
      experiment: s.experiment_id
    }))

  return (
    <div style={styles.tabContent}>
      <div style={styles.chartRow}>
        <ChartCard title="Fault Type Distribution">
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={faultDist}
                dataKey="value"
                nameKey="name"
                cx="50%" cy="50%"
                outerRadius={90}
                label={({name, value}) => `${name}: ${value}`}
              >
                {faultDist.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={COLORS[entry.name] || COLORS.default}
                  />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Resilience Score Timeline">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={scoreTimeline}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="index" stroke="#9ca3af"
                label={{value: "Run #", position: "insideBottom", offset: -5}} />
              <YAxis domain={[0, 1]} stroke="#9ca3af" />
              <Tooltip
                formatter={(v) => [v, "Resilience Score"]}
                labelFormatter={(l) => `Run ${l}`}
              />
              <Line
                type="monotone" dataKey="score"
                stroke="#10b981" strokeWidth={2}
                dot={{ fill: "#10b981", r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}

// ── Resilience Tab ────────────────────────────────────────────────
function ResilienceTab({
  data, selectedRun, setSelectedRun,
  selectedScore, selectedFault, selectedDeg
}) {
  const componentData = selectedScore
    ? Object.entries(selectedScore.component_scores || {}).map(
        ([service, score]) => ({ service, score })
      )
    : []

  const degradationData = selectedDeg
    ? ["service_a", "service_b", "service_c"].map(s => ({
        service: s,
        latency_increase: selectedDeg.latency_degradation?.[s]
          ?.latency_increase_pct || 0,
        throughput_drop: selectedDeg.throughput_drop?.[s]
          ?.throughput_drop_pct || 0
      }))
    : []

  return (
    <div style={styles.tabContent}>
      {/* Run Selector */}
      <div style={styles.selector}>
        <label style={styles.label}>Select Run: </label>
        <select
          style={styles.select}
          value={selectedRun || ""}
          onChange={e => setSelectedRun(e.target.value)}
        >
          {data.scores?.map(s => (
            <option key={s.run_id} value={s.run_id}>
              {s.experiment_id} — Score: {s.final_resilience_score}
            </option>
          ))}
        </select>
      </div>

      {selectedScore && (
        <>
          {/* Score Badge */}
          <div style={styles.scoreBadge}>
            <div style={styles.scoreValue}>
              {selectedScore.final_resilience_score}
            </div>
            <div style={styles.scoreLabel}>
              {selectedScore.score_interpretation}
            </div>
            {selectedFault && (
              <div style={{
                ...styles.faultBadge,
                background: COLORS[selectedFault.fault_type] || "#6b7280"
              }}>
                {selectedFault.fault_type?.toUpperCase()} FAULT
              </div>
            )}
          </div>

          <div style={styles.chartRow}>
            <ChartCard title="Component Resilience Scores">
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={componentData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="service" stroke="#9ca3af" />
                  <YAxis domain={[0, 1]} stroke="#9ca3af" />
                  <Tooltip />
                  <Bar dataKey="score" radius={[4, 4, 0, 0]}>
                    {componentData.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={SERVICE_COLORS[entry.service] || "#6b7280"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>

            <ChartCard title="Degradation Analysis">
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={degradationData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                  <XAxis dataKey="service" stroke="#9ca3af" />
                  <YAxis stroke="#9ca3af" />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="latency_increase"
                    name="Latency Increase %"
                    fill="#ef4444" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="throughput_drop"
                    name="Throughput Drop %"
                    fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
          </div>
        </>
      )}
    </div>
  )
}

// ── ML Tab ────────────────────────────────────────────────────────
function MLTab({ data }) {
  const ml = data.ml
  if (!ml) return (
    <div style={styles.tabContent}>
      <p style={{ color: "#9ca3af" }}>
        No ML results found. Run python -m analytics.ml.classifier first.
      </p>
    </div>
  )

  const labelDist = Object.entries(ml.label_distribution || {}).map(
    ([name, value]) => ({ name, value })
  )

  const cvScores = (ml.results?.cv_scores || []).map((s, i) => ({
    fold: `Fold ${i + 1}`, accuracy: round(s, 3)
  }))

  return (
    <div style={styles.tabContent}>
      {/* ML Summary */}
      <div style={styles.cardRow}>
        <SummaryCard
          label="Model Type"
          value={ml.model_type}
          color="#8b5cf6"
        />
        <SummaryCard
          label="CV Accuracy"
          value={ml.results?.accuracy}
          color="#10b981"
        />
        <SummaryCard
          label="Training Samples"
          value={ml.results?.training_samples}
          color="#3b82f6"
        />
        <SummaryCard
          label="Features Used"
          value={ml.results?.feature_count}
          color="#f97316"
        />
      </div>

      <div style={styles.chartRow}>
        <ChartCard title="Training Data Distribution">
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={labelDist}
                dataKey="value"
                nameKey="name"
                cx="50%" cy="50%"
                outerRadius={90}
                label={({name, value}) => `${name}: ${value}`}
              >
                {labelDist.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={COLORS[entry.name] || COLORS.default}
                  />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Cross-Validation Scores">
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={cvScores}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="fold" stroke="#9ca3af" />
              <YAxis domain={[0, 1]} stroke="#9ca3af" />
              <Tooltip />
              <Bar dataKey="accuracy" fill="#8b5cf6"
                radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}

// ── Propagation Tab ───────────────────────────────────────────────
function PropagationTab({
  data, selectedRun, setSelectedRun,
  selectedProp, selectedFault
}) {
  const nodes = selectedProp?.propagation_graph?.nodes || []
  const blastRadius = selectedProp?.blast_radius

  return (
    <div style={styles.tabContent}>
      <div style={styles.selector}>
        <label style={styles.label}>Select Run: </label>
        <select
          style={styles.select}
          value={selectedRun || ""}
          onChange={e => setSelectedRun(e.target.value)}
        >
          {data.propagations?.map(p => (
            <option key={p.run_id} value={p.run_id}>
              {p.experiment_id} — {p.run_id?.slice(0, 8)}...
            </option>
          ))}
        </select>
      </div>

      {selectedProp && (
        <>
          {/* Blast Radius */}
          {blastRadius && (
            <div style={styles.blastCard}>
              <span style={styles.blastLabel}>Blast Radius:</span>
              <span style={styles.blastValue}>
                {blastRadius.blast_radius_pct}%
              </span>
              <span style={{ color: "#9ca3af", marginLeft: 16 }}>
                {blastRadius.affected_count} of{" "}
                {blastRadius.total_services} services affected
              </span>
            </div>
          )}

          {/* Service Nodes */}
          <div style={styles.propagationGrid}>
            {nodes.map(node => (
              <div
                key={node.id}
                style={{
                  ...styles.serviceNode,
                  borderColor: node.is_fault_origin
                    ? "#ef4444"
                    : node.affected
                    ? "#f97316"
                    : "#10b981",
                  background: node.is_fault_origin
                    ? "#450a0a"
                    : node.affected
                    ? "#431407"
                    : "#052e16"
                }}
              >
                <div style={styles.nodeName}>{node.id}</div>
                <div style={styles.nodeStatus}>
                  {node.is_fault_origin
                    ? "🔴 Fault Origin"
                    : node.affected
                    ? "🟠 Affected"
                    : "🟢 Healthy"}
                </div>
                {node.propagation_lag_sec !== null && (
                  <div style={styles.nodeLag}>
                    Lag: {node.propagation_lag_sec}s
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Dependency Arrow */}
          <div style={styles.dependencyNote}>
            Service A → Service B → Service C (dependency chain)
          </div>
        </>
      )}
    </div>
  )
}

// ── Reusable Components ───────────────────────────────────────────
function LiveTab({ liveData }) {
  const LEVEL_COLORS = {
    CRITICAL: "#ef4444",
    WARNING:  "#f97316",
    INFO:     "#3b82f6"
  }

  if (!liveData) return (
    <div style={styles.tabContent}>
      <div style={{
        background: "#1e293b", borderRadius: 8,
        padding: 24, textAlign: "center"
      }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>⚡</div>
        <div style={{ color: "#94a3b8", fontSize: 16 }}>
          Flask API not running
        </div>
        <div style={{ color: "#475569", fontSize: 13, marginTop: 8 }}>
          Run: python dashboard/api_server.py
        </div>
      </div>
    </div>
  )

  const { running_experiment, recent_metrics, active_alerts } = liveData

  // Group metrics by service
  const metricsByService = {}
  for (const m of (recent_metrics || [])) {
    if (!metricsByService[m.service]) {
      metricsByService[m.service] = m
    }
  }

  return (
    <div style={styles.tabContent}>
      {/* Live Status Banner */}
      <div style={{
        background: running_experiment ? "#052e16" : "#1e293b",
        border: `1px solid ${running_experiment ? "#16a34a" : "#334155"}`,
        borderRadius: 8, padding: "12px 20px",
        marginBottom: 20, display: "flex",
        alignItems: "center", gap: 12
      }}>
        <div style={{
          width: 10, height: 10, borderRadius: "50%",
          background: running_experiment ? "#16a34a" : "#475569",
          boxShadow: running_experiment
            ? "0 0 8px #16a34a" : "none"
        }} />
        <div>
          {running_experiment
            ? `Experiment running: ${running_experiment.experiment_id}`
            : "No experiment running"}
        </div>
        <div style={{
          marginLeft: "auto", color: "#475569", fontSize: 12
        }}>
          Auto-refreshes every 5s
        </div>
      </div>

      {/* Live Metrics */}
      <h3 style={{ color: "#94a3b8", marginBottom: 12, fontSize: 14 }}>
        Latest Metrics
      </h3>
      <div style={styles.propagationGrid}>
        {["service_a", "service_b", "service_c"].map(service => {
          const m = metricsByService[service]?.metrics || {}
          return (
            <div key={service} style={{
              ...styles.serviceNode,
              borderColor: "#334155",
              background: "#1e293b"
            }}>
              <div style={styles.nodeName}>{service}</div>
              <div style={{
                fontSize: 12, color: "#94a3b8", marginTop: 8
              }}>
                <div>Latency p50: {m.latency_p50_ms
                  ? `${m.latency_p50_ms}ms` : "—"}</div>
                <div>RPS: {m.request_rate_rps
                  ? m.request_rate_rps : "—"}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Active Alerts */}
      <h3 style={{
        color: "#94a3b8", marginBottom: 12,
        fontSize: 14, marginTop: 24
      }}>
        Active Alerts {active_alerts?.length > 0
          ? `(${active_alerts.length})` : ""}
      </h3>

      {(!active_alerts || active_alerts.length === 0) ? (
        <div style={{
          background: "#052e16", borderRadius: 8,
          padding: 16, color: "#16a34a", fontSize: 14
        }}>
          ✅ No active alerts — system healthy
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {active_alerts.map((alert, i) => (
            <div key={i} style={{
              background: "#1e293b", borderRadius: 8,
              padding: "12px 16px",
              borderLeft: `4px solid ${
                LEVEL_COLORS[alert.level] || "#6b7280"
              }`
            }}>
              <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
                <span style={{
                  color: LEVEL_COLORS[alert.level],
                  fontSize: 12, fontWeight: 700
                }}>
                  {alert.level}
                </span>
                <span style={{ color: "#64748b", fontSize: 12 }}>
                  {new Date(alert.timestamp * 1000)
                    .toLocaleTimeString()}
                </span>
              </div>
              <div style={{ fontSize: 14, color: "#e2e8f0" }}>
                {alert.message}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
function SummaryCard({ label, value, color }) {
  return (
    <div style={{ ...styles.card, borderTop: `3px solid ${color}` }}>
      <div style={{ ...styles.cardValue, color }}>{value ?? "—"}</div>
      <div style={styles.cardLabel}>{label}</div>
    </div>
  )
}

function ChartCard({ title, children }) {
  return (
    <div style={styles.chartCard}>
      <h3 style={styles.chartTitle}>{title}</h3>
      {children}
    </div>
  )
}

function round(v, d) {
  return Math.round(v * Math.pow(10, d)) / Math.pow(10, d)
}

// ── Styles ────────────────────────────────────────────────────────
const styles = {
  container: {
    minHeight: "100vh",
    background: "#0f172a",
    color: "#f1f5f9",
    fontFamily: "'Inter', sans-serif",
    padding: "24px"
  },
  header: {
    marginBottom: 24,
    borderBottom: "1px solid #1e293b",
    paddingBottom: 16
  },
  title: {
    fontSize: 24, fontWeight: 700,
    color: "#f1f5f9", margin: 0
  },
  subtitle: {
    color: "#64748b", margin: "4px 0 0", fontSize: 14
  },
  loading: {
    display: "flex", alignItems: "center",
    justifyContent: "center", height: "100vh",
    color: "#64748b", fontSize: 18,
    background: "#0f172a"
  },
  cardRow: {
    display: "grid",
    gridTemplateColumns: "repeat(4, 1fr)",
    gap: 16, marginBottom: 24
  },
  card: {
    background: "#1e293b",
    borderRadius: 8, padding: "16px 20px"
  },
  cardValue: {
    fontSize: 28, fontWeight: 700, marginBottom: 4
  },
  cardLabel: {
    fontSize: 13, color: "#94a3b8"
  },
  tabs: {
    display: "flex", gap: 4,
    marginBottom: 24,
    borderBottom: "1px solid #1e293b"
  },
  tab: {
    padding: "8px 20px",
    background: "transparent",
    border: "none", borderBottom: "2px solid transparent",
    color: "#64748b", cursor: "pointer",
    fontSize: 14, fontWeight: 500
  },
  tabActive: {
    color: "#3b82f6",
    borderBottom: "2px solid #3b82f6"
  },
  tabContent: { paddingTop: 8 },
  chartRow: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: 16, marginBottom: 24
  },
  chartCard: {
    background: "#1e293b",
    borderRadius: 8, padding: 20
  },
  chartTitle: {
    fontSize: 14, fontWeight: 600,
    color: "#94a3b8", marginBottom: 16, marginTop: 0
  },
  selector: {
    marginBottom: 20, display: "flex",
    alignItems: "center", gap: 12
  },
  label: { color: "#94a3b8", fontSize: 14 },
  select: {
    background: "#1e293b", color: "#f1f5f9",
    border: "1px solid #334155",
    borderRadius: 6, padding: "6px 12px",
    fontSize: 13, minWidth: 300
  },
  scoreBadge: {
    background: "#1e293b", borderRadius: 8,
    padding: "20px 24px", marginBottom: 24,
    display: "flex", alignItems: "center", gap: 16
  },
  scoreValue: {
    fontSize: 48, fontWeight: 800, color: "#10b981"
  },
  scoreLabel: {
    fontSize: 18, color: "#94a3b8"
  },
  faultBadge: {
    padding: "4px 12px", borderRadius: 20,
    fontSize: 12, fontWeight: 700,
    color: "#fff", marginLeft: "auto"
  },
  blastCard: {
    background: "#1e293b", borderRadius: 8,
    padding: "16px 24px", marginBottom: 24,
    display: "flex", alignItems: "center", gap: 12
  },
  blastLabel: { color: "#94a3b8", fontSize: 14 },
  blastValue: {
    fontSize: 32, fontWeight: 700, color: "#f97316"
  },
  propagationGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: 16, marginBottom: 16
  },
  serviceNode: {
    borderRadius: 8, border: "2px solid",
    padding: "20px", textAlign: "center"
  },
  nodeName: {
    fontSize: 18, fontWeight: 700, marginBottom: 8
  },
  nodeStatus: { fontSize: 14, marginBottom: 8 },
  nodeLag: { fontSize: 12, color: "#94a3b8" },
  dependencyNote: {
    textAlign: "center", color: "#475569",
    fontSize: 13, marginTop: 8
  }
}
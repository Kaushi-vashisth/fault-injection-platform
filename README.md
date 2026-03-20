# Fault Injection & Resilience Analytics Platform

A research platform for real-time fault injection, anomaly detection, and resilience scoring in distributed microservices systems.

## 🎯 Research Objective

Proactively detect and classify faults in distributed systems **before complete failure occurs** using real-time anomaly detection and ML-based fault classification.

## 🏗️ Architecture
```
Locust (Load Generator)
        ↓
Service A (Gateway) → Service B (Processor) → Service C (Storage/MongoDB)
        ↓                     ↓                        ↓
                    Prometheus (Metrics)
                    MongoDB (Storage)
                    Grafana (Monitoring)
                          ↓
              Fault Injection Engine
                          ↓
         Real-Time Detector (background thread)
                          ↓
         ML Fault Classifier (Random Forest)
                          ↓
         Resilience Scorer + Dashboard
```

## ✨ Key Features

- **4 Fault Types** — CPU stress, memory exhaustion, network delay, service crash
- **Real-time Detection** — anomalies detected every 10s during fault injection
- **ML Classification** — identifies fault type with confidence score
- **Resilience Scoring** — composite score across MTTR, latency, throughput, blast radius
- **OpenStack Validation** — results validated against DSSELab dataset (911 tests)
- **Live Dashboard** — React + Recharts dashboard with auto-refresh

## 📁 Project Structure
```
fault-injection-platform/
├── fault_engine/          # Fault injection executors
│   ├── executors/         # CPU, memory, network, crash, combo
│   ├── experiment_controller.py
│   ├── audit_logger.py
│   └── watchdog.py
├── observability/         # Metrics collection & cleaning
│   ├── metrics_collector.py
│   ├── data_cleaner.py
│   └── mongodb_setup.py
├── analytics/             # Analytics pipeline
│   ├── spark_jobs/        # MTTR, degradation, propagation
│   └── ml/                # Feature extraction, classifier, anomaly detector
├── scoring/               # Resilience scoring framework
├── realtime/              # Real-time detection pipeline
├── validation/            # OpenStack dataset comparison
├── dashboard/             # React + Vite frontend
├── experiments/configs/   # Experiment configurations
├── load_generator/        # Locust load generator
└── docker/                # Docker compose setup
```

## 🚀 Quick Start

### Prerequisites
- Docker Desktop
- Python 3.11+ (3.13 recommended)
- Node.js 18+

### Installation
```bash
# Clone repository
git clone https://github.com/Kaushi-vashisth/fault-injection-platform.git
cd fault-injection-platform

# Install Python dependencies
pip install pymongo prometheus-api-client pyyaml scikit-learn numpy pandas flask flask-cors locust

# Install dashboard dependencies
cd dashboard
npm install
cd ..
```

### Running the Platform

**Terminal 1 — Start Docker services:**
```bash
cd docker
docker compose up
```

**Terminal 2 — Start load generator:**
```bash
locust --headless -u 10 -r 2 --host http://localhost:8000 -f load_generator/locustfile.py
```

**Terminal 3 — Start Flask API:**
```bash
python dashboard/api_server.py
```

**Terminal 4 — Start dashboard:**
```bash
cd dashboard
npm run dev
```

**Terminal 5 — Run real-time pipeline:**
```bash
python -m realtime.realtime_pipeline experiments/configs/exp_001_cpu_service_b.yaml
```

Open `http://localhost:5173` and click the **Live** tab.

## 📊 Experiment Configs

| Config | Fault Type | Target | Duration |
|--------|-----------|--------|----------|
| exp_001_cpu_service_b.yaml | CPU Stress (80%) | service_b | 60s |
| exp_002_memory_service_b.yaml | Memory (100MB) | service_b | 30s |
| exp_003_network_service_b.yaml | Network Delay (200ms) | service_b | 30s |
| exp_004_crash_service_b.yaml | SIGKILL Crash | service_b | — |

## 🤖 ML Classification

- **Model:** Random Forest / Decision Tree (auto-selected by dataset size)
- **Features:** 65 statistical features across 3 services × 3 time windows
- **Accuracy:** 70% cross-validated (13 samples, 4 fault types)
- **Top features:** RPS delta, latency increase %, pre-fault latency std

## 📈 Resilience Scoring

Composite score (0.0 — 1.0) weighted across:
- MTTR (35%) — recovery speed
- Latency increase (25%)
- Throughput drop (25%)
- Error rate delta (15%)

## ✅ OpenStack Validation

Validated against [DSSELab Fault Injection Dataset](https://github.com/dessertlab/Fault-Injection-Dataset) (911 tests):

| Fault Type | OpenStack | Our Platform | Delta |
|-----------|-----------|-------------|-------|
| crash | 19.8% | 7.1% | 12.7% ✅ |
| network | 27.1% | 14.6% | 12.5% ✅ |

## 🔧 Adding New Fault Types

1. Create executor in `fault_engine/executors/`
2. Register in `fault_engine/experiment_controller.py`
3. Add experiment config in `experiments/configs/`
4. Retrain ML model: `python -m analytics.ml.classifier`

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-fault-type`
3. Commit changes: `git commit -m "Add new fault type"`
4. Push: `git push origin feature/new-fault-type`
5. Open a Pull Request

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 👤 Author

**Kaushi Vashisth**
- GitHub: [@Kaushi-vashisth](https://github.com/Kaushi-vashisth)

## 📚 References

- DSSELab Fault Injection Dataset: https://github.com/dessertlab/Fault-Injection-Dataset
- Prometheus: https://prometheus.io
- Scikit-learn: https://scikit-learn.org

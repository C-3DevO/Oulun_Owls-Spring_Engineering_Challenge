# 📡 RAN Control & Monitoring Dashboard (srsRAN + AI Scheduler)

A real-time **RAN control and monitoring dashboard** built on top of **srsRAN**, enabling dynamic control of network components and visualization of key performance metrics.

This tool bridges **AI-driven scheduling**, **5G system control**, and **live performance analytics** in one interface.

---

## 🚀 Key Features

### 🎛️ Network Control
- Start/Stop:
  - Open5GS Core
  - gNB (srsRAN)
  - Near-RT RIC (FlexRIC)
  - xApp (monitoring)
- Automatic dependency management:
  - gNB depends on Open5GS + RIC
  - xApp depends on gNB

---

### ⚙️ Dynamic Configuration (Live)
- Modify test parameters directly from UI:
  - Number of UEs
  - Rank Indicator (RI)
  - Scheduler type:
    - Round Robin (`rr_sched`)
    - QoS Scheduler (`qos_sched`)
    - AI Scheduler (`ai_sched`)
- Automatic **gNB restart after config update**

---

### 📊 Real-Time Monitoring
- UE-level metrics:
  - Throughput
  - CQI
  - RI
  - MCS
  - DL Buffer Size
- Cell-level metrics:
  - Total throughput
  - Jain’s fairness index
  - 
---

### 📈 Visualization (Chart.js)
- Live UE throughput graphs
- Cell throughput trends
- Fairness evolution
- DL buffer dynamics
- Auto-scaling charts

---

### 🧠 AI-RAN Integration
- Supports AI-based scheduling via:
  - Custom scheduler in srsRAN
- Enables experimentation with:
  - Reinforcement Learning (DQN / PPO)
  - Data-driven scheduling policies

---

### 📝 Logging & Data Export
- Automatic CSV logging per scheduler:
  - Throughput
  - CQI
  - Fairness
  - Cell performance
- Timestamped logs for experiments

---

## 🏗️ Dashboard Architecture

- **Flask Backend**
  - Process control (Open5GS, gNB, RIC, xApp)
  - YAML config manipulation
  - Log parsing & metrics extraction  

⬇️  

- **srsRAN gNB Logs**
  - Parsed in real-time for UE metrics  

⬇️  

- **Metrics Engine**
  - Computes:
    - Cell throughput
    - Jain fairness index  

⬇️  

- **Frontend (HTML + Chart.js)**
  - Interactive dashboard
  - Real-time visualization  

---

## 📁 Key Components

- `app.py`
  - Core backend logic (Flask server)
  - Process orchestration + metrics API  

- `templates/index.html`
  - Dashboard UI
  - Charts + controls  

- `logs/`
  - Runtime logs + CSV experiment data  

---

## ⚙️ Requirements

- Linux (Ubuntu recommended)
- Python 3.8+
- srsRAN (built)
- Open5GS installed and configured
- FlexRIC

---

## ▶️ Running the Dashboard

```bash
cd ran_dashboard

python3 -m venv new-env
source new-env/bin/activate

pip install -r requirements.txt

python app.py

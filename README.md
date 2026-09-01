# 📡 AI-Driven RAN Scheduling & Monitoring Platform

This project presents an **AI-powered Radio Access Network (RAN) scheduling system** built on top of **srsRAN**, combined with a **real-time monitoring dashboard** and **FlexRIC-based RAN monitoring**.

It demonstrates how **offline Artificial Intelligence scheduling** can improve **Physical Resource Block (PRB) allocation, throughput, and fairness** in a practical 5G New Radio testbed.

---

## 🚀 Project Overview

Modern 5G networks rely heavily on efficient scheduling of radio resources (PRBs). Traditional schedulers such as:

- Round Robin (RR)
- Proportional Fair (QoS/PF)

provide reliable baseline performance but often struggle to balance throughput and fairness across varying channel conditions.

👉 This project introduces three **offline AI-based schedulers** trained from real scheduler experience collected from the srsRAN MAC scheduler:

- **SLR** – Supervised Learning Ranker
- **CQL** – Conservative Q-Learning
- **IQL** – Implicit Q-Learning

The learned policies are evaluated against the classical schedulers under multiple network conditions.

---

## 🧠 Key Features

- ✅ End-to-end **srsRAN + Open5GS** 5G testbed
- ✅ Offline replay-buffer generation from MAC scheduler logs
- ✅ Three AI schedulers (SLR, CQL, and IQL)
- ✅ Integration with **FlexRIC** Near-RT RIC
- ✅ Real-time Flask monitoring dashboard
- ✅ CQI, throughput, fairness, and buffer monitoring
- ✅ Comparative evaluation across four experimental scenarios

---

## 🏗️ Project Structure

```text
Oulun_Owls-Spring_Engineering_Challenge/
├── srsRAN_Project/        # Modified srsRAN with AI scheduler integration
├── flexric/               # Near-RT RIC and xApp framework
├── ran_dashboard/         # Flask monitoring dashboard
├── model_items/           # Training and evaluation models
├── logs/                  # Scheduler logs and replay datasets
├── images/                # Experimental figures
├── ci/                    # CI scripts
└── README.md
```
---
## ⚙️ System Architecture

The scheduling pipeline operates entirely inside the modified **srsRAN gNB**.

1. **Traffic Generation**
   - Software UEs generate downlink traffic.

2. **MAC Scheduler**
   - Collects CQI, buffer occupancy, estimated rate, and historical throughput.

3. **AI Scheduler**
   - Computes UE priorities using SLR, CQL, or IQL.

4. **PRB Allocation**
   - The gNB allocates downlink resources.

5. **Monitoring**
   - Performance metrics are visualized through the Flask dashboard and monitored via FlexRIC.

The Near-RT RIC operates as an external monitoring framework and does not directly control scheduling decisions.

---

## 🧩 xApp (Near-RT RIC Monitoring)

This project integrates a **Near-Real-Time RAN Intelligent Controller (RIC)** using the **FlexRIC framework**.

### 📡 What is an xApp?

An xApp is a lightweight application running on the Near-RT RIC that subscribes to RAN measurements through the **E2 interface**.

In this project, the xApp is used for:

- Fairness monitoring
- RAN metric collection
- AI-RAN experimentation

### 🧠 Implemented xApp: Fairness Monitor

**Location**

```text
flexric/examples/xApp/c/monitor/xapp_fairness_moni.c
```

**Capabilities**

- Subscribes to E2SM-KPM measurements
- Computes Jain's Fairness Index
- Tracks rolling fairness statistics
- Detects fairness imbalance conditions

---

## 🤖 AI Scheduling Models

The AI schedulers learn directly from historical scheduling decisions collected from the MAC scheduler.

### Input Features

- CQI
- Buffer occupancy
- Average throughput
- Estimated rate
- Proportional Fair metric

### Implemented Models

| **Model** | **Learning Approach** |
|-----------|------------------------|
| SLR | Supervised Learning Ranker |
| CQL | Conservative Offline Reinforcement Learning |
| IQL | Implicit Offline Reinforcement Learning |

Offline policy evaluation showed that **IQL** most accurately recovered expert scheduling behavior, achieving the highest Top-1 recovery, strongest ranking agreement, and highest recovered reward.

---

## 📊 Dashboard

The Flask dashboard provides real-time visualization of network performance.

### Available Metrics

- Cell throughput
- Jain's Fairness Index
- UE-level throughput
- CQI distribution
- Buffer occupancy
- Scheduler comparison

---

## 📊 Experimental Evaluation

Four experimental scenarios were used to evaluate scheduler performance under different channel conditions, user densities, and transmission configurations.

| **Scenario** | **Configuration** |
|-------------|-------------------|
| **S1** | Slow fading, 5 UEs, Rank 1 |
| **S2** | Fast fading, 5 UEs, Rank 1 |
| **S3** | Slow fading, 10 UEs, Rank 1 |
| **S4** | Slow fading, 5 UEs, Rank 2 |

### Scenario 1 — Slow Fading (5 UEs)

Heterogeneous channel conditions created clear CQI differences between users.

**Results**

- SLR achieved the highest throughput.
- QoS provided the strongest fairness and cell-edge protection.
- IQL delivered the best overall throughput-fairness compromise.

### Scenario 2 — Fast Fading (5 UEs)

Fast fading averaged out long-term CQI differences, producing nearly homogeneous channel conditions.

**Results**

- IQL achieved **50.14 Mbps** throughput.
- Throughput improved by **19.5%** over RR.
- Fairness also increased, demonstrating strong adaptation under homogeneous conditions.

### Scenario 3 — Slow Fading (10 UEs)

Increasing the number of users amplified scheduling competition.

**Results**

- IQL achieved the highest throughput.
- QoS remained the fairest scheduler.
- SLR prioritized throughput while reducing fairness.

### Scenario 4 — Rank-2 Transmission

Rank-2 transmission substantially increased available spatial capacity.

**Results**

- Throughput increased across all schedulers.
- IQL achieved the highest throughput.
- QoS remained the strongest fairness-oriented scheduler.

---

## 📈 Offline Policy Evaluation

The learned schedulers were also evaluated against the expert replay dataset.

| **Metric** | **SLR** | **CQL** | **IQL** |
|------------|:-------:|:-------:|:-------:|
| Top-1 Recovery | 0.710 | 0.794 | **0.955** |
| Spearman Correlation | 0.497 | 0.577 | **0.971** |
| Avg Reward | 0.692 | 0.712 | **0.774** |
| Avg PRBs | 34.4 | 37.1 | **39.3** |

These results demonstrate that **IQL** most faithfully reproduces expert scheduling behavior while selecting higher-quality scheduling decisions.

---

## ⚖️ Overall Takeaways

- ✅ Offline learning successfully improves PRB allocation without requiring online exploration.
- ✅ IQL consistently provides the strongest throughput-fairness trade-off.
- ✅ SLR aggressively clears buffers and prioritizes throughput.
- ✅ CQL remains close to expert scheduling behavior while providing stable improvements.
- ✅ FlexRIC enables external monitoring without modifying scheduler control.
- ✅ The framework provides a practical platform for AI-assisted RAN research.

---

## 🛠️ Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/C-3DevO/Oulun_Owls-Spring_Engineering_Challenge.git
cd Oulun_Owls-Spring_Engineering_Challenge
```

### 2. Build srsRAN

```bash
cd srsRAN_Project
mkdir build && cd build
cmake ..
make -j$(nproc)
```

### 3. Start Open5GS

Launch the required Open5GS core services.

### 4. Run the gNB

```bash
./gnb -c ../configs/gnb_custom_cell_2.yml
```

### 5. Launch the Dashboard

```bash
cd ../../ran_dashboard
python app.py
```

### 6. Run FlexRIC (Optional)

Start the Near-RT RIC and fairness monitoring xApp.

---

## 📚 Technologies Used

- srsRAN Project
- Open5GS
- FlexRIC
- Python
- PyTorch
- C++
- Flask
- Docker
- Git

---

## 👥 Authors

- **Brian Kibor**
- **Rubayet Kabir**

*University of Oulu – Wireless Communications Engineering*

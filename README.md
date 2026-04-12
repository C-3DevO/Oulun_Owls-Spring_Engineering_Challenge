# 📡 AI-Driven RAN Scheduling & Monitoring Platform

This project presents an **AI-powered Radio Access Network (RAN) scheduling system** built on top of **srsRAN**, combined with a **real-time monitoring dashboard**.

It demonstrates how  Reinforcement Learning can be used to improve **resource allocation, fairness, and throughput** in 5G networks.

---

## 🚀 Project Overview

Modern 5G networks rely heavily on efficient scheduling of radio resources (PRBs). Traditional schedulers such as:

- Round Robin (RR)
- Proportional Fair (PF)
- Max-CQI

have limitations in dynamic environments.

👉 This project introduces an **AI-based scheduler** that learns optimal allocation strategies using data-driven approaches.

---

## 🧠 Key Features

- ✅ AI-based scheduler (Linear Regression + Reinforcement Learning)
- ✅ Integration with **srsRAN (5G stack)**
- ✅ YAML-driven configuration for flexible experimentation
- ✅ Real-time metrics collection (CQI, throughput, buffer, fairness)
- ✅ Interactive web dashboard for visualization
- ✅ Comparison with traditional schedulers (RR, PF)

---

## 🏗️ Project Structure
Oulun_Owls-Spring_Engineering_Challenge/
│
├── srsRAN_Project/ # Modified srsRAN stack (AI scheduler integration)
├── ran_dashboard/ # Flask dashboard for visualization
├── flexric/ # External RIC framework

---

## ⚙️ System Architecture
YAML Config (testmode.yml)
↓
Config Translator (DU Layer)
↓
Scheduler Factory
↓
AI Scheduler (DQN / ML Model)
↓
PRB Allocation (srsRAN)
↓
Metrics → Dashboard (Flask)

---

## 🤖 AI Scheduler

The AI scheduler uses:

- 📊 Features:
  - CQI
  - Buffer size
  - Average throughput
  - Historical allocation

- 🎯 Output:
  - Scheduling priority per UE

- 🧠 Models:
  - Linear Regression (baseline)
  - Reinforcement Learning (DQN)

---

## 📊 Dashboard (ran_dashboard)

A Flask-based web app that provides:

- Real-time throughput visualization
- Fairness analysis (Jain’s Index)
- UE-level performance monitoring
- Scheduler comparison plots

---

## 🛠️ Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/C-3DevO/Oulun_Owls-Spring_Engineering_Challenge.git
cd Oulun_Owls-Spring_Engineering_Challenge


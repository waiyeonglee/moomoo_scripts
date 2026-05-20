# Portfolio Analytics Engine (Python)

A Python-based portfolio analytics system that integrates with broker APIs to track real-time positions, compute profit & loss (realized and unrealized), and support both live trading and backtesting workflows.

---

## 🚀 Features

- Real-time portfolio tracking via broker API integration  
- Automated computation of realized and unrealized P/L  
- Session-aware data handling for market trading days  
- Unified logic for both live trading and backtesting modes  
- Robust handling of inconsistent and fragmented position data  
- Daily logging and portfolio state persistence  

---

## 🧠 System Overview

This project builds a portfolio state engine that reconstructs and tracks trading performance across time.

It ensures consistency between:
- Live trading environment (real-time updates)
- Backtesting environment (historical replay)

Key focus areas:
- Accurate P/L computation
- Clean portfolio state management
- Reliable handling of broker API data inconsistencies

---

## 📊 Core Components

### 1. Data Ingestion
Fetches account and position data from broker APIs.

### 2. Portfolio Engine
Processes:
- Position aggregation
- Unrealized P/L computation
- Realized P/L tracking

### 3. Session Management
Ensures correct handling of trading days and prevents mixing partial sessions.

### 4. Logging Layer
Stores daily portfolio snapshots for tracking and debugging.

---

## 🛠 Tech Stack

- Python
- Pandas
- Broker API (Moomoo/Futu OpenAPI)
- Date/Time utilities for session handling

---

## 📈 Example Output

- Total Assets
- Position-level breakdown
- Realized P/L
- Unrealized P/L
- Portfolio exposure tracking

---

## 📌 Key Design Goals

- Consistency between live and backtest environments  
- Accurate financial calculations across trading sessions  
- Resilience against incomplete or duplicated API data  
- Simple and extensible architecture for future strategy integration  

---

## ⚠️ Notes

- Designed for single-stock and multi-position portfolio tracking  
- Assumes regular trading sessions for session segmentation logic  
- API responses may contain duplicate or fragmented position rows, which are normalized internally  

---

## 🔧 Future Improvements

- Strategy module integration (signals, indicators)  
- Visualization dashboard for portfolio performance  
- Trade-level analytics (win rate, Sharpe ratio, drawdown)  
- Multi-asset portfolio support  

---

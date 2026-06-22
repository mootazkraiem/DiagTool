# 🛡️ CANVision System QA & Validation Plan

**Date:** 2026-06-21
**Author:** Senior QA Engineer (Goose Agent)
**Project Status:** Initial Discovery Phase (Pre-Validation)

## 🎯 Objective
To rigorously validate the entire CANVision system, ensuring stability, correctness, and performance across all components (C#, Python, ML, API) before deployment. **Validation will continue until all system components are stable.**

## 🗺️ 1. Project Architecture Overview (Mental Map)
The system employs a hybrid architecture:
1.  **Frontend (C#/.NET):** Responsible for the user interface, visualization (using HelixToolkit), and handling data display (UI/Styles). It interacts with the backend via the `PythonApiClient.cs` service.
2.  **Backend (Python):** The core intelligence layer. It manages data ingestion, processing, and analysis.
    *   **Data Layer:** Handled by `backend/data_processing/` (e.g., `parser.py`, `decoder.py`, `mf4_to_csv_converter.py`).
    *   **ML Layer:** Located in `backend/ml/`, this is where feature engineering (`feature_engineering.py`), anomaly detection (Isolation Forest, OCSVM), and model evaluation occur.
    *   **API Layer:** The `backend/api/server.py` provides the interface for external interaction (FastAPI).
    *   **Intelligence Layer:** `backend/knowledge/` contains critical system assets like `attack_kb.json` (for the Analyst Assistant) and `signal_map.json`.
3.  **Workflow:** Data is ingested (via `hardware/can_interface.py`), processed, features are extracted, models are run, and results are served via the API to the C# frontend.

## 📁 2. Important Paths & Components
| Component | Path/File | Purpose | Type |
| :--- | :--- | :--- | :--- |
| **C# Solution** | `CANvisionNative.sln` | Primary project file for the GUI/Client. | Build Target |
| **C# Code** | `Converters/`, `Models/`, `UI/` | UI logic, data models, and view definitions. | Source Code |
| **Python Backend** | `backend/` | Contains all core business logic, ML, and API. | Source Code |
| **FastAPI Entry** | `backend/api/server.py` | The main entry point for the API server. | Entry Point |
| **ML Pipeline** | `backend/ml/core/feature_engineering.py` | Core logic for extracting features from raw CAN data. | Core Module |
| **Dataset/Ground Truth**| `backend/ml/configs/runtime_config.py` | Configuration, likely holds paths to datasets. | Config |
| **Test Files** | `backend/data_processing/integration_test.py` | Existing unit/integration testing files. | Testing |
| **Analyst Assistant** | `backend/knowledge/attack_kb.json` | Knowledge base used by the assistant. | Asset/KB |
| **ML Models** | `backend/ml/models/` | Directory storing trained model snapshots. | Assets/Models |
| **Validation Reports**| `backend/ml/results/` | Contains summaries of ML validation runs. | Datasets |
| **Dependencies** | `requirements.txt` | Lists required Python libraries. | Dependency List |

## 🛠️ 3. Commands & Dependencies
### ⚙️ Dependencies
*   **Python:** All packages listed in `requirements.txt`.
*   **C#:** .NET SDK (required to compile `CANvisionNative.csproj`).
*   **External:** Assimp (for 3D visualization, noted in DLLs).

### 🚀 Required Commands
| Action | Environment | Command | Notes |
| :--- | :--- | :--- | :--- |
| **C# Build** | Windows/CLI | `dotnet build CANvisionNative.csproj` | Must be run before UI tests. |
| **Python Test** | Python/CLI | `pytest backend/` | Execute all tests in the backend directory. |
| **API Run** | Python/CLI | `uvicorn backend.api.server:app --reload` | Start the FastAPI server. |
| **Run Full Pipeline** | Python/CLI | `python backend/runtime/replay_runner.py` | Placeholder for the complete 11-step validation sequence.
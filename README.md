# GammaRips MCP Server

GammaRips is an **Agent-First Options Trading Intelligence Platform** built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It provides AI agents with real-time access to high-quality financial data, technical analysis, and options market structure (Vol/OI walls, Gamma exposure).

## Features

*   **Winners Dashboard:** Real-time ranking of high-gamma options opportunities.
*   **Market Structure Analysis:** Deep dive into Volume and Open Interest walls to identify support/resistance.
*   **Technical Analysis:** comprehensive indicators (RSI, MACD, Moving Averages) and trend analysis.
*   **Fundamental Insights:** Access to 10-K risk factors, earnings call transcripts, and financial metrics.
*   **News & Sentiment:** Real-time news analysis and sentiment scoring.

## Project Structure

```
gammarips-mcp/
├── docs/               # Documentation, changelogs, and roadmap
├── scripts/            # Deployment and debugging scripts
├── src/
│   ├── data/           # BigQuery and GCS client libraries
│   ├── tools/          # Individual MCP tool implementations
│   ├── utils/          # Helper functions
│   └── server.py       # Main FastMCP server entry point
├── tests/              # Test suites and runners
└── ...
```

## Getting Started

### Prerequisites

*   Python 3.12+
*   Google Cloud Platform (GCP) account with BigQuery and GCS enabled.
*   `gcloud` CLI installed and authenticated.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/yourusername/gammarips-mcp.git
    cd gammarips-mcp
    ```

2.  **Create a virtual environment:**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r pyproject.toml # or pip install .
    ```

4.  **Configuration:**
    Copy `.env.example` to `.env` and fill in your GCP credentials and project details.
    ```bash
    cp .env.example .env
    ```

### Running Locally

```bash
# Run the MCP server
python src/server.py
```

### Deployment

Deploy to Google Cloud Run using the provided script:

```bash
./scripts/deploy.sh
```

## Testing

This project uses a comprehensive "LLM-as-a-Judge" evaluation framework.

```bash
# Run the comprehensive test suite
python tests/comprehensive_runner.py
```

See `docs/reports/` for past evaluation results.

## License

[MIT License](LICENSE)
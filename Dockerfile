# Use the official Python lightweight image
FROM python:3.11-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml ./
COPY src ./src
# Methodology playbooks served by list_playbooks/get_playbook + MCP resources
COPY content ./content

# Install dependencies
RUN uv pip install --system --no-cache -e .

# Allow statements and log messages to immediately appear in the logs
ENV PYTHONUNBUFFERED=1

# Set Python path to include src directory
ENV PYTHONPATH=/app/src

# Expose port (Cloud Run will set the PORT environment variable)
EXPOSE 8080

# Run the FastMCP server with uvicorn
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]

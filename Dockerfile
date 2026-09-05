FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[mcp]"
ENV SHIFT_RELAY_DB=/tmp/shiftrelay.db
EXPOSE 8000
CMD ["python", "-m", "shift_relay.mcp_server"]

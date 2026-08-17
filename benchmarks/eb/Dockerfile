FROM python:3.11-slim
WORKDIR /workspace
COPY pyproject.toml README.md /workspace/
COPY eb /workspace/eb
RUN pip install --no-cache-dir -e .
CMD ["python", "-m", "eb.cli", "--help"]

# JobVeyra in a container. Mount your workspace at /workspace:
#   docker build -t jobveyra .
#   docker run --rm -v "$PWD/my-search:/workspace" jobveyra discover
# Browser submission needs a browser-driving agent on your own machine and is not run here.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 JOBVEYRA_HOME=/workspace
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[charts]" && useradd --create-home jobveyra
USER jobveyra
WORKDIR /workspace
ENTRYPOINT ["jobveyra"]
CMD ["--help"]

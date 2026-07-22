FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

LABEL org.opencontainers.image.source="https://github.com/oyasumiholiday/ailex"
LABEL org.opencontainers.image.description="Reproducible IntentIR v0.14 command-line demonstration"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 intentir

WORKDIR /opt/intentir

COPY --chown=intentir:intentir LICENSE-APACHE README.md pyproject.toml ./
COPY --chown=intentir:intentir intentir ./intentir
COPY --chown=intentir:intentir examples ./examples
COPY --chown=intentir:intentir demo ./demo
COPY --chown=intentir:intentir benchmarks ./benchmarks

USER intentir

ENTRYPOINT ["python", "-m", "intentir"]
CMD ["demo", "concurrent-agent"]

# NOT build-tested — this build sandbox has no Docker daemon available, so this
# file was written and reasoned through but never actually `docker build`'d.
# Test it for real (`docker build -t anticassiopeia .`) before relying on it for
# the submission; the most likely failure point is the RUN evals step below if
# any path assumption is wrong.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY anticassiopeia ./anticassiopeia

RUN pip install --no-cache-dir -e .

# Not copied into the image on purpose: datasheets/reports/datasets a deployer
# wants verified live should be mounted in or fetched at runtime, not baked in.
# evals/ IS copied so `python evals/run_evals.py` works as a container healthcheck
# / CI smoke test against the fixtures that ship with the repo.
COPY evals ./evals

EXPOSE 8000

# Fails the build/run step loudly if the bone framework itself is broken,
# rather than shipping an image that imports but doesn't actually work.
RUN PYTHONPATH=. python evals/run_evals.py

CMD ["uvicorn", "anticassiopeia.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

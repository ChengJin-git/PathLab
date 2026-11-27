ARG BASE_IMAGE=python:3.12.12-slim-bookworm
FROM ${BASE_IMAGE}
ARG TARGETARCH
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
    OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 XFORMERS_DISABLED=1 \
    MPLCONFIGDIR=/tmp/matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git bash libglib2.0-0 libgl1 libgomp1 libopenslide0 \
    pandoc ffmpeg fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'numpy==1.26.4' \
    'torch==2.9.1' 'torchvision==0.24.1' --index-url ${TORCH_INDEX}
COPY server/backend/autoresearch/runtime/containers/ml-runtime-requirements.txt /opt/pathlab/ml-runtime-requirements.txt
RUN printf 'torch==2.9.1\ntorchvision==0.24.1\n' > /opt/pathlab/base-constraints.txt && \
    pip install --no-cache-dir -c /opt/pathlab/base-constraints.txt -r /opt/pathlab/ml-runtime-requirements.txt
COPY server/backend/autoresearch/runtime/containers/skills-runtime-requirements.txt /opt/pathlab/skills-requirements.txt
RUN pip install --no-cache-dir -c /opt/pathlab/base-constraints.txt \
    -c /opt/pathlab/ml-runtime-requirements.txt -r /opt/pathlab/skills-requirements.txt
COPY deploy/install-opencode.py /opt/pathlab/install-opencode.py
COPY package.json /opt/package.json
RUN target="linux-x64"; if [ "$TARGETARCH" = "arm64" ]; then target="linux-arm64"; fi; \
    python /opt/pathlab/install-opencode.py --target "$target" --output /opt/opencode && \
    test "$(/opt/opencode --version)" = "opencode v$(python -c 'import json; print(json.load(open("/opt/package.json"))["opencodeVersion"])')"
RUN mkdir -p /workspace /research-data /opt/pathlab/templates /opt/pathlab/guidance /opt/pathlab/skill-library /home/research
WORKDIR /workspace
CMD ["python"]

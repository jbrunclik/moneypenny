FROM python:3.14-slim-trixie

# Install system dependencies for Python libraries
# - fonts-dejavu-core: Unicode support for PDF generation (fpdf2)
# - gcc, g++: Compilers for building numpy/scipy from source if needed
# - libgomp1: OpenMP library for numpy/scipy parallelization
RUN apt-get update -qq && \
    apt-get install -y -qq \
        fonts-dejavu-core \
        gcc \
        g++ \
        libgomp1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Pre-install commonly used Python libraries to avoid runtime installation
# This significantly speeds up code execution as libraries are already cached
RUN pip install --no-cache-dir \
    numpy \
    pandas \
    matplotlib \
    scipy \
    sympy \
    pillow \
    reportlab \
    fpdf2 \
    requests \
    beautifulsoup4 \
    lxml \
    openpyxl \
    python-docx \
    python-pptx \
    python-dateutil \
    pytz \
    pypdf \
    pdfplumber

# Helpers importable from user code (from sandbox_helpers import pdf_overview)
COPY sandbox_helpers.py /opt/helpers/sandbox_helpers.py
ENV PYTHONPATH=/opt/helpers

# Code runs as this user, never root (Nov 16 2026). The uid matches
# SANDBOX_UID in src/agent/tools/docker_sandbox.py; /work, /output and /tmp
# are memory-backed mounts owned by it, the root filesystem is read-only.
# HOME and MPLCONFIGDIR point at writable places: matplotlib and friends
# write caches on import.
RUN groupadd --gid 10001 sandbox && \
    useradd --uid 10001 --gid 10001 --no-create-home --home-dir /work sandbox
ENV HOME=/work MPLCONFIGDIR=/tmp/matplotlib XDG_CACHE_HOME=/tmp/cache
USER 10001:10001
WORKDIR /work

# Add labels to identify our custom image and enable cleanup of old versions
LABEL moneypenny.sandbox=true \
      moneypenny.version=1.3

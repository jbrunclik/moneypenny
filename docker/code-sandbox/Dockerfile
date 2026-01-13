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
    python-dateutil \
    pytz

# Add labels to identify our custom image and enable cleanup of old versions
LABEL ai-chatbot.sandbox=true \
      ai-chatbot.version=1.0

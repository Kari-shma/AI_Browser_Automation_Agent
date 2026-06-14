FROM mcr.microsoft.com/playwright/python:v1.52.0-jammy

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Re-install Playwright's Chromium browser to match the installed package version.
# System dependencies (libgbm, libnss3, etc.) are already in the base image,
# so no install-deps / sudo needed.
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Ensure runtime directories exist (git doesn't track empty folders)
RUN mkdir -p artifacts scripts/generated

EXPOSE 8000

ENV HOST=0.0.0.0
ENV ENV=production

CMD ["python", "api/main.py"]

# Use a slim Python image for minimal size
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first (Docker layer caching — faster rebuilds)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

# Run the bot (non-interactive cloud mode is detected automatically)
CMD ["python", "new script.py"]

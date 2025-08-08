FROM python:3.10

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
RUN playwright install --with-deps chromium

# Copy project files
COPY . .

# Expose port Hugging Face
EXPOSE 7860

# Jalankan server
CMD ["python", "run.py"]

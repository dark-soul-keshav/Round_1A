# Use a specific, lightweight Python version
FROM --platform=linux/amd64 python:3.10-slim

# --- INSTALL SYSTEM DEPENDENCIES (TESSERACT OCR) ---
# Update package list and install Tesseract with English and French language packs
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra && \
    # Clean up the package cache to keep the image size small
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# --- INSTALL PYTHON LIBRARIES (OFFLINE) ---
# Copy the pre-downloaded libraries
COPY libraries/ /app/libraries/
# Copy the requirements file
COPY requirements.txt .
# Install packages from the local 'libraries' folder without using the internet
RUN pip install --no-index --find-links=./libraries -r requirements.txt

# --- COPY APPLICATION CODE ---
COPY main_1A.py .

# --- SET EXECUTION COMMAND ---
# Specify the command to run when the container starts
CMD ["python", "main_1A.py"]
# Use the official Python 3.9 image as the base image
FROM python:3.11
EXPOSE 1710

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file to the working directory
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code to the working directory
COPY . .

# Set the environment variable
ENV PYTHONPATH=/app/backend

# Define volume to store data.json and create data.json
VOLUME /app/data/

# Set the command to run the application
WORKDIR /app/backend
RUN echo ""
CMD [ "./app.sh" ]

# https://docs.docker.com/reference/dockerfile/#run---mounttypebind
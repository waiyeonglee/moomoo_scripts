#!/bin/bash

# Directory where your files are
DIR="/home/ubuntu/moomoo_scripts/logs"

# Find the latest file (by modification time)
latest_file=$(ls -t "$DIR"/* | head -1)

# Upload it to S3
if [ -n "$latest_file" ]; then
    aws s3 cp "$latest_file" s3://moomoos3/
    echo "Uploaded $latest_file to S3"
else
    echo "No files found in $DIR"
fi
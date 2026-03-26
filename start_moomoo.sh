#!/bin/bash

# Copy latest main.py to EC2
aws s3 cp s3://moomoos3/main.py /home/ubuntu/moomoo_scripts/main.py

# Run main.py
/home/ubuntu/moomoo/bin/python3 -u /home/ubuntu/moomoo_scripts/main.py --live
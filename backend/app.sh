#!/bin/bash

while true
do
    python backend.py
    echo "Server 'backend.py' crashed with exit code $?.  Respawning..." >&2
    sleep 1
done
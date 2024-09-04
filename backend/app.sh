#!/bin/sh

if [ "$APP_MODE" = "0" ]; then
    python backend-standalone.py
elif [ "$APP_MODE" = "1" ]; then
    python backend-obsidian.py
fi
#!/bin/bash

# Intended use:
# 1. To substitute UI-based Git clients for simple Git operations
# i.e: Obsidian Git plugin
# This way the bot can be deployed on a remote server and run without
# the need for a UI-based Git client


# Run in an infinite loop
while true; do
    # change to the directory of the script
    cd "$(dirname "$0")"

    # commit all local changes with generic message
    git add .
    git commit -m "Autogit commit"

    # pull the latest changes, if any conflict, keep theirs
    git pull -s recursive -X theirs

    # push the changes to the remote repository
    git push

    # Sleep for 5 minutes (300 seconds) before next execution
    echo "Sleeping for 5 minutes before next execution..."
    sleep 300
done
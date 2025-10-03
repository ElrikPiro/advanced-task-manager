# Elrikpiro's Advanced Task Manager

## Description

Elrikpiro's Advanced Task Manager is a tool designed to help users manage and automate their tasks efficiently. It integrates with Telegram to send notifications and updates about task statuses directly to your chat. This project aims to streamline task management and improve productivity by providing a user-friendly interface and robust automation features.

![Diagrama Arquitectura](https://github.com/user-attachments/assets/26fad6b0-b45f-4be0-a6fb-dba612fa2aaf)

## Before starting

### Configure the config.json file
The first time the application is running it will ask you a few questions about your preferences:

#### App Mode

- **JSON file** : The application will save your tasks in a single JSON file, this is the most simple and easy to configure.
- **Markdown vault** : The application will scan a given directory and subdirectories for markdown files and query for tasks in them.
- **cmd** : Means that the application will interact with the user by using a command console.
- **telegram** : Means that the application will interact with the user by using a telegram bot. (Bot credentials should be provided)

Note: by now Markdown vault mode will only show tasks that have the following strings that start with '- [ ]' and contain '[track:: (category)]', '[start:: (date in YYYY-MM-DD format)]' and '[due:: (date in YYYY-MM-DD format)]'. It is projected to add some configurability on these matters to ease up it's use.

#### Data files directory

It will ask you for a directory to save your data files, uses the current directory by default.

#### Telegram credentials

If a telegram mode is selected, it will ask for a telegram bot token, if you don't know how, please check the section `Getting Ready>Obtain your bot token` from this site: https://core.telegram.org/bots/tutorial.

It will also ask you for a telegram chat Id, you can get it by following this tutorial: https://www.wikihow.com/Know-Chat-ID-on-Telegram-on-Android

#### Markdown vault directory

If a Markdown vault mode is selected, the application will need a directory (and subdirectory) to scan markdown (.md) files to. 

> [!note]
> Several markdown editors like Logseq or Obsidian allow users to create templates that combined with this functionability, would create a consistent TODO-list for tasks with any given periodicity.

#### Finally

A file called `config.json` will be created with a basic set of task categories/contexts, you can modify this file to reconfigure your task manager or delete it so the application will prompt you again on the next start.

## Usage (Python 3.11)

run `python backend.py` in the backend folder

## Usage (Win64 Binaries)

unzip the archive and double click the executable, a console window will open and apply the settings contained at config.json

## Usage (Docker)

### Clone this repository
```bash
git clone https://github.com/ElrikPiro/advanced-task-manager.git
```

### Configure the compose.yaml
`TZ` should be replaced with your timezone. You can find a list of valid timezones [here](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

Edit the `compose.yaml` file to configure the application settings:

### Configure your config.json

Use the tutorial above or modify the example.

#### Examples

##### Single User JSON example
compose.yaml
```yaml
version: '3.8'

services:
  advancedtaskmanager:
    image: advancedtaskmanager:latest
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    environment:
      - TZ=Europe/Madrid
    volumes:
      - .:/app/data/
```

config.json
```json
{
    "categories": [
        {
            "prefix": "alert",
            "description": "Alert and events"
        },
        {
            "prefix": "billable",
            "description": "Tasks that generate income"
        },
        {
            "prefix": "indoor",
            "description": "Indoor dynamic tasks"
        },
        {
            "prefix": "aux_device",
            "description": "Lightweight digital/analogic tasks"
        },
        {
            "prefix": "bujo",
            "description": "Bullet journal tasks"
        },
        {
            "prefix": "workstation",
            "description": "Heavyweight digital tasks"
        },
        {
            "prefix": "outdoor",
            "description": "Outdoor dynamic tasks"
        }
    ],
    "APP_MODE": 3,
    "JSON_PATH": ".",
    "TELEGRAM_BOT_TOKEN": "<Your telegram bot token>",
    "TELEGRAM_CHAT_ID": "<Your telegram user id>",
}
```

### Build the Docker image
```bash
docker-compose build
```

### Run the Docker container
```bash
docker-compose up -d
```

## Contributing

We welcome contributions to Elrikpiro's Advanced Task Manager! To contribute, follow these steps:

1. **Fork the repository:**
   Click the "Fork" button on the top right corner of the repository page to create a copy of the repository in your GitHub account.

2. **Clone your forked repository:**
   ```sh
   git clone https://github.com/yourusername/advanced-task-manager.git
   cd advanced-task-manager
   ```

3. **Create a new branch:**
   ```sh
   git checkout -b feature/your-feature-name
   ```

4. **Make your changes:**
   Implement your feature or bug fix.

5. **Commit your changes:**
   ```sh
   git add .
   git commit -m "Add your commit message here"
   ```

6. **Push to your branch:**
   ```sh
   git push origin feature/your-feature-name
   ```

7. **Create a Pull Request:**
   Go to the original repository and click the "New Pull Request" button. Provide a clear description of your changes and submit the pull request.

8. **Review Process:**
   Your pull request will be reviewed by the maintainers. Please be responsive to any feedback or requests for changes.

Thank you for contributing to Elrikpiro's Advanced Task Manager!

## License

MIT License

Copyright (c) 2024 David Baselga Masià

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

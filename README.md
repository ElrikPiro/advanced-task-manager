# Elrikpiro's Advanced Task Manager

## Description

Elrikpiro's Advanced Task Manager is a tool designed to help users manage and automate their tasks efficiently. It integrates with Telegram to send notifications and updates about task statuses directly to your chat. This project aims to streamline task management and improve productivity by providing a user-friendly interface and robust automation features.

## Before starting

### Configure the config.json file
`APP_MODE` 
- 0: single user JSON mode, which persists tasks on a single json file. 
- 1: single user OBSIDIAN mode, which loads the tasks from the Obsidian vault. *This feature is incomplete as it depends on the DataviewJs Plugin and requires to add several scripts to your vault and leaving it running on the background.*
- -1: single user JSON mode (debug), it will print the tasks on the console instead of sending them to Telegram. Requires interactive shell as it expects to interact with the user via stdin.

In case you want to use telegram, `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` should be replaced with your Telegram bot token and chat ID, respectively. You can obtain these values by creating a new bot using the [BotFather](https://core.telegram.org/bots#6-botfather) and sending a message to the bot to get the chat ID.

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

#### Examples

##### Single User JSON example
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

# Elrikpiro's Advanced Task Manager

## Description

Elrikpiro's Advanced Task Manager is a tool designed to help users manage and automate their tasks efficiently. It integrates with Telegram to send notifications and updates about task statuses directly to your chat. This project aims to streamline task management and improve productivity by providing a user-friendly interface and robust automation features.

For detailed architecture documentation, see [ARCHITECTURE.md](./ARCHITECTURE.md).


## Before starting

### Configure the config.json file
The first time the application is running it will ask you a few questions about your preferences:

#### App Mode

- **JSON file** : The application will save your tasks in a single JSON file, this is the most simple and easy to configure.
- **Markdown vault** : The application will scan a given directory and subdirectories for markdown files and query for tasks in them.
- **cmd** : Means that the application will interact with the user by using a command console.
- **telegram** : Means that the application will interact with the user by using a telegram bot. (Bot credentials should be provided)
- **API** : Means that the application will interact with the user via a REST API interface. Server configuration should be provided.

Available combinations:
1. **Obsidian (cmd)** - Markdown vault with command line interface
2. **JSON file (cmd)** - JSON storage with command line interface
3. **JSON file (telegram)** - JSON storage with Telegram bot interface
4. **Obsidian (telegram)** - Markdown vault with Telegram bot interface
5. **JSON file (API)** - JSON storage with the resource-oriented HTTP API
6. **Obsidian (API)** - Markdown vault with the resource-oriented HTTP API

### HTTP API behavior and limits

`APP_MODE` 5/6 exposes the versioned resource API. `HTTP_API_PREFIX` sets its base path and defaults to `/api/v1`; a mount prefix such as `/manager/api/v1` is supported. It provides task, agenda, statistics, event, strategy, project and operation resources using HAL JSON (`application/hal+json`). Reads use explicit query parameters and do not change a shared task-list selection. Task changes use `PATCH` with `application/merge-patch+json`; task and project actions use typed `POST /operations` requests. Arbitrary command names and unknown fields are rejected. Errors use `application/problem+json`. Bearer authentication is required, and responses are marked `Cache-Control: no-store`.

Task-list queries default to page 1, five items per page, the `All active task filter`, the `GTD Algorithm`, and `Remaining Effort(1)`. `filters` and `search` can be repeated; page and page size must be positive integers. Each `POST /operations` request must carry a client-generated UUID in `id` before it is first sent. The server returns the final result; the same UUID and intent return the original in-process outcome, while a different intent conflicts. Receipts are held in memory, disappear after restart, and are never replayed when absent; a missing receipt does not prove that no write happened.

Older command-style GET paths that could change task data or shared view state are retired and return `404` with the `legacy-route-retired` problem code. The old volatile `/notifications` endpoint is also unavailable; persistent notification history is not part of the current API.

The API accepts a configured Bearer token, but the backend does not enforce HTTPS. Validation for this version used a local loopback test server; HTTPS behavior has not been verified and HTTPS enforcement remains unimplemented. Do not expose the token over an untrusted network.

Task IDs are opaque strings stored with each task: JSON records use `id`, and Markdown task lines can declare `[id:: value]`. When an older task has no ID, the backend derives a compatibility ID from its description and current storage location. JSON uses the configured task-file path and the task's zero-based position in the full array; Markdown uses the file path and line number. Reading does not write a derived ID. The first real task update stores it, and later edits or moves keep that value. Resolution includes completed tasks. A lookup for an ID with no matching task reports absence, while duplicate IDs report ambiguity and block writes to that ID. MD5 fallback IDs can collide, so the backend does not guarantee mathematical uniqueness.

The backend does not provide persistent, non-destructive notification history.

### File save behavior

Task data, project files, and work statistics are saved one file at a time through a temporary file in the same directory, followed by an atomic replacement. Readers see the complete previous file or the complete replacement. If a write fails before replacement, that file is known to be unchanged; if durability fails after replacement, the saved state may be uncertain. Operations that touch several files stop at the first failure and report the confirmed changes for review. They do not roll back earlier files or retry automatically. External editors can still change a file between the backend's comparison and replacement.

All writes initiated inside one running backend process enter a shared in-memory FIFO queue. A task operation that also updates statistics holds one queue turn across both files, and discovery, project changes, imports, and channel commands use the same queue. A caller that times out or disconnects stops waiting; an already admitted operation continues. The queue and its short-lived operation results are cleared when the backend restarts.

Internal callers may identify an operation with a UUID, separate from any channel request ID. Reusing the UUID with the same intent waits for an unfinished operation or returns its known result; reusing it with a different intent is a conflict. The process retains up to 1024 completed results, excluding operations still in progress. Looking up a missing result never reruns the operation, and absence of a result does not prove that no effects occurred.

Note: by now Markdown vault mode will only show tasks that have the following strings that start with '- [ ]' and contain '[track:: (category)]', '[start:: (date in YYYY-MM-DD format)]' and '[due:: (date in YYYY-MM-DD format)]'. It is projected to add some configurability on these matters to ease up it's use.

#### Data files directory

It will ask you for a directory to save your data files, uses the current directory by default.

#### Telegram credentials

If a telegram mode is selected, it will ask for a telegram bot token, if you don't know how, please check the section `Getting Ready>Obtain your bot token` from this site: https://core.telegram.org/bots/tutorial.

It will also ask you for a telegram chat Id, you can get it by following this tutorial: https://www.wikihow.com/Know-Chat-ID-on-Telegram-on-Android

#### API credentials

If an API mode is selected, you will need to provide:
- **Server bind address** - The IP address or hostname for the server to bind to (default: 0.0.0.0)
- **Server port** - The port number for the server (default: 8080)
- **API prefix** - The resource API base path (`HTTP_API_PREFIX`, default: `/api/v1`; for example, `/manager/api/v1`)
- **Authentication token** - A secure token that clients must provide in the Authorization header
- **Chat ID** - The identifier used by the configured API interface (default: 1)

The resource API accepts a Bearer token in the `Authorization` header. Each response includes a generated `X-Request-ID`; problem responses repeat it as `requestId` and report the request's effects when known. HTTPS enforcement is not implemented in this backend version.

#### Markdown vault directory

If a Markdown vault mode is selected, the application will need a directory (and subdirectory) to scan markdown (.md) files to. 

> [!note]
> Several markdown editors like Logseq or Obsidian allow users to create templates that combined with this functionability, would create a consistent TODO-list for tasks with any given periodicity.

#### Finally

A file called `config.json` will be created with a basic set of task categories/contexts, you can modify this file to reconfigure your task manager or delete it so the application will prompt you again on the next start.

## Usage (Python 3.11)

run `python backend.py` in the backend folder

## Web Frontend (React + TypeScript)

The browser frontend in `frontend/` still uses the earlier command-style interface. The backend has retired the mutating GET routes, so the frontend has not yet been adapted to the current resource API and its task-changing actions will not work against this backend version.

### Frontend prerequisites

- Node.js 20+
- Backend configured in API mode (`APP_MODE` 5 or 6)

### Run frontend in development

```bash
cd frontend
npm install
npm run dev
```

### Run backend in API mode

Set `APP_MODE` in `config.json` to one of:
- `5` (JSON file + API)
- `6` (Obsidian + API)

Then start backend:

```bash
make run
```

Configure the backend endpoint for your installation.

Open `http://localhost:5173` and configure:
- **Backend URL** (default `/api`, proxied by Vite)
- **Bearer token** (from `HTTP_TOKEN` in your `config.json`)

The current frontend development proxy and client still issue GET requests to command paths. They need a resource-API client before they can be used with the backend described here. The frontend currently contains task lists, dashboards and legacy task actions, but the backend no longer accepts those mutating GET routes. Notification polling is unavailable until a persistent notification resource is provided.

### Build frontend

```bash
cd frontend
npm run build
```

### Frontend caveats

- The frontend has not migrated to HAL resources, typed operations or the current authentication and error contract.
- In API mode, `/export` is not implemented as a file download action.

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
    "TELEGRAM_CHAT_ID": "<Your telegram user id>"
}
```

##### API mode JSON example
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
    "APP_MODE": 5,
    "JSON_PATH": ".",
    "HTTP_URL": "0.0.0.0",
    "HTTP_PORT": "8080",
    "HTTP_API_PREFIX": "/api/v1",
    "HTTP_TOKEN": "<Your secure authentication token>",
    "HTTP_CHAT_ID": "1"
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

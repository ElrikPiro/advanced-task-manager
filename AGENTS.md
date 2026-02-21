# AGENTS.md instruction for coding agents

## Developing
- There is a Makefile at root that contains common utilities like creating a `.venv` or testing the application.
- Base python module is not at root, it is located at the `backend/` folder.
- Testing is based on `MagicMock` and the `unittest` module.
- Application entry point is at `backend/backend.py`.
- Use `git diff` to get additional context when starting a new task.
- Python version 3.11
- Import pattern: `from src.module import Class` (relative to backend/)
- Tests run from `backend/` directory: `cd backend && python -m unittest discover -s tests`
- Test files must end with `_test.py` (e.g., `TaskModel_test.py`)
- Uses `dependency-injector` library
- New services should be registered in `TelegramReportingServiceContainer.py`

## Requisites
- A task is not ended until the markdown files are updated, if applicable.
- A task is not completed until `make test` passes.
- When a test fails, get differences from `master`, evaluate and state the cause and present the user with the choice to fix the test or the code.

### Documentation Updates
When making changes, update applicable documentation:
- `README.md` - User-facing changes, new features, config options
- `ARCHITECTURE.md` - Structural changes, new components, architecture decisions
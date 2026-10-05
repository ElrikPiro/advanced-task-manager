.PHONY: install install-runtime install-test test package-linux-source run run-frontend

PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON = $(VENV)/bin/python

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

install: install-runtime

install-runtime: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --disable-pip-version-check --requirement requirements.lock

install-test: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pip install --disable-pip-version-check --requirement requirements-test.lock

test: install-test
	PYTHON="$(abspath $(VENV_PYTHON))" ./tools/bash/local-quality-checks.sh

package-linux-source:
	$(PYTHON) tools/build_linux_source.py

run: install-runtime
	$(VENV_PYTHON) backend/backend.py

run-frontend:
	npm --prefix frontend run dev

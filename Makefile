.PHONY: test .venv

RUN_IN_VENV = . .venv/bin/activate &&

.venv:
	python3 -m venv .venv
	$(RUN_IN_VENV) pip install -r requirements.txt

test: .venv
	$(RUN_IN_VENV) ./tools/bash/local-quality-checks.sh

run: .venv
	$(RUN_IN_VENV) python3 backend/backend.py

# Activity Imitator task runner (ADR 0002). Targets are offline unless noted.
# Entry point for agents: AGENTS.md. Paths are relative: the repo path has a space.
PY ?= .venv/bin/python
UNITTEST = $(PY) -m unittest discover -t . -s
CLOCK = date +%s%N

.DEFAULT_GOAL := help
.PHONY: help setup lint guard test-unit test-integration verify check ratchet-coverage \
        screenshots install-hooks install-launcher manual-cursor-test manual-keys-test

help: ## List targets
	@grep -E '^[a-z][a-z0-9_-]*:.*## ' Makefile | awk 'BEGIN {FS = ":.*## "} {printf "  %-20s %s\n", $$1, $$2}'

setup: ## Create .venv and install requirements.txt (needs network)
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

lint: ## Stdlib lint of every Python file
	@$(PY) tools/lint.py

guard: ## Block secrets, personal data and forbidden files in the working tree
	@$(PY) tools/guard.py --all

test-unit: ## Unit tests: core, GUI (offscreen), doc-sync, ratchets
	@$(UNITTEST) tests/unit

test-integration: ## Integration tests: worker threads, Qt event loop
	@$(UNITTEST) tests/integration

verify: ## Inner loop: lint + guard + unit tests (budget in AGENTS.md)
	@t0=$$($(CLOCK)); \
	$(PY) tools/lint.py && $(PY) tools/guard.py --all && $(UNITTEST) tests/unit && \
	echo "verify: OK in $$(( ($$($(CLOCK)) - t0) / 1000000 )) ms"

check: ## Exactly what CI runs: lint + guard + all tests under the coverage ratchet
	@t0=$$($(CLOCK)); \
	$(PY) tools/lint.py && $(PY) tools/guard.py --all && \
	$(PY) tools/coverage_run.py tests/unit tests/integration && \
	echo "check: OK in $$(( ($$($(CLOCK)) - t0) / 1000000 )) ms"

ratchet-coverage: ## Raise tools/coverage-threshold.txt to the measured floor (never lowers)
	@$(PY) tools/coverage_run.py --raise-threshold tests/unit tests/integration

screenshots: ## Render all GUI states offscreen to build/screenshots/
	@$(PY) tools/screenshots.py

install-hooks: ## Activate repo hooks (guard on commit and on commit message)
	git config core.hooksPath tools/hooks
	@echo "hooks: tools/hooks active"

install-launcher: ## Desktop launcher; DRY-RUN unless APPLY=1 (writes outside the repo)
	@$(PY) tools/install_launcher.py $(if $(APPLY),--apply,)

manual-cursor-test: ## Moves the REAL cursor; DRY-RUN unless CONFIRM=1 (owner watches)
	@$(PY) tools/manual_cursor_test.py $(if $(CONFIRM),--confirm,)

manual-keys-test: ## Toggles the REAL Caps Lock twice; DRY-RUN unless CONFIRM=1
	@$(PY) tools/manual_cursor_test.py --keys $(if $(CONFIRM),--confirm,)

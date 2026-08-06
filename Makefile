# Tools run from .venv, not through `uv run`: this package declares an entry point
# group that uv resolves against the whole environment, and a bare `uv run` can fail
# in a checkout where sibling eduTAP packages are not installed.
PYTHON := .venv/bin/python
VENV   := .venv

.DEFAULT_GOAL := help
.PHONY: help venv lint reformat test-local test-integration test-slow test-mutation run

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

venv: ## Create .venv and install the package with its dev extra
	test -d $(VENV) || uv venv
	uv pip install -U -e ".[dev]"

lint: venv ## Run ruff checks and the type checker
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m ty check src

reformat: venv ## Autoformat and autofix
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

test-local: venv ## Unit tests, no database needed
	$(PYTHON) -m pytest -v

test-integration: venv ## Integration tests against a PostgreSQL container
	$(PYTHON) -m pytest -m integration -v

test-slow: venv ## Tests that measure real elapsed time (seconds, not milliseconds)
	$(PYTHON) -m pytest -m slow -v

# Deliberately not a CI job. Roughly a third of the surviving mutants are rewritten
# string literals — an error message nobody asserts on — so a threshold would have to
# be raised on every legitimate wording change, and a threshold that gets raised is
# not a threshold. Run it when changing behaviour, and read the survivors.
test-mutation: venv ## Mutation testing: would any test notice if this line changed?
	# The whole tree, not just mutants/mutmut-stats.json: mutmut keys its verdicts on
	# the source it mutated, and adding a test to kill a survivor does not invalidate
	# them. Without this the second run finishes in 3 seconds instead of 47 and
	# reports the previous numbers unchanged while the survivors are already dead —
	# measured, and the reason this line is here rather than a note in the README.
	rm -rf mutants
	$(PYTHON) -m mutmut run
	$(PYTHON) -m mutmut results

run: venv ## Start the service against the compose environment
	$(PYTHON) -m uvicorn edutap.data_provider.api.app:create_app --factory --reload

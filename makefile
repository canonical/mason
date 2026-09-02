.SUFFIXES:

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)} /^[a-zA-Z_.\/-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: verify
verify: lint check-shared test  ## Run every check ci runs

.PHONY: test
test:  ## Test the skill scripts (uvx pytest, pyyaml pulled in on the fly)
	uvx --with pyyaml --with pytest pytest tests/scripts/

.PHONY: lint
lint:  ## Lint python (uvx ruff check)
	uvx ruff check scripts/ skills/ tests/scripts/

.PHONY: format
format:  ## Format python in place (uvx ruff format)
	uvx ruff format scripts/ skills/ tests/scripts/

.PHONY: sync-shared
sync-shared:  ## Copy _shared/ files into the skills that list them in shared.list
	python3 scripts/sync-shared.py

.PHONY: check-shared
check-shared:  ## Fail if any skill's shared/ copy is out of sync with _shared/
	python3 scripts/sync-shared.py --check

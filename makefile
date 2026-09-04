.SUFFIXES:

RUFF ?= ruff@0.16.5

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)} /^[a-zA-Z_.\/-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: verify
verify: lint check-shared test  ## Run every check ci runs

.PHONY: test
test:  ## Test the scripts and repo metadata (uvx pytest, pyyaml pulled in on the fly)
	uvx --with pyyaml --with pytest pytest tests/scripts/ tests/meta/

.PHONY: lint
lint:  ## Lint python (ruff, version pinned by RUFF)
	uvx $(RUFF) check scripts/ skills/ tests/scripts/ tests/meta/

.PHONY: format
format:  ## Format python in place (ruff, version pinned by RUFF)
	uvx $(RUFF) format scripts/ skills/ tests/scripts/ tests/meta/

.PHONY: sync-shared
sync-shared:  ## Copy _shared/ files into the skills that ask for them in .shared.yaml
	uv run --script scripts/sync-shared.py

.PHONY: check-shared
check-shared:  ## Fail if any skill's generated copy is out of sync with _shared/
	uv run --script scripts/sync-shared.py --check

.DEFAULT_GOAL := help
PY ?= python3
COMPOSE ?= docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

validate: ## Validate workflow JSON structure (connections, orphans, secrets)
	$(PY) tests/validate_workflows.py

test: ## Run the pytest suite
	$(PY) -m pytest -q tests

diagram: ## Regenerate docs/workflow.png from the workflow JSON
	$(PY) scripts/render_diagram.py

fmt: ## Pretty-print workflow JSON in place (stable key order not enforced)
	@for f in workflows/*.json; do $(PY) -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); open(p,'w').write(json.dumps(d,indent=2,ensure_ascii=False)+'\n')" $$f; done

up: ## Start self-hosted n8n + Postgres
	$(COMPOSE) up -d

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) down

logs: ## Tail n8n logs
	$(COMPOSE) logs -f n8n

import: ## Import all workflows into the running n8n container via CLI
	$(COMPOSE) exec n8n n8n import:workflow --separate --input=/data/workflows

export: ## Export all workflows from the running container to ./export
	mkdir -p export && $(COMPOSE) exec n8n n8n export:workflow --all --separate --output=/tmp/export && \
	docker cp $$($(COMPOSE) ps -q n8n):/tmp/export ./export

check: validate test diagram ## Everything CI runs

.PHONY: help validate test diagram fmt up down logs import export check

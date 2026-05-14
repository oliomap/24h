# Two targets, one terminal each. Never run both in the same terminal.
#
# Terminal A:   make backend
# Terminal B:   make frontend
#
# RAM: the frontend dev script caps Node at 1.5 GB (NODE_OPTIONS in
# frontend/package.json). Never run a headless browser in parallel with `make
# frontend` on this machine — that combination is what froze things last time.

SHELL := /bin/bash

# The system /usr/bin/node is v18 on this machine, which is too old for
# Next.js 16. Resolve nvm's Node 22 binary explicitly.
NODE22 := $(shell ls -d $$HOME/.nvm/versions/node/v22.* 2>/dev/null | tail -n 1)/bin

.PHONY: backend frontend reset stop check

backend:
	@echo "→ Starting FastAPI on http://127.0.0.1:8000"
	cd backend && env -u PYTHONPATH -u AMENT_PREFIX_PATH \
		.venv/bin/uvicorn api:app --port 8000 --reload

frontend:
	@if [ -z "$(NODE22)" ] || [ ! -x "$(NODE22)/node" ]; then \
		echo "ERROR: Node >=20 not found under ~/.nvm/versions/node/v22.*"; \
		echo "      install with: nvm install 22"; exit 1; \
	fi
	@echo "→ Starting Next.js on http://localhost:3000 (Node $$($(NODE22)/node -v))"
	@cd frontend && PATH="$(NODE22):$$PATH" npm run dev

check:
	@echo "Node on PATH: $$(which node) ($$(node -v 2>/dev/null || echo missing))"
	@echo "Resolved nvm v22 bin: $(NODE22)"
	@echo "Backend venv:        $$(test -x backend/.venv/bin/uvicorn && echo OK || echo MISSING)"
	@echo "Frontend node_modules: $$(test -d frontend/node_modules && echo OK || echo MISSING)"

reset:
	@curl -sS -X POST http://127.0.0.1:8000/api/reset && echo " — reset"

stop:
	@-pkill -f "uvicorn api:app" 2>/dev/null || true
	@-pkill -f "next dev" 2>/dev/null || true
	@echo "stopped"

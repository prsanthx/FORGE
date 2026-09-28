.PHONY: test backend frontend

test:
	cd backend && python -m pytest

backend:
	cd backend && python -m forge.cli serve

frontend:
	cd frontend && npm run dev

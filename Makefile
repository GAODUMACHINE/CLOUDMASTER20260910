pre:
	ruff check . && ruff format --check .
	pytest -q
.PHONY: test lint typecheck format install dry-run health

test:
	python3 -m pytest tests/ -v

lint:
	python3 -m ruff check hookline/

typecheck:
	python3 -m pyright hookline/

format:
	python3 -m ruff format hookline/

install:
	bash setup.sh --update

dry-run:
	echo '{"hook_event_name":"Stop","cwd":"/test/demo"}' | python3 -m hookline --dry-run

health:
	python3 -m hookline --health

.PHONY: test lint typecheck format install dry-run health

test:
	python3 -m pytest tests/ -v

lint:
	python3 -m ruff check notify/

typecheck:
	python3 -m pyright notify/

format:
	python3 -m ruff format notify/

install:
	bash setup.sh --update

dry-run:
	echo '{"hook_event_name":"Stop","cwd":"/test/demo"}' | python3 -m notify --dry-run

health:
	python3 -m notify --health

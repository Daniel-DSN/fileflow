.PHONY: help test demo init-demo plan apply report clean

PYTHON ?= python3
CLI = PYTHONPATH=src $(PYTHON) -m fileflow.cli
DIR ?= demo/demo_workspace

help:
	@echo "make test          run the offline test suite"
	@echo "make init-demo     recreate the seeded demo workspace in $(DIR)"
	@echo "make plan          dry-run plan for $(DIR)"
	@echo "make apply         execute the plan (requires APPLY=yes)"
	@echo "make report        write demo/report.csv"
	@echo "make demo          full captured demo sequence"

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

init-demo:
	rm -rf $(DIR)
	$(CLI) init-demo $(DIR)

plan:
	$(CLI) plan $(DIR) --rename

apply:
	@test "$(APPLY)" = "yes" || (echo "run 'make apply APPLY=yes' to confirm"; exit 1)
	$(CLI) apply $(DIR) --yes --rename

report:
	$(CLI) report $(DIR) -o demo/report.csv

demo: init-demo
	$(CLI) plan $(DIR) --rename
	$(CLI) apply $(DIR) --yes --rename
	$(CLI) report $(DIR) -o demo/report.csv

clean:
	rm -rf demo/demo_workspace demo/report.csv
	find . -name __pycache__ -type d -exec rm -rf {} +
	rm -rf .pytest_cache

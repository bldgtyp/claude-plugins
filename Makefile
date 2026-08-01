PYTHON ?= python3
MCP_CONTRACT ?= contract/phn-mcp.md

.PHONY: generate test check

generate:
	$(PYTHON) scripts/generate.py

test:
	$(PYTHON) -m unittest discover -s tests

check:
	$(PYTHON) scripts/generate.py --check
	$(PYTHON) scripts/check_public_hygiene.py
	$(PYTHON) -m compileall -q plugins scripts tests
	$(PYTHON) -m unittest discover -s tests
	$(PYTHON) scripts/check_contract.py "$(MCP_CONTRACT)"

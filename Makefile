PYTHON ?= python3
MCP_CONTRACT ?= contract/phn-mcp.md

.PHONY: generate install-codex test check

generate:
	$(PYTHON) scripts/generate.py

install-codex:
	$(PYTHON) scripts/install_codex.py

test:
	$(PYTHON) -m unittest discover -s tests

check:
	$(PYTHON) scripts/generate.py --check
	$(PYTHON) scripts/check_public_hygiene.py
	$(PYTHON) -m compileall -q plugins scripts tests
	$(PYTHON) -m unittest discover -s tests
	$(PYTHON) scripts/check_contract.py "$(MCP_CONTRACT)"

# BLDGTYP Claude Code plugins

Public marketplace for BLDGTYP agent tooling. The first plugin connects Claude
Code to PH-Navigator through its production MCP surface and supplies the
project-resolution, read, draft-write, and error-recovery workflow.

## Install for Claude Code

Requires Claude Code 2.1.203 or newer and Python 3.11 or newer.

```sh
claude plugin marketplace add bldgtyp/claude-plugins --scope user
claude plugin install bldgtyp@bldgtyp --scope user
```

Restart Claude Code or run `/reload-plugins`. The plugin provides:

- production MCP server `phn`;
- `/bldgtyp:phn` workflow guidance;
- `/bldgtyp:phn-login` browser-approved machine authorization; and
- `/bldgtyp:phn-status` read-only project status summary.

The credential bridge reads the path declared in
`plugins/bldgtyp/config/phn.json`. If the file is missing or the remote server
rejects an expired/revoked token, it opens the
PH-Navigator device-approval page and writes the replacement credential with
mode `0600`. It never places the token in plugin config, command arguments, or
the working project folder.

## Project markers

BLDGTYP project roots carry a `.phn.json` marker:

```json
{
  "phn_project_id": null,
  "phn_api": "https://api.ph-nav.com",
  "phn_web": "https://www.ph-nav.com"
}
```

The null id is intentional for new folders. The agent resolves it with
`list_projects`, asks the user if matching is ambiguous, and stamps the chosen
id. Generated thin `CLAUDE.md` and `AGENTS.md` templates live under
`templates/project-folder/`.

## Source and drift checks

`plugins/bldgtyp/config/phn.json` is the canonical machine-readable service,
device-flow, credential, and required-tool contract. `source/phn-workflow.md`
is the canonical agent workflow. One generator emits the Claude skill, the
Codex AGENTS section, and the project-folder templates:

```sh
python3 scripts/generate.py
python3 scripts/generate.py --check
python3 scripts/sync_contract.py /path/to/ph-navigator/context/mcp.md
python3 scripts/check_contract.py contract/phn-mcp.md
```

`contract/phn-mcp.md` is a vendored snapshot so public CI is deterministic and
does not need access to the PH-Navigator repository. Maintainers refresh it
with `sync_contract.py` whenever the upstream MCP contract changes. The drift
checker requires the configured workflow tools, recoverability values, device
protocol, credential shape, and draft-safety semantics in both artifacts.

`scripts/sync_project_folder.py <folder>` installs the generated thin files and
preserves an existing `phn_project_id`. The public-hygiene check rejects token
shapes, UUID-shaped project ids, client test identifiers, and developer home
paths from every tracked/untracked source file.

## Development

```sh
make generate
make check MCP_CONTRACT=/path/to/ph-navigator/context/mcp.md
claude plugin validate . --strict
claude --plugin-dir ./plugins/bldgtyp
```

The MCP bridge uses only the Python standard library. PH-Navigator's server is
stateless Streamable HTTP; the bridge translates newline-delimited stdio
JSON-RPC without adding a package-install or proxy dependency.

## Install for Codex

Requires Codex CLI and Python 3.11 or newer. From this checkout:

```sh
make install-codex
codex mcp get phn
```

The idempotent installer copies the same credential-aware bridge to
`~/.local/share/bldgtyp/phn-agent`, adds a managed `mcp_servers.phn` section to
`~/.codex/config.toml`, and adds the generated workflow section to
`~/.codex/AGENTS.md`. Existing content and file permissions are preserved; an
unmanaged server already named `phn` is rejected instead of overwritten.
Restart Codex after installing or updating.

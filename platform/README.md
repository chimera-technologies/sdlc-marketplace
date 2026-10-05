# Platform controls (managed settings)

`managed-settings.json` is the starting point for the "Platform controls"
layer in the architecture. IT or the platform team deploys it to every
engineer's machine; engineers cannot override it. It is not part of the
plugin and is not installed by it.

| OS | Path |
|---|---|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |

## What it sets

- **Bypass mode off** (`permissions.disableBypassPermissionsMode`).
- **Credential reads denied**: SSH, cloud CLI, kube, Docker, npm and netrc
  credentials, `.env` files and key files.
- **One approved marketplace** (`strictKnownMarketplaces`): users can only
  add this marketplace, so it is the only source of skills, agents and hooks.
- **OpenTelemetry export** for sessions, tool decisions and hook
  allow/block events. Replace the endpoint with your collector.

Before deploying, check the marketplace repo (`chimera-technologies/sdlc-marketplace`), replace the OTLP
endpoint, and confirm each key against the current Claude Code settings and
monitoring docs. Test on one machine first with `/status`.

## Still to add (confirm the exact format in the docs first)

These are in the architecture, but their exact key formats weren't verified
when this file was written, so they are left out rather than guessed:

- **Managed MCP allowlist** (`allowedMcpServers`): allow only the Atlassian
  server (`https://mcp.atlassian.com/v1/mcp`) plus anything platform approves.
- **OS-level sandbox with a network domain allowlist** (`sandbox`): allow
  your git host, package registries, the Anthropic API and Atlassian.
- **Minimum Claude Code version**.
- **Managed hooks only** (`allowManagedHooksOnly`): check whether it also
  disables hooks from the approved plugin. If it does, the plugin's
  headless write guard and intent validation stop running, so either leave
  it off or deploy those hooks as managed hooks instead.

## CI runners

CI already follows the same rules without this file. Tokens are short-lived
GitHub App tokens minted per job, no standing production credentials are
held, the Jira token is never passed to Claude, and `--allowedTools`,
`--strict-mcp-config` and the plugin's headless write guard limit what the
agent can touch.

# Friction Log — Submission Draft

Only real friction observed during development is included.

## 1. SDK / protocol-version clarity

**Task:** Choose a stable Python SDK configuration for an Alexa+ self-hosted MCP server using MCP 2025-11-25+ and Streamable HTTP.

**Expected:** One clear hackathon-specific recommendation showing the preferred Python SDK line and protocol/transport combination.

**Observed:** The hackathon requirements specify a minimum MCP protocol version, while MCP SDK documentation and examples evolve independently. It took cross-checking the hackathon rules, Alexa+ documentation, and SDK behavior to choose and test the v1 FastMCP line used for the final proof.

**Workaround:** Pin the tested SDK line, keep transport state separate from business state, and certify the final server using the official SDK plus MCP Inspector.

**Suggestion:** Provide a hackathon compatibility table with tested SDK versions, protocol versions, transports, and a minimal Alexa+-ready server.

## 2. Localhost proxy interference on a managed corporate PC

**Task:** Run the official MCP Streamable HTTP E2E proof locally at `127.0.0.1:8000/mcp`.

**Expected:** The local MCP client would connect directly to the locally running FastMCP server.

**Observed:** On a managed corporate PC, the client received `503 Service Unavailable` even though Uvicorn and the StreamableHTTP session manager had started successfully. The server log showed no corresponding POST request, indicating local traffic was being intercepted before it reached the MCP server.

**Workaround:** Re-run on a non-managed home network / PC and explicitly bypass proxies for `127.0.0.1,localhost`. The official MCP SDK E2E then passed.

**Suggestion:** Add a troubleshooting note for managed-device proxy policies and recommend `NO_PROXY=127.0.0.1,localhost` for local Inspector/client testing.

## 3. Compatibility harness vs. official SDK response envelope

**Task:** Validate the same tool behavior first with a local compatibility harness and later with the official MCP SDK.

**Expected:** Equivalent response envelopes.

**Observed:** The compatibility harness exposed structured results differently from the official FastMCP response shape in the tested SDK version. The business behavior was correct, but tests written too tightly against one envelope could create false-green confidence.

**Workaround:** Separate compatibility-harness evidence from official-SDK evidence, normalize result parsing where needed, and use MCP Inspector as the final manual proof surface.

**Suggestion:** Document response-shape examples for the current FastMCP server/client pair and emphasize which fields are stable protocol guarantees versus SDK presentation details.

## 4. Inspector version discoverability

**Task:** Visually certify tool discovery and calls using MCP Inspector.

**Observed:** A locally invoked Inspector displayed a deprecation notice for Inspector v1 and directed the developer to the latest package. The older Inspector still connected successfully, but the version transition added uncertainty during a time-sensitive proof step.

**Suggestion:** In hackathon resources, link directly to the current Inspector command and show the exact Streamable HTTP connection flow.


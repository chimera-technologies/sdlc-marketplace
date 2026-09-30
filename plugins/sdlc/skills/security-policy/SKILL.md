---
name: security-policy
description: Security and data-handling policy for every product repo. Use
  whenever writing or reviewing a spec, design, implementation plan, code
  change or PR that touches authentication, authorization, personal or
  regulated data (PII, claims, health, payment), secrets, external input,
  logging, third-party services, dependencies or AI/LLM features. Also use
  when the Design stage asks you to make a spec conform to security
  policies, or when a reviewer asks whether something is allowed.
---

# Security and data-handling policy

<!-- DRAFT BASELINE. The policy owner must replace or sign off on these rules
     before this skill is relied on. Changes need their approval via
     CODEOWNERS. Anything that must ALWAYS hold should also get a hook or CI
     check; this skill is advisory. -->

- **Policy owner:** the `security_owner` in the project's
  `.sdlc/owners.yaml` (falls back to `default.tech_lead`): the named
  approver for changes and for every exception
- **Version:** 0.1 (draft), last reviewed: not yet

## How to apply it

- **Writing a spec or design:** add a `## Security considerations` section.
  For each rule below that applies, give its ID and say how the design
  satisfies it. Say "Not applicable" only with a one-line reason.
- **When a rule cannot be met**, or two policies conflict: do not quietly
  work around it. List it under the spec's areas of concern with the rule
  ID, what conflicts, the options, and "Decision needed from: policy
  owner". Set the spec's risk to `high`.
- **Reviewing code or a PR:** cite the rule ID for each finding (for
  example "SEC-2.3: claim number written to the access log").
- **Needs security review** (risk `high`, tech lead plus policy owner):
  anything marked *(review)* below.

## Rules

**SEC-1 Authentication and authorization**
1. Every endpoint and job uses the existing identity provider. No new
   login, token or session mechanism *(review)*.
2. Authorization is enforced on the server for each resource (a user can
   only reach their own records), never only in the UI.
3. Service-to-service calls use short-lived credentials scoped to the one
   service they need.

**SEC-2 Personal and regulated data**
1. Name every personal or regulated field a change reads, stores or sends.
   Collect only what the outcome needs.
2. New storage of, or a new flow for, personal or regulated data needs
   review *(review)*.
3. Personal data never appears in logs, URLs, analytics events, error
   messages or test fixtures. Use IDs or masked values.
4. Encrypted in transit (TLS 1.2+) and at rest. Retention follows the data
   retention schedule. Say which period applies.

**SEC-3 Secrets**
1. No secrets in code, config files, commit history, logs or prompts.
2. Secrets come from the platform secret manager at runtime, with the
   shortest practical lifetime.

**SEC-4 Untrusted input**
1. Validate all input at the trust boundary: type, length, format and
   allowed values.
2. Use parameterized queries and the framework's output encoding. Never
   build SQL, shell commands or HTML by joining strings.
3. File uploads are type-checked and size-limited, and never executed or
   served from the upload location.

**SEC-5 Dependencies and supply chain**
1. New dependencies come from the approved registries, are pinned, and
   have no known critical or high vulnerabilities.
2. A new dependency that handles auth, crypto or parsing of untrusted data
   needs review *(review)*.

**SEC-6 Logging and audit**
1. Log security-relevant events (sign-in, permission change, access to
   personal data, admin actions) with the actor, action, target ID and
   time, and without sensitive values.
2. Audit logs cannot be edited or deleted by the application.

**SEC-7 Third parties**
1. Sending data to a new external service needs a completed vendor and
   data-processing review *(review)*.

**SEC-8 AI and LLM features**
1. Customer or personal data is sent only to approved model providers,
   under the approved agreement *(review)*.
2. Model input from users, tickets, documents or web content is untrusted
   (see SEC-4). Model output never runs as code or commands without a
   deterministic check or a human approval.
3. An agent never holds standing production credentials, and the agent
   that wrote a change never approves it.

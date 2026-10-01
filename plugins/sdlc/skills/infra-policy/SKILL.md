---
name: infra-policy
description: Infrastructure and delivery policy for every product repo, for
  any cloud (AWS, Azure, GCP) and any tool (Terraform, Docker, Kubernetes,
  Helm, CI/CD). Use whenever writing or reviewing a spec, plan, code change
  or PR that adds or changes infrastructure as code, cloud resources,
  networking, identity and access, container images, cluster manifests, or
  the deploy pipeline. Applied with sdlc:security-policy, not instead of it.
---

# Infrastructure and delivery policy

<!-- DRAFT BASELINE. The policy owner must replace or sign off on these rules
     before this skill is relied on. Changes need their approval via
     CODEOWNERS. Rules that must ALWAYS hold should also be a check in the
     project's test_command (tflint, checkov, trivy, kubeconform); this skill
     is advisory. -->

- **Policy owner:** the `security_owner` in the project's `.sdlc/owners.yaml`
  (falls back to `default.tech_lead`)
- **Version:** 0.1 (draft), last reviewed: not yet

## How to apply it

- **The cloud and the tools are the architect's decision** in the spec's
  Technology and architecture section; these rules hold whichever they pick.
  Use the cloud's own name for each control (security group or NSG or
  firewall rule; IAM role or managed identity or service account).
- **Writing a spec:** in Security considerations, give each INF rule that
  applies and how the design meets it; "Not applicable" needs a reason.
- **Writing or reviewing a plan or PR:** cite the rule ID for each finding
  (for example "INF-2.1: ingress 0.0.0.0/0 on port 22"). In review-plan and
  review-story, breaking a rule is at least `high`; a *(review)* item done
  without the policy owner is `critical`.
- **Risk:** any change under INF-1, INF-2, INF-5 or INF-7 makes the intent
  and spec risk `high` (tech lead approval).

## Rules

**INF-1 Identity and access**
1. Least privilege: every role, identity or service account gets only the
   actions and resources it needs. No wildcard actions or resources on
   write permissions; no owner, admin or contributor roles for workloads
   *(review)*.
2. CI/CD and workloads authenticate with short-lived federated credentials
   (OIDC, workload identity, managed identity). No long-lived access keys
   or service account key files.
3. The production plan identity is read-only; only the production deploy,
   behind the environment's approvers, can change production.

**INF-2 Network exposure**
1. No ingress from anywhere (0.0.0.0/0, ::/0) except to a public load
   balancer or CDN on 80/443. Admin ports (22, 3389, databases, cluster
   APIs) are never public *(review)*.
2. Data stores and internal services live in private networks or subnets
   with private endpoints; public endpoints are off.
3. TLS everywhere (1.2+); HTTP only redirects to HTTPS.

**INF-3 Data at rest**
1. Storage, databases, disks, queues and backups are encrypted at rest.
2. Object storage blocks public access; nothing is public-read unless the
   spec says why *(review)*.
3. Production data stores have backups with a tested restore, and
   deletion protection.

**INF-4 State, secrets and configuration**
1. IaC state lives in a remote backend with locking and encryption, and
   access limited to the deploy identities; never in the repo.
2. No secrets in IaC variables, tfvars, manifests, Helm values or images.
   They come from the cloud's secret manager at runtime (SEC-3).
3. Every environment is described by code (var files per environment);
   no manual changes. Drift found by a plan is fixed in code.

**INF-5 Change safety**
1. Anything a plan would destroy or replace is named in the plan PR or
   release with why, and applied only by a person re-running the release
   with `allow_destroy` after reading the plan *(review)*.
2. Production applies exactly the plan its approvers saw (the release
   workflow does this).
3. A change to a data store, network or identity has a rollback note in
   the plan's Risks and rollback, and is applied to staging first.

**INF-6 Containers and images**
1. Images are built from pinned, minimal base images (by digest or exact
   tag, never `:latest`), run as a non-root user, and are scanned with no
   critical or high vulnerabilities (SEC-5).
2. Images come from the project's own registry; no pulling from unknown
   public registries in production.

**INF-7 Kubernetes and orchestration**
1. Workloads set resource requests and limits, liveness and readiness
   probes, `runAsNonRoot`, a read-only root filesystem where possible, and
   no privileged containers, host network or host path mounts *(review)*.
2. Each workload has its own service account with only the permissions it
   needs; network policies deny by default.
3. Manifests and charts pin image versions and pass schema validation
   (kubeconform or helm lint) in the project's tests.

**INF-8 Pipeline**
1. The deploy pipeline is the only path to production; humans do not hold
   standing production write access.
2. Every deploy is traceable to a release record, a commit and an approval
   (the release workflow records this).

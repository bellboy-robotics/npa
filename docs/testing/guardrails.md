# Repo-Resident Guardrails

This repository has additive no-GPU guardrails for PRs:

- `confidentiality scan`: scans the PR diff and tracked tree with regexes sourced from the required `CUSTOMER_DENYLIST` GitHub Actions secret and, when configured, the supplemental `INFRA_DENYLIST` secret. Local operator runs may provide the same regexes through `${PATTERN_ENV}_FILE` or `~/.config/npa/<lowercase-pattern-env>.regex`. The workflow prints only redacted file locations and fails closed when the required customer source is absent.
- `harness guardrails`: runs static three-tier workbench contracts, pytest collection protection, GPU-skip lint, and SkyPilot teardown lint.

The `bellboy-robotics/npa` fork has no custom customer denylist. Its PR and main-push
checks always enforce the built-in Nebius infrastructure rules on added lines,
matching the local pre-PR scan. Gitleaks also remains required. When configured,
`CUSTOMER_DENYLIST` adds the full-tree and diff customer scan; `INFRA_DENYLIST`
adds the operator-private scan. Other repositories still require the customer
policy. A missing or invalid Git baseline fails the fork's scan. The public
rules are intentionally diff-scoped: the existing tree includes synthetic
scanner fixtures that match those rules.

Recommended branch-protection policy is an admin decision. The confidentiality scan and harness guardrails are designed to be merge-blocking checks; the local registry check is informational until it can run from an environment with registry reachability.

Operator-private denylist files must stay outside the repository. For example,
`CUSTOMER_DENYLIST` falls back to `~/.config/npa/customer-denylist.regex` for
local scans when the environment variable is not set.

## Public Image Reachability Check

Registry reachability is environment-dependent, so anonymous image existence
checks stay out of GitHub CI and can be run from a host with internet access:

```bash
npa/.venv/bin/python -m npa.deploy.publish_public \
  --target ghcr.io/nebius/nebius-physical-ai --verify-accepted-releases
```

BYOF workflow placeholders are intentionally excluded from the supported public
release inventory and require an explicitly selected operator registry.

## Proven-Run Drift

The optional YAML-to-proven-run drift guard needs a committed canonical proven-run manifest before it can compare drift. Until that manifest exists, this remains a documented `SEAM` rather than a GitHub CI gate.

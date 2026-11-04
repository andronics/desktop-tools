# Security

## Threat model

<!-- guidance: what this protects, from whom, and what is out of scope. What's exposed (ports, endpoints), who should be able to reach it, what it trusts (headers, upstreams, input files), and what an attacker gains if it is compromised. -->

## Secrets

- Give each secret through `DESKTOP_TOOLS_<KEY>_FILE`, a mounted file. A secret setting is also read from its plain variable and the config file, like any setting, so keep it out of both: `docker inspect` and `ps` show variables. See [In-Depth Configuration](In-Depth-Configuration#secrets).
- Values are never logged. Logs and `desktop-tools config` show where a value came from, never the value itself.
- CI scans every commit with gitleaks, and secrets in history fail the build.

<!-- guidance: list each secret, what it grants, and how to rotate it. -->

## Hardening

- **Supply chain:** dependencies are pinned in the lock file and updated weekly by Dependabot. GitHub Actions are pinned to commit SHAs.
- **Dependency auto-merge:** Dependabot patch updates get auto-merge queued by `dependabot-automerge.yml`: they still need a code owner's approval, then merge once CI passes.

<!-- guidance: input validation, authentication and authorisation, rate limiting: what this project does and where. -->

## Reporting a vulnerability

Report privately through [GitHub security advisories](https://github.com/andronics/desktop-tools/security/advisories/new), never in a public issue.

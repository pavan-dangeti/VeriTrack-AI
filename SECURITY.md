# Security policy

VeriTrack is a personal project that runs only on synthetic data. Security reports are still welcome and
taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 3.0.x | yes |
| < 3.0 | no |

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue:

1. Open the repository's **Security** tab and choose **Report a vulnerability**
   ([direct link](https://github.com/pavan-dangeti/VeriTrack-AI/security/advisories/new)).
2. Describe the problem, the affected version or commit, and the steps to reproduce it.

I'll acknowledge the report, keep you informed while it's investigated, and credit you in the advisory
unless you'd rather not be named. Please give me a reasonable chance to fix the problem before you disclose it.

## Scope

In scope: this repository's code, its CI workflows, and the configuration it ships (Dockerfile, Render
blueprints, `vercel.json`).

Out of scope: the hosted demo's availability (it runs on free plans and sleeps when idle), findings that need
an already compromised database or server, and reports from automated scanners without a demonstrated impact.

## What the design protects against

[docs/threat-model.md](docs/threat-model.md) describes the assets, the attackers considered, each defence
with the test that proves it, and the known gaps (for example, the audit chain cannot detect a fake entry
appended at the end). A report about something the threat model already lists as a gap is still welcome if
it shows a practical attack.

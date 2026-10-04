# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

Security of `cmd-vault` is taken seriously. If you discover a security vulnerability, please report it responsibly rather than opening a public issue.

### Disclosure Process

1. Email your report to `modus.labs.znz@gmail.com` or submit a private security advisory on GitHub.
2. Include a detailed description of the vulnerability, steps to reproduce, and any potential impact.
3. We will acknowledge receipt within 48 hours and work on a security fix promptly.

### Security Best Practices for Users

- Avoid including plain-text API keys, passwords, or secrets directly in CLI command lines recorded into `cmd-vault`.
- Restrict permissions on `~/.cmd_vault/` directory (`chmod 700 ~/.cmd_vault`).

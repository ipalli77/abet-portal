# Security and university deployment

## Reporting a vulnerability

Do not place vulnerability details in public issue trackers. Operators should publish a monitored security contact and response SLA before external launch. Until that contact exists, this repository is suitable only for controlled pilots.

## Required production controls

- Set `ABET_ENV=production`, a unique high-entropy `ABET_SECRET_KEY`, and a separate `ABET_SETUP_TOKEN` through a secrets manager. Rotate the setup token after the owner workspace is claimed; the production startup policy still requires a value even though `/setup` becomes unavailable once an owner exists.
- Serve only through TLS and enable HSTS at the reverse proxy after confirming HTTPS coverage.
- Put the database and evidence directory on encrypted, access-controlled durable storage.
- Back up the database and uploads as one recovery unit; test restoration on a schedule.
- Centralize application and infrastructure logs without recording passwords, session cookies, or student work contents.
- Run dependency, container, static-code, and dynamic security scans in CI and before each release.
- Obtain an independent penetration test before storing real student evidence.
- Establish retention, legal-hold, export, and deletion rules with each customer. The application does not decide institutional FERPA policy.
- Integrate institutional SSO (SAML or OIDC) before a broad university rollout; local passwords are intended for pilots and controlled deployments.
- Move evidence files to managed object storage with malware scanning for a multi-institution hosted service.

## Data classification

Assessment narratives and aggregate rubric counts may be education records depending on institutional practice. Uploaded student work can contain directly identifying information. Programs should collect the minimum necessary data and avoid names in assessment narratives. Access must be reviewed at least each term.

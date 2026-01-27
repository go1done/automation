🧩 Story 1: Repository Inventory & Classification

Story title
📘 Create comprehensive repository inventory and classification

Description
Create a complete inventory of all repositories currently hosted in the existing source control organisation. Classify repositories to support future migration planning and risk assessment.

Scope includes

Active vs archived repositories

Production vs non-production usage

Ownership (team / individual)

Criticality (business-critical / internal / experimental)

Out of scope

Any repository migration or modification

Acceptance Criteria

 All repositories are listed in a central inventory (doc or sheet)

 Each repository has an identified owner

 Repositories are tagged with usage and criticality

 Inventory reviewed with platform / leadership representative

Notes (optional, but useful)

This inventory is platform-agnostic and required regardless of final migration path.

🧩 Story 2: Dependency Mapping (CI/CD, Secrets, Webhooks)

Story title
🔗 Map repository dependencies and external integrations

Description
Identify and document dependencies for each repository that may be impacted by a source control platform change.

Dependencies to capture

CI/CD systems (e.g. pipelines, runners, build triggers)

Secrets management integrations

Webhooks (deployments, notifications, automation)

External tools relying on repo metadata or APIs

Acceptance Criteria

 Dependency mapping completed for all production and critical repos

 CI/CD integrations documented per repo

 Secrets and webhook dependencies identified

 Risks flagged where integrations are platform-specific

Why this matters

Enables accurate effort estimation and avoids service disruption during any future migration.

🧩 Story 3: Access Model & Permissions Documentation

Story title
🔐 Document current access model and permission structure

Description
Document how access and permissions are currently managed across repositories, teams, and automation accounts.

Includes

Human access (admins, maintainers, contributors)

Service accounts / bots

Team-based vs individual permissions

Inheritance patterns

Acceptance Criteria

 Current access model documented clearly

 High-risk permissions identified (e.g. shared admin access)

 Gaps or inconsistencies noted

 Document reviewed with security or platform stakeholders

Explicitly excludes

Permission changes

Access revocation

🧩 Story 4: Compliance & Policy Gap Analysis

Story title
📋 Identify compliance and policy gaps in current source control setup

Description
Assess the current source control configuration against organisational security, compliance, and governance expectations.

Areas to review

Branch protection policies

Required reviews / approvals

Audit logging

Repository visibility

Security scanning / checks

Acceptance Criteria

 Current policies documented

 Gaps identified relative to organisational standards

 Risks prioritised (high / medium / low)

 Findings shared with platform / security stakeholders

Important note

This story identifies gaps only; remediation is intentionally out of scope until platform decisions are finalised.

🧩 Story 5: Migration Automation Design (No Execution)

Story title
⚙️ Design migration automation and tooling approach (no execution)

Description
Design a reusable, automated approach for repository migration that can be adapted to the final target platform (GitHub org or Bitbucket).

Includes

High-level migration flow

Tooling options (scripts, APIs, vendor tools)

Dry-run / validation approach

Rollback and failure handling strategy

Excludes

Running migrations

Creating target organisations

Modifying live repositories

Acceptance Criteria

 Migration approach documented at a design level

 Platform-specific assumptions clearly marked

 Risks and limitations documented

 Ready to execute once platform decision is confirmed

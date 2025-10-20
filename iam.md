
1. Centralized Module Structure and Creation
The core of consolidation is creating a single, authoritative source for each common IAM resource. This source is a Terraform Module hosted in a central Git repository (like an AFT CodeCommit repo).

📝 Example Module: iam-standard-role
You would create a module that defines a standard set of IAM Roles, Policies, or Policy Attachments.

Repository Structure (e.g., in an AFT-managed infrastructure-as-code repository):

iam-repo/
├── modules/
│   ├── standard-roles/
│   │   ├── main.tf           # Defines the IAM role and standard attachments
│   │   ├── variables.tf      # Role name, principal, optional tags
│   │   └── outputs.tf        # Outputs the Role ARN
│   └── standard-policies/
│       ├── main.tf           # Defines the Customer Managed Policy
│       ├── variables.tf
│       └── outputs.tf
└── versions.tf               # Defines the provider and Terraform version constraints
modules/standard-policies/main.tf (The "Golden" Policy)

Terraform

# This is the single definition of the policy, used everywhere.
resource "aws_iam_policy" "standard_s3_read" {
  name        = var.policy_name
  description = "Standard ReadOnly S3 access for common workloads."
  policy      = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::*"]
      },
    ]
  })
}
2. Preventing Duplication via Module Calls
Instead of developers writing the aws_iam_policy resource block repeatedly across accounts (which leads to duplicates), they call your central module.

This module can be called from AFT's aft-global-customizations (for resources needed in all accounts) or aft-account-customizations (for account-specific resources).

📦 Enforcing the Module Call
In an AFT account customization, the code would look like this:

Terraform

# aft-account-customizations/<account_id>/main.tf

# 1. Deploy the "Golden" Policy (best done in a global customization 
#    or a central account, and then the ARN is passed to all accounts)
# If you deploy it once, you can pass the ARN around.
# For simplicity, if a policy is needed in every account, you might call it once per account.
module "standard_policy" {
  source = "git::ssh://git@<your_codecommit_repo_path>/iam-repo//modules/standard-policies?ref=v1.0.0"
  policy_name = "WorkloadStandardS3ReadOnly"
}

# 2. Use the Policy ARN to create the Role and Attach the Policy
resource "aws_iam_role" "application_role" {
  name = "AppRole-${var.account_id}"
  # ... other configuration
}

resource "aws_iam_role_policy_attachment" "s3_read_attach" {
  role       = aws_iam_role.application_role.name
  # This attachment ensures all roles use the same policy document
  policy_arn = module.standard_policy.policy_arn
}
Result: Every account creates a policy with the exact same content, but more importantly, every team is forced to use the common, vetted IAM structure defined in the single source code block within the module.

3. Versioning for Control and Rollout
Versioning is critical for managing changes to your "golden" IAM policies and roles. You use Git tags on your central IAM repository to define module versions.

A. Tagging Your Module (CodeCommit/Git)
When you make a change to the standard-policies module, you must tag it.

Action	Git Command
Initial Release	git tag v1.0.0
Bug Fix/Minor Change	git tag v1.0.1
Major Security/Permission Change	git tag v2.0.0

Export to Sheets

B. Consuming the Version in AFT
The AFT customization pipeline consumes the module by referencing the tag:

Terraform

module "standard_policy" {
  source = "git::ssh://git@<your_repo_path>/iam-repo//modules/standard-policies?ref=v1.0.0" 👈 FIXED VERSION
  # ...
}
C. The Control Benefits
Staggered Rollout: You can update the module version in one OU's customizations (dev OU uses v2.0.0) before rolling it out to another (prod OU stays on v1.0.0). This is a fundamental part of controlled deployment.

Immutability: By pinning to a specific version (ref=v1.0.0), you ensure that a breaking change introduced later (e.g., in v1.0.1) doesn't unexpectedly break existing accounts.

Auditing and Governance: The version tag acts as a clear audit trail. You know exactly what policy document is active in which account at all times.

4. Using PaC (Rego/OPA) for Enforcement
While modules prevent duplicates in new deployments, you can use Policy-as-Code (PaC) in your AFT pipeline to detect drift or to enforce the use of your standard policies.

You would write a Rego policy that checks the Terraform plan output for two things:

Module Enforcement: Deny the creation of any aws_iam_policy or aws_iam_role resource that is not sourced from your approved central module.

Duplicate Detection: Deny the creation of any new IAM resource if a resource with the same policy document already exists in the configuration set.

Conceptual Rego Rule for Module Enforcement:

Code snippet

package iam.governance.enforcement

deny[msg] {
    # Find any IAM Policy resource in the Terraform plan
    resource := input.planned_values.root_module.resources[_]
    resource.type == "aws_iam_policy"

    # Check the source of the module. This is highly dependent on how your
    # IaC tool exposes module source in the plan.
    # If the resource is NOT from the approved module source:
    not startswith(resource.source, "module.standard_policy")
    
    msg := sprintf("IAM Policy '%s' is being created outside of the approved standard module. Please use the 'standard-policies' module.", [resource.address])
}

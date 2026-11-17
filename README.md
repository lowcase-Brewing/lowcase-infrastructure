# lowcase infrastructure

Terraform scaffolding for the Grain Bill Calculator proof of concept in the
**lowcase Brewing** AWS project (`697731339425`), selected Region `us-east-2`.
The isolated recipe API POC is defined in `terraform/`; application hosting is not
included yet. See [the POC runbook](poc/README.md) for Cognito sign-in, recipe save/load,
two-user isolation testing and cleanup.

## Remote state

The state file lives in an S3 bucket. Native S3 locking uses a separate `.tflock`
object to prevent simultaneous Terraform writes; no DynamoDB table is needed.
[DynamoDB locking is deprecated by Terraform](https://developer.hashicorp.com/terraform/language/backend/s3).

| Configuration | Purpose | State location |
| --- | --- | --- |
| `terraform/bootstrap/` | Creates and protects the shared state bucket | Local initially, then `bootstrap/terraform.tfstate` in S3 |
| `terraform/` | Grain Bill Calculator POC infrastructure | `grain-bill-calculator/poc/terraform.tfstate` in S3 |

Both roots use bucket `lowcase-terraform-state-697731339425-us-east-2` and reject
credentials for any other AWS project. Backend settings cannot reference Terraform
resources, so the bucket must exist before the application backend is initialized.

The bootstrap module enables versioning, SSE-S3 encryption, Block Public Access,
disabled ACLs, and a policy denying HTTP requests from non-service principals.
`prevent_destroy` blocks bucket replacement or destruction while that resource block
remains in configuration. Keep the state bucket when tearing down the POC.

## Prerequisites

- Terraform **1.15 or later**, below 2.0, for native `aws login` authentication in
  the S3 backend. Native S3 locking alone only requires 1.10. This repository pins
  **1.17.2** in `.terraform-version` for version managers such as `tenv`.
  See the [official install page](https://developer.hashicorp.com/terraform/install)
  and [Terraform 1.15 release notes](https://github.com/hashicorp/terraform/blob/v1.15.0/CHANGELOG.md).
- AWS CLI and the existing authenticated `lowcase` profile. If its session expires,
  renew it through browser-based AWS login.
- Confirm the selected Region in **AWS Settings > View all projects > lowcase Brewing >
  Overview > Additional Info > Region** before applying.

Run the following commands from the repository root. Select the profile for both
the provider and the backend without putting credentials in configuration:

```sh
export AWS_PROFILE=lowcase
export AWS_REGION=us-east-2
```

If you previously exported temporary access keys into the terminal, remove those
overrides so Terraform can use and refresh the `lowcase` login session:

```sh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
terraform version
```

The version should be 1.17.2 with the repository pin, or at least 1.15 with another
installation. An `ExpiredToken` error during backend initialization can come from
expired environment credentials even while the named login profile still works.
If the profile's overall login session has expired, renew it through browser-based
AWS login before retrying. Keep local bootstrap state and its backup until migration
has succeeded; authentication failures do not require recreating the bucket.

## 1. Bootstrap the bucket

The first bootstrap run intentionally uses local state: the bucket cannot store
its own state before it exists. Keep this local state file safe until migration
finishes. It is excluded from Git.

```sh
terraform -chdir=terraform/bootstrap init
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform/bootstrap plan -out=bootstrap.tfplan
```

Review the plan. It should create only the state bucket and its five configuration
resources, all in `us-east-2`. When ready to create them:

```sh
terraform -chdir=terraform/bootstrap apply bootstrap.tfplan
```

If the bucket already exists, stop and confirm its ownership and management rather
than trying to recreate it. A bucket name containing a project ID does not prove
ownership; Terraform also checks the authenticated project ID.

## 2. Migrate bootstrap state into S3

Only after the bootstrap apply succeeds, enable its remote backend:

```sh
cp terraform/bootstrap/backend.tf.example terraform/bootstrap/backend.tf
terraform -chdir=terraform/bootstrap init -migrate-state
```

Approve Terraform's state-copy prompt. Confirm the migrated resources are visible:

```sh
terraform -chdir=terraform/bootstrap state list
terraform -chdir=terraform/bootstrap plan
```

Keep the generated `terraform/bootstrap/backend.tf` in Git once migration succeeds.
It contains no secrets. Until migration is verified, retain the local state backup;
never commit local state or saved plans.

## 3. Initialize the application infrastructure

```sh
terraform -chdir=terraform init
terraform -chdir=terraform validate
terraform -chdir=terraform plan
```

The application root defines the isolated Cognito, API Gateway, Lambda and DynamoDB
recipe POC. Its plan should add only POC resources, never replace the bootstrap
bucket. Its backend uses a different state key from the bootstrap module.
Follow [the POC runbook](poc/README.md) before applying. `s3.tf` remains a placeholder
for later application hosting; the local browser harness requires no hosting bucket.

## Validation without creating infrastructure

Before the state bucket exists, initialize providers without contacting the remote
backend, then validate each root:

```sh
terraform fmt -check -recursive terraform
terraform -chdir=terraform/bootstrap init -backend=false
terraform -chdir=terraform/bootstrap validate
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
```

These checks validate formatting and provider schemas, not live permissions or bucket
availability. Commit the generated `.terraform.lock.hcl` files for both roots.

## Costs, access, and recovery

S3 charges for stored state versions and requests, including lock operations.
SSE-S3 avoids adding a customer-managed KMS key and its associated costs. No fixed
monthly estimate is assumed; see [S3 pricing](https://aws.amazon.com/s3/pricing/) and
track the project's credits and plan in **AWS Settings > Billing**. Versioning retains
complete prior state objects, so stored history grows with subsequent writes.

Keep state access limited to the people and automation managing infrastructure.
When adding a dedicated Terraform role, scope permissions to this bucket and the
required state prefixes: `s3:ListBucket` on the bucket, `s3:GetObject`/`s3:PutObject`
on state objects, and `s3:GetObject`/`s3:PutObject`/`s3:DeleteObject` on their `.tflock`
objects. See [Terraform's backend permissions](https://developer.hashicorp.com/terraform/language/backend/s3#permissions-required).

Before shared or production use, enable S3 server access logging, CloudTrail S3 data
events, and CloudWatch request metrics for auditing and monitoring. These features
and their encrypted log destinations should be scoped separately, with their added
costs reviewed. See [S3 monitoring guidance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/monitoring-overview.html).

Do not store application assets in the Terraform state bucket. Preserve it and its
state history when cleaning up POC hosting resources.

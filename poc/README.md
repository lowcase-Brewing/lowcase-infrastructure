# Isolated AWS recipe POC

This stack tests one path: **Cognito sign-in -> save a recipe -> load it again**.
It uses new app users and a new DynamoDB table in lowcase Brewing (`697731339425`),
selected Region `us-east-2`. The calculator repository, Lovable, Supabase, existing
users, and production DNS are not modified by this configuration.

The Terraform root is `terraform/`, using the existing
`grain-bill-calculator/poc/terraform.tfstate` backend key. `terraform/bootstrap/`
continues to manage only the shared state bucket, under its own key.

## What the stack defines

| Component | Purpose |
| --- | --- |
| Cognito user pool, public app client, classic hosted UI domain | Administrator-created test users; authorization code + PKCE; public signup disabled |
| Cognito resource server | Separate `recipes.read` and `recipes.write` access-token scopes |
| API Gateway HTTP API | Two JWT-protected routes; CORS restricted to the harness origin; request throttling |
| Python Lambda and execution role | Validate requests, derive ownership from the verified token, and read/write recipe items |
| DynamoDB on-demand table | Composite key `owner_id` + `recipe_id`; encryption and point-in-time recovery enabled |
| Two CloudWatch log groups | Seven-day retention; request metadata rather than tokens or recipe bodies |

The browser never gets AWS credentials. No identity pool or browser DynamoDB access
is required. API Gateway validates the Cognito token's signature, issuer, client,
expiry and route scope. Lambda also checks `token_use=access`, the client, scope,
and `sub`, and always builds the DynamoDB key from that verified subject.

Test users and passwords are intentionally absent from Terraform. The isolated
pool has MFA disabled to keep the first POC small; this is a non-production choice.
The public client has no secret. Access tokens last 15 minutes. The harness keeps
its access token only in memory, keeps the temporary PKCE transaction in
`sessionStorage`, and discards ID and refresh tokens. Refreshing the page requires
signing in again; it does not remove the saved recipe.

Refresh-token rotation is explicitly disabled for compatibility with the Lite pool.
Token revocation remains enabled. The harness never retains or uses a refresh token;
revisit feature-tier support and rotation when adding production session refresh.

## 1. Validate and review the Terraform plan

From the repository root, use Terraform 1.17.2 and the authenticated `lowcase` profile.
Clear temporary credentials in this terminal so they cannot override the profile:

```sh
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
export AWS_PROFILE=lowcase
export AWS_REGION=us-east-2
terraform version
terraform -chdir=terraform init
terraform fmt -check -recursive terraform
terraform -chdir=terraform validate
terraform -chdir=terraform plan -out=poc.tfplan
terraform -chdir=terraform show poc.tfplan
```

Expect only POC additions, with no bootstrap bucket changes or Supabase resources.
The plan file contains infrastructure details; Git ignores it. Confirm the selected
Region in **AWS Settings > View all projects > lowcase Brewing > Overview >
Additional Info > Region** before applying.

When you are ready to provision this reviewed plan:

```sh
terraform -chdir=terraform apply poc.tfplan
```

If an apply fails partway through, Terraform records the resources that succeeded.
After fixing the configuration, regenerate `poc.tfplan` with the plan command above,
review the remaining changes, and apply that **new** plan. Do not replay the old plan
or destroy successful resources just to retry. Validation and planning cannot catch
every feature-tier restriction that AWS enforces when a resource is created.

The default browser callback/logout URL is exactly `http://localhost:8040/`.
If changing it, set `poc_callback_url` in an ignored `terraform/terraform.tfvars`
before planning. The allowed CORS origin follows this URL. HTTP is allowed only
for localhost; a remotely hosted harness needs HTTPS. No custom domain or certificate
is needed for this first test.

## 2. Create two test users outside Terraform

After apply, get the new pool ID:

```sh
terraform -chdir=terraform output -raw poc_user_pool_id
```

In the Cognito console in `us-east-2`, open that pool, choose **Users > Create user**,
and create test user A. Use an email you control, mark it verified only after you
have established ownership, and choose a temporary password satisfying the pool's
policy. Suppress automatic invitations for this controlled POC if the console
offers that option; pass the temporary password privately to the tester. The hosted
sign-in page will require a new password on first sign-in.

Repeat for test user B using another email you control. These users are independent
of the developer-facing AWS CLI login.

- **Do not reuse production users or passwords.**
- **Do not put passwords into Terraform configuration, variables, or state.**
- **Do not paste passwords, access tokens, or refresh tokens into chat or Git.**

Set the temporary password in the Cognito console, and enter it on Cognito's hosted
sign-in page when testing. The harness handles tokens automatically; you do not need
to copy or paste them.

## 3. Generate public config and serve the browser harness

```sh
terraform -chdir=terraform output -json poc_browser_config | python3 scripts/configure-poc.py
python3 -m http.server 8040 --bind 127.0.0.1 --directory poc/web
```

Open **http://localhost:8040/**. Use `localhost`, not `127.0.0.1`, in the browser:
the Cognito callback and API CORS origin must match exactly. The local server serves
only the harness directory, not the repository or Terraform state files.

`config.json` contains only public endpoints, scopes and a public client ID. It is
generated from the applied stack and excluded from Git. If the terminal pipeline
fails, regenerate it after checking profile credentials and successful apply.

## 4. Acceptance test

1. Click **Check unauthenticated request**. Expect **401** without a token.
2. Click **Sign in with Cognito**, sign in as A, and finish first-login password setup.
3. Leave the sample ID as `poc-recipe-001`. Edit the recipe's name or notes in the
   JSON editor, then click **Save recipe**. Expect a successful response with `savedAt`.
4. Click **Load recipe**. Expect the same recipe document, including numbers and
   ingredient snapshots. No brewing calculations are recomputed on the server.
5. Refresh the page, sign in again as A, and load the same ID. The saved recipe must
   survive the reload even though the access token did not.
6. Open a private browsing window, open the harness, and sign in as B. Load
   `poc-recipe-001` **before saving anything as B**. Expect **404**, not A's recipe.
7. Save a different recipe as B using that same ID. A and B must each load their own
   independent document. Sign out A and confirm an API request without a token is rejected.

Sign-out clears the harness token and Cognito hosted session. JWTs already issued
to other clients are not immediately invalidated at API Gateway; the short access
token expiry bounds that window. This harness does not implement a production
session/refresh-token strategy.

## API contract

Both routes require a Bearer **access token** from this POC's Cognito app client.

| Method and path | Scope | Result |
| --- | --- | --- |
| `PUT /recipes/{recipeId}` | `lowcase-grain-bill-poc-api/recipes.write` | Save/upsert the signed-in user's schema-v1 document; 200 |
| `GET /recipes/{recipeId}` | `lowcase-grain-bill-poc-api/recipes.read` | Read that user's document; 200 or 404 |

PUT uses `Content-Type: application/json`. The request is the shape in
[`web/sample-recipe.json`](web/sample-recipe.json): `{ "schemaVersion": 1, "recipe": {...} }`.
The URL ID must match `recipe.id`. IDs allow 1-128 ASCII letters, numbers, underscores
and hyphens, starting with a letter or number. The request limit is 64 KiB.
Unknown fields, client-supplied owners, invalid numeric parameters and incompatible
schema versions are rejected. Historical ingredient snapshots and raw weight strings
are retained, with no rounding or calculator evaluation.

Responses include `schemaVersion`, `recipe`, and a server-generated `savedAt`.
Immediate loads use a strongly consistent read. Writes are last-writer-wins for one
user and recipe ID; optimistic concurrency, lists, deletes, library management and
data migration are outside this first POC. The table stores each recipe as a validated
JSON string, so loading does not depend on DynamoDB Decimal conversion.

## Local checks

No AWS calls are made by the unit tests:

```sh
uv run --no-project --with-requirements poc/requirements-dev.txt python -m unittest discover -s poc/tests -p 'test_*.py' -v
node --test poc/tests/oauth.test.mjs
```

Tests cover recipe round trips, cross-user isolation, forged owners, token type,
client/scopes, malformed input, body limits, unreadable stored data, sanitized SDK
errors, PKCE S256, state mismatch, expiry and callback rejection.

The deployed function uses boto3 supplied by the Python 3.13 Lambda runtime. Before
production, package a tested SDK dependency version and reuse the app's canonical
schema rather than maintaining a separate POC validator. The validator deliberately
adds ID, size and timestamp limits beyond the existing browser schema.

## Cost, operations and cleanup

On-demand DynamoDB bills for requests and storage; point-in-time recovery adds
backup charges. API Gateway, Lambda, Cognito and CloudWatch have their own usage
charges and allowances. This stack uses no NAT gateway, load balancer, provisioned
database, or customer-managed KMS key. DynamoDB uses a service-managed encryption
key, and CloudWatch Logs uses its default encryption at rest. Review actual usage
and remaining credits in **AWS Settings > Billing**; throttling is not a spending cap.

Pricing: [DynamoDB](https://aws.amazon.com/dynamodb/pricing/),
[API Gateway](https://aws.amazon.com/api-gateway/pricing/),
[Lambda](https://aws.amazon.com/lambda/pricing/),
[Cognito](https://aws.amazon.com/cognito/pricing/),
[CloudWatch](https://aws.amazon.com/cloudwatch/pricing/).

API and Lambda log groups are named with the `lowcase-grain-bill-poc` prefix.
Start with the request ID and HTTP status when diagnosing failures; never enable
request-body or token logging for this test. Check exact callback URLs and API CORS
origin for browser failures; check client, issuer and requested recipe scopes for
401/403 responses. If a previously working AWS operation returns Access Denied,
check the project's plan and any spend limit in AWS Settings.

Before production, assess required MFA, session revocation, audit coverage, alarms,
customer-managed log encryption and concurrency controls. This POC is not a migration
of the app's existing accounts or data and does not yet implement BrewRepository.

After testing, decide whether to keep the POC for further work or remove it. To remove
only this stack, review `terraform -chdir=terraform plan -destroy` and then run
`terraform -chdir=terraform destroy` when ready. This deletes POC users, recipes and
logs; export anything needed first. Preserve the separate bootstrap state bucket.

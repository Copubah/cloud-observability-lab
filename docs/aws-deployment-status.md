# AWS deployment status

Updated 2026-09-11, region `us-east-1`. Phase 12 remains in progress.

## Completed

- Applied the reviewed ECR bootstrap: two repositories created, no other resources.
- Published both linux/amd64 images under tag `phase12-20260911162131`.
- Confirmed the registry digests below with ECR `describe-images`.
- Generated a full-stack preview: **29 additions, 0 changes, 0 deletions**,
  including exactly three alarms. The existing two repositories remain unchanged.

| Repository | Published digest |
|---|---|
| `cloud-observability-lab-demo/app` | `sha256:23f07e98a69b983d14f41593081e5965e58ea510849d3560e510256468e3b263` |
| `cloud-observability-lab-demo/collector` | `sha256:6e6700983eae9701ed4dc13d88d3a643478dfc49fd09dae8aa9bce380c2f1a37` |

These are registry manifest digests, not local Docker image configuration IDs.
`terraform/images.auto.tfvars.json` holds deployment values locally and is
intentionally gitignored. Terraform state is also local and gitignored; retain
it so the existing repositories can be managed and destroyed safely.

## Pending

The workspace's public IPv4 was discovered through AWS's public-IP endpoint.
A new `terraform/deployment.tfplan` uses that address as a `/32`, the published
image digests, and `us-east-1`. It proposes **29 additions, 0 changes, 0 deletions**.
The exact address is stored locally in gitignored `terraform/access.auto.tfvars.json`.
This permits testing from the workspace; browsers behind another public IP
will not have access. Recheck the address if the network changes.

The final deployment plan is prepared but **awaiting approval for apply**.
The earlier `terraform/review-only.tfplan` uses a documentation address and
must not be applied. State, plans, and generated inputs remain gitignored.

No VPC, ALB, ECS service, CloudWatch log groups, or alarms have been created.
Live telemetry ingestion, IAM enforcement, alarm transitions/recovery, and
teardown remain unverified. ECR image storage now exists and can incur charges.
Use the [Terraform runbook](../terraform/README.md) to resume or clean up;
nonempty ECR repositories deliberately block deletion until their images
are explicitly removed.

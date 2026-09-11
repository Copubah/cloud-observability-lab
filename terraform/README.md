# Terraform — Phase 12

This directory implements the [AWS architecture](../docs/aws-architecture.md)
in `us-east-1`. It creates two ECR repositories first; enabling `deploy_app`
adds the VPC, two public subnets, ALB, ECS cluster/task/service, IAM roles,
three log groups, and exactly three alarms. No NAT gateway, RDS, EFS, or Aspire
is deployed. Notification actions are unset until a destination is supplied.

Implementation is complete; no resources have been applied. Actual AWS
telemetry ingestion, IAM enforcement, alarm transitions, and destroy remain
unverified. Do not treat a mocked plan or local AWS protocol stub as a live AWS
test. Cost-bearing deployment requires review of the saved plan and your real
client CIDR. The default CIDR in the example is documentation-only.

## Files and decisions

| File | Purpose |
|---|---|
| `versions.tf`, `.terraform.lock.hcl` | Provider constraints and verified AWS provider 6.64.0 lock |
| `variables.tf` | Region, naming, CIDR, deployment/image/incident settings |
| `main.tf` | ECR, networking, ALB, and log retention |
| `iam.tf` | Separate execution and task roles with scoped log/repository access |
| `ecs.tf` | Digest-pinned containers, health checks, and single-task service |
| `alarms.tf` | 5xx percentage, ALB p99, unhealthy app-container alarms |
| `outputs.tf` | Repositories, endpoint, cluster/service, log groups |
| `tests/plan.tftest.hcl` | Mocked bootstrap/full plans and rejected unsafe inputs |
| `../otel/collector-aws.yaml`, `../otel/Dockerfile.aws` | Pinned ADOT sidecar and AWS exporter configuration |

ADOT v0.45.1 is pinned by digest and includes Contrib exporter components
v0.131.0. It accepts OTLP HTTP on task-local `127.0.0.1:4318`. The app uses
standard OTLP for traces/metrics and its existing JSON stdout for `awslogs`.
The EMF exporter retains the initial counter sample, then emits deltas; two
local test orders yielded counter values totaling two across repeated exports.
The metric allowlist excludes SDK diagnostic instruments, and dimension
rollups are disabled. HTTP histograms become EMF statistic sets (min/max/count/
sum), so the p99 alarm uses ALB `TargetResponseTime`, not those statistic sets.

X-Ray conversion preserves the 32 hex digits as `1-<first 8>-<remaining 24>`.
For log correlation, remove `1-` and the separator from the X-Ray ID. The
pinned binary's timestamp-validation bypass supports W3C-generated IDs.
[AWS trace-ID format](https://docs.aws.amazon.com/xray/latest/devguide/xray-api-sendingdata.html).
The local stub confirmed segment conversion but not X-Ray service acceptance.

SQLite writes to the image-owned `/app/data`, so the ECS app filesystem is
writable (unlike local Compose's read-only root plus named volume). The app
still runs as UID 10001. Container replacement loses orders. Deployment uses
0% minimum healthy / 100% maximum to avoid overlapping independent SQLite
instances; expect downtime on updates. The Collector starts first and stops
after the app through the ECS dependency relationship.

The execution role pulls only these ECR repositories and writes app/Collector
logs. The task role writes X-Ray segments and EMF logs. Log groups are pre-created
with seven-day retention. EMF may create its stream, but must not create missing
log groups; a missing group should be repaired through Terraform. Both containers
share the task role. ALB input is limited to the supplied IPv4 CIDR (/24 or
narrower), while task input permits only the ALB security group on port 8000.

## Validate without deploying

Prerequisites: Terraform >=1.7, AWS CLI v2, Docker, and credentials for eventual
planning/deployment. AWS credentials are not needed by mocked tests. Run from
the repository root:

```bash
terraform -chdir=terraform init
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
terraform -chdir=terraform test
```

Expected: configuration valid and **4 passed, 0 failed**. The mock tests use
reserved documentation addresses and fake digests; they do not call AWS.
The provider plugin may need network access during installation.

Build both images locally:

```bash
docker build --platform linux/amd64 -t cloud-observability-app:phase12 .
docker build --platform linux/amd64 -f otel/Dockerfile.aws -t cloud-observability-collector:phase12 otel
```

ADOT's wrapper has no `validate` subcommand. For a no-network configuration
startup check, run the exact image briefly and stop it with Ctrl-C after
`Everything is ready`:

```bash
docker run --rm --network none \
  -e AWS_REGION=us-east-1 -e LAB_ENVIRONMENT=demo \
  -e EMF_LOG_GROUP=/local-check/metrics -e AWS_EC2_METADATA_DISABLED=true \
  cloud-observability-collector:phase12
```

This checks component/config loading without credentials or AWS calls. It
cannot prove delivery. The benign EMF warning about a future rollup default
still appears in this version despite our explicit `NoDimensionRollup` setting.

## Review and bootstrap ECR

The following commands are the manual deployment procedure, not actions already
performed. Check the selected account, copy the example, and edit the CIDR:

```bash
aws sts get-caller-identity --region us-east-1
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
${EDITOR:-vi} terraform/terraform.tfvars
terraform -chdir=terraform plan -out=bootstrap.tfplan
terraform -chdir=terraform show bootstrap.tfplan
```

With `deploy_app=false`, expect exactly two ECR repositories and no running
compute or ALB. After reviewing and approving that plan:

```bash
terraform -chdir=terraform apply bootstrap.tfplan
```

Local state and plans are gitignored; keep secure backups. Do not share local
state between concurrent operators. Configure a secured remote backend before
collaborative use. The provider lock file is committed. Saved plans become
stale if configuration, images, state, or intended inputs change; regenerate
them rather than applying an old file.

## Publish images, then review the full plan

From the repository root in Bash, after building the two images above:

```bash
APP_REPO=$(terraform -chdir=terraform output -json repositories | python3 -c 'import json,sys; print(json.load(sys.stdin)["app"])')
COLLECTOR_REPO=$(terraform -chdir=terraform output -json repositories | python3 -c 'import json,sys; print(json.load(sys.stdin)["collector"])')
REGISTRY=${APP_REPO%%/*}
IMAGE_TAG=phase12-$(date -u +%Y%m%d%H%M%S)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$REGISTRY"
docker tag cloud-observability-app:phase12 "$APP_REPO:$IMAGE_TAG"
docker tag cloud-observability-collector:phase12 "$COLLECTOR_REPO:$IMAGE_TAG"
docker push "$APP_REPO:$IMAGE_TAG"
docker push "$COLLECTOR_REPO:$IMAGE_TAG"
export APP_DIGEST=$(aws ecr describe-images --region us-east-1 --repository-name "${APP_REPO#*/}" --image-ids "imageTag=$IMAGE_TAG" --query 'imageDetails[0].imageDigest' --output text)
export COLLECTOR_DIGEST=$(aws ecr describe-images --region us-east-1 --repository-name "${COLLECTOR_REPO#*/}" --image-ids "imageTag=$IMAGE_TAG" --query 'imageDetails[0].imageDigest' --output text)
python3 - <<'PY'
import json, os
from pathlib import Path
Path('terraform/images.auto.tfvars.json').write_text(json.dumps({
    'deploy_app': True,
    'app_digest': os.environ['APP_DIGEST'],
    'collector_digest': os.environ['COLLECTOR_DIGEST'],
}, indent=2) + '\n')
PY
```

Remove the `deploy_app = false` line from `terraform/terraform.tfvars` so the
generated file is the single source of that setting. Then:

```bash
terraform -chdir=terraform plan -out=deployment.tfplan
terraform -chdir=terraform show deployment.tfplan
```

Review security-group sources, two public subnets, the one-task service, image
digests, log retention, IAM scope, and exactly three alarms. Budget for ALB,
Fargate, public IPv4, ECR, CloudWatch/Container Insights and X-Ray; consult the
linked pricing pages in the architecture document. Nothing assumes free tier.
After approval, apply that exact reviewed plan:

```bash
terraform -chdir=terraform apply deployment.tfplan
```

## Verify the actual deployment

```bash
CLUSTER=$(terraform -chdir=terraform output -raw cluster_name)
SERVICE=$(terraform -chdir=terraform output -raw service_name)
aws ecs wait services-stable --region us-east-1 --cluster "$CLUSTER" --services "$SERVICE"
API_URL=$(terraform -chdir=terraform output -raw endpoint)
curl --fail-with-body "$API_URL/health"
python3 scripts/generate_traffic.py --requests 10 --delay 0.5 --url "$API_URL"
```

Expect health JSON and the normal generator totals `200:6, 201:2, 500:2`.
The waiter can time out: inspect ECS service events, task stopped reasons, and
Collector logs rather than treating Terraform apply as proof of health. A
changed operator public IP requires a new reviewed CIDR plan. HTTP is only
for synthetic demo data; add ACM/HTTPS before broader use.

Inspect the output log groups in CloudWatch. Find `Order saved` and
`Request failed`; take a fresh trace ID and locate its formatted counterpart
in X-Ray. Check all four business spans, SQL operations, and error status.
Verify `CloudObservabilityLab` metrics with the declared dimension sets; ensure
orders count once, and confirm Collector logs contain no AccessDenied or dropped
export errors. No notification is sent automatically by the alarms.

For incidents, create a new plan with `-var=simulate_db_latency=true` or
`-var=simulate_errors=true`, review and apply it; replacing the task resets
SQLite. Generate sustained traffic for at least five minutes and follow the
architecture's alarm verification steps. Restore both variables to false
through another reviewed plan. The mixed generator deliberately trips 5xx/p99
alarms even in normal mode. Use only health/users/orders for the quiet baseline.
The unhealthy-task alarm requires an actual failed ECS container health check;
`/error` alone leaves `/health` healthy and does not test this alarm.

## Teardown

Export any wanted logs before removal. Repositories deliberately use
`force_delete=false`: destroy will refuse to delete nonempty repositories.
After deciding to delete their images, list them and use ECR's console to remove
only this lab's images (including untagged images). Do not delete unrelated
repositories or account resources. Then review a destroy plan:

```bash
terraform -chdir=terraform plan -destroy -out=destroy.tfplan
terraform -chdir=terraform show destroy.tfplan
terraform -chdir=terraform apply destroy.tfplan
terraform -chdir=terraform state list
```

Expect no managed resources in state after successful teardown. If repository
deletion was blocked, clear the reviewed lab repositories and rerun the destroy
plan. Verify the console has no remaining lab tasks, ALB, ECR repositories, or
log groups; residual resources can continue billing. Retain the state backup
until this check is complete. Scaling ECS to zero does not remove ALB charges.

# Pilot AWS Deploy Checklist

Use this checklist when standing up the Duplicate Checker on AWS infrastructure for the pilot.

---

## Pre-work (before AWS access)

- [ ] Confirm approved AWS account and VPC with IT
- [ ] Confirm storage path for PDFs and run artifacts (mount point, retention policy)
- [ ] Confirm OpenAI API key is available in AWS Secrets Manager or Parameter Store
- [ ] Confirm network: reviewers access via internal VPN or direct internal URL
- [ ] Confirm PHI handling: PDFs must stay on internal storage, no external uploads

---

## Infrastructure: recommended minimal pilot shape

```text
1 x EC2 instance (t3.medium or larger, Amazon Linux 2023)
  - 2+ vCPUs for engine jobs
  - 8 GB RAM minimum (16 GB preferred for large batches)
  - 50 GB gp3 EBS root volume

1 x EBS volume for data (or EFS if multi-instance)
  - /data/review_ui_jobs     — browser-uploaded batch inputs + job outputs
  - /data/runs               — completed run artifacts (page images, JSON)
  - /data/pdfs               — optional: pre-staged PDF batches

Security group:
  - Inbound port 8765 (review UI) from VPN CIDR only
  - No public internet exposure
  - Outbound HTTPS (443) for OpenAI API calls

IAM role:
  - SecretsManagerReadWrite (to fetch OpenAI key if using OpenAI path)
  - bedrock:InvokeModel on arn:aws:bedrock:*::foundation-model/anthropic.claude-* (for Bedrock OCR)
  - No S3 access needed for v1 (local storage only)
```

---

## Deployment steps

### 1. Provision EC2

```bash
# Launch from AWS console or CLI
# Recommended: Amazon Linux 2023, t3.medium, in the approved VPC
# Attach the data EBS volume at /dev/xvdf -> mount as /data
```

### 2. Install Docker

```bash
sudo dnf install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user
```

### 3. Transfer the Docker image

Option A: push to ECR

```bash
# On your workstation:
aws ecr create-repository --repository-name dupe-engine --region us-east-1
docker tag dupe-engine-worker:v0.10.9 <account>.dkr.ecr.us-east-1.amazonaws.com/dupe-engine:v0.10.9
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/dupe-engine:v0.10.9

# On the EC2 instance:
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker pull <account>.dkr.ecr.us-east-1.amazonaws.com/dupe-engine:v0.10.9
docker tag <account>.dkr.ecr.us-east-1.amazonaws.com/dupe-engine:v0.10.9 dupe-engine-worker:v0.10.9
```

Option B: save/load via SSH (no ECR)

```bash
# On your workstation:
docker save dupe-engine-worker:v0.10.9 | gzip | ssh ec2-user@<host> "docker load"
```

### 4. Set up the .env file

```bash
# On the EC2 instance:
sudo mkdir -p /srv/apps/dupe-engine
sudo tee /srv/apps/dupe-engine/.env > /dev/null <<'EOF'
# --- Vision OCR: Bedrock (IAM auth, no key needed on AWS) ---
DUPE_VISION_OCR_PROVIDER=bedrock
DUPE_BEDROCK_OCR_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
DUPE_BEDROCK_REGION=us-east-1

# --- OpenAI key: omit when using Bedrock; add only as break-glass failsafe ---
# DUPE_OPENAI_API_KEY=sk-...

# --- OCR budget ---
DUPE_OPENAI_OCR_ENABLED=true
DUPE_REQUIRE_OPENAI_OCR=true
DUPE_OPENAI_OCR_DRY_RUN=false
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT=5

# --- PHI / compliance ---
DUPE_INCLUDE_TEXT_PREVIEW=false
DUPE_LOG_PHI=false
DUPE_PERSIST_EXTRACTED_TEXT=false
DUPE_STRICT_COMPLIANCE=true
DUPE_TLS_TERMINATED=true
DUPE_UI_AUTH_TOKEN=<set-a-strong-token>
EOF
sudo chmod 600 /srv/apps/dupe-engine/.env
```

Or fetch from Secrets Manager:

```bash
aws secretsmanager get-secret-value --secret-id dupe-engine/openai-key \
  --query SecretString --output text > /tmp/openai_key
echo "DUPE_OPENAI_API_KEY=$(cat /tmp/openai_key)" >> /srv/apps/dupe-engine/.env
rm /tmp/openai_key
```

### 5. Create data directories

```bash
sudo mkdir -p /data/review_ui_jobs /data/runs
sudo chown -R ec2-user:ec2-user /data
```

### 6. Start the review UI container

```bash
docker run -d \
  --name dupe-engine-review \
  --restart unless-stopped \
  -p 8765:8765 \
  --env-file /srv/apps/dupe-engine/.env \
  -v /data/review_ui_jobs:/data/review_ui_jobs \
  -v /data/runs:/data/runs \
  dupe-engine-worker:v0.10.9 \
  dupe-engine review-ui \
    --workspace /data/review_ui_jobs \
    --host 0.0.0.0 \
    --port 8765 \
    --no-browser
```

### 7. Verify

```bash
# On the EC2 instance:
curl http://localhost:8765/api/status
# Expected: {"ok": true, "workspace_dir": "/data/review_ui_jobs", "has_run": false}

# From VPN workstation:
curl http://<internal-ip>:8765/api/status
```

---

## Post-launch checks

- [ ] `GET /api/status` returns `{"ok": true}`
- [ ] Browser can reach `http://<internal-ip>:8765` from a VPN workstation
- [ ] Upload a small test PDF pair — job runs and completes
- [ ] Page images render in the review UI
- [ ] Reviewer decision saves and persists within the session
- [ ] `docker logs dupe-engine-review` shows no errors
- [ ] Extracted text not written to logs (`DUPE_LOG_PHI=false`, `DUPE_INCLUDE_TEXT_PREVIEW=false`, `DUPE_PERSIST_EXTRACTED_TEXT=false`)
- [ ] `DUPE_STRICT_COMPLIANCE=true` is set (compliance guards hard-stop on misconfiguration)
- [ ] `DUPE_UI_AUTH_TOKEN` is set to a strong token

---

## Maintenance commands

```bash
# Check container status
docker ps

# View logs
docker logs dupe-engine-review --tail 50

# Restart container
docker restart dupe-engine-review

# Update to a new image version
docker pull dupe-engine-worker:v0.10.10   # (when available)
docker stop dupe-engine-review
docker rm dupe-engine-review
docker run -d --name dupe-engine-review ...  # same command as step 6

# Backup run artifacts
tar czf /tmp/runs_backup_$(date +%Y%m%d).tar.gz /data/runs
aws s3 cp /tmp/runs_backup_$(date +%Y%m%d).tar.gz s3://your-backup-bucket/dupe-engine/
```

---

## Open questions (fill in before launch)

- [ ] Which EC2 instance type? (t3.medium is minimum; t3.large preferred for 20+ page batches)
- [ ] EBS vs EFS? (EFS only needed if multiple EC2 instances share storage)
- [ ] Backup retention period for run artifacts?
- [ ] Is a load balancer / HTTPS termination needed, or is VPN + HTTP sufficient for pilot?
- [ ] Who has SSH access to the instance?
- [ ] What is the escalation path if the container crashes overnight?
- [ ] Should we set a CloudWatch alarm on the container health?

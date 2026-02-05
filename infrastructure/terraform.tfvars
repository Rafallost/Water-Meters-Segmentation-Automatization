# Terraform Variables for AWS Infrastructure
# IMPORTANT: Update these values before running terraform apply

# AWS Configuration
aws_region        = "us-east-1"
availability_zone = "us-east-1a"

# EC2 Configuration
instance_type = "t3.small"  # Can upgrade to t3.medium for Phase 7 (monitoring)

# Your IP address for SSH access (get it from: curl ifconfig.me)
# MUST end with /32
my_ip = "46.112.103.98/32"  # Example: "203.0.113.45/32"

# SSH key pair name (pre-created by AWS Academy Learner Lab)
key_name = "vockey"

# S3 bucket names (globally unique - account ID already appended)
dvc_bucket    = "wms-dvc-data-055677744286"
mlflow_bucket = "wms-mlflow-artifacts-055677744286"

# GitHub repository (leave as-is unless you forked the repo)
github_repo = "Rafallost/Water-Meters-Segmentation-Autimatization"

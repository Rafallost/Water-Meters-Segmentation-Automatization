# Terraform Variables for AWS Infrastructure
# IMPORTANT: Update these values before running terraform apply

# AWS Configuration
aws_region        = "eu-central-1"
availability_zone = "eu-central-1a"

# EC2 Configuration
instance_type = "t3.small"  # Can upgrade to t3.medium for Phase 7 (monitoring)

# Your IP address for SSH access (get it from: curl ifconfig.me)
# MUST end with /32
my_ip = "YOUR_IP_HERE/32"  # Example: "203.0.113.45/32"

# SSH key pair name (must exist in AWS eu-central-1)
# Create via: AWS Console → EC2 → Key Pairs → Create key pair
key_name = "YOUR_KEY_NAME"  # Example: "wms-ssh-key"

# S3 bucket names (globally unique - account ID already appended)
dvc_bucket    = "wms-dvc-data-036136800740"
mlflow_bucket = "wms-mlflow-artifacts-036136800740"

# GitHub repository (leave as-is unless you forked the repo)
github_repo = "Rafallost/Water-Meters-Segmentation-Autimatization"

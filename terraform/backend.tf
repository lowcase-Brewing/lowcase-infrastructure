# Create the bucket with terraform/bootstrap before initializing this backend.
# State is stored in S3; Terraform uses a sibling .tflock object for locking.
terraform {
  backend "s3" {
    bucket              = "lowcase-terraform-state-697731339425-us-east-2"
    key                 = "grain-bill-calculator/poc/terraform.tfstate"
    region              = "us-east-2"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["697731339425"]
  }
}

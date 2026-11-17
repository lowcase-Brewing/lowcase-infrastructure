# After the first successful bootstrap apply, copy this to backend.tf and run:
# terraform -chdir=terraform/bootstrap init -migrate-state
terraform {
  backend "s3" {
    bucket              = "lowcase-terraform-state-697731339425-us-east-2"
    key                 = "bootstrap/terraform.tfstate"
    region              = "us-east-2"
    encrypt             = true
    use_lockfile        = true
    allowed_account_ids = ["697731339425"]
  }
}

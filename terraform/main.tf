terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

locals {
  poc_name     = "lowcase-grain-bill-poc"
  poc_origin   = trimsuffix(var.poc_callback_url, "/")
  scope_prefix = "${local.poc_name}-api"
  read_scope   = "${local.scope_prefix}/recipes.read"
  write_scope  = "${local.scope_prefix}/recipes.write"
}

# Use AWS_PROFILE=lowcase locally. Keep credentials out of Terraform files.
provider "aws" {
  region              = "us-east-2"
  allowed_account_ids = ["697731339425"]

  default_tags {
    tags = {
      Project     = "lowcase Brewing"
      Application = "Grain Bill Calculator"
      Environment = "poc"
      ManagedBy   = "Terraform"
    }
  }
}

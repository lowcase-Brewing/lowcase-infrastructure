terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
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

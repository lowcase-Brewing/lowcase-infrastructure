resource "aws_cognito_user_pool" "poc" {
  name                = local.poc_name
  username_attributes = ["email"]
  user_pool_tier      = "LITE"
  deletion_protection = "INACTIVE"

  # Non-production test pool only. Test users are created separately, never in state.
  mfa_configuration = "OFF"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_configuration {
    case_sensitive = false
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = "1"
      max_length = "2048"
    }
  }
}

resource "aws_cognito_resource_server" "recipes" {
  identifier   = local.scope_prefix
  name         = "Grain Bill POC recipe API"
  user_pool_id = aws_cognito_user_pool.poc.id

  scope {
    scope_name        = "recipes.read"
    scope_description = "Read the signed-in user's recipes"
  }
  scope {
    scope_name        = "recipes.write"
    scope_description = "Save the signed-in user's recipes"
  }
}

resource "aws_cognito_user_pool_client" "poc" {
  name         = "${local.poc_name}-browser"
  user_pool_id = aws_cognito_user_pool.poc.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", local.read_scope, local.write_scope]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [var.poc_callback_url]
  default_redirect_uri                 = var.poc_callback_url
  logout_urls                          = [var.poc_callback_url]
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 15
  id_token_validity                    = 15
  refresh_token_validity               = 1
  read_attributes                      = ["email", "email_verified"]
  write_attributes                     = []

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  refresh_token_rotation {
    # Lite rejects rotation. The POC harness discards refresh tokens and signs in again.
    feature                    = "DISABLED"
    retry_grace_period_seconds = 0 # Explicit AWS default avoids a provider null-versus-zero error.
  }

  depends_on = [aws_cognito_resource_server.recipes]
}

resource "aws_cognito_user_pool_domain" "poc" {
  domain                = "${local.poc_name}-697731339425"
  user_pool_id          = aws_cognito_user_pool.poc.id
  managed_login_version = 1 # Classic hosted UI works with the Lite tier.
}

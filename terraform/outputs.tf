output "poc_user_pool_id" {
  description = "Isolated Cognito pool; create test users here, never in the live app."
  value       = aws_cognito_user_pool.poc.id
}

output "poc_api_url" {
  value = aws_apigatewayv2_api.poc.api_endpoint
}

output "poc_recipes_table" {
  value = aws_dynamodb_table.recipes.name
}

output "poc_browser_config" {
  description = "Public client configuration only; no credentials or secrets."
  value = {
    apiBaseUrl  = aws_apigatewayv2_api.poc.api_endpoint
    clientId    = aws_cognito_user_pool_client.poc.id
    issuer      = "https://${aws_cognito_user_pool.poc.endpoint}"
    authDomain  = "https://${aws_cognito_user_pool_domain.poc.domain}.auth.us-east-2.amazoncognito.com"
    redirectUri = var.poc_callback_url
    scopes      = ["openid", "email", local.read_scope, local.write_scope]
  }
}

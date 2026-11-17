resource "aws_apigatewayv2_api" "poc" {
  name          = local.poc_name
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = [local.poc_origin]
    allow_methods = ["GET", "PUT", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_authorizer" "poc" {
  api_id           = aws_apigatewayv2_api.poc.id
  name             = "cognito-access-token"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.poc.id]
    issuer   = "https://${aws_cognito_user_pool.poc.endpoint}"
  }
}

resource "aws_apigatewayv2_integration" "recipes" {
  api_id                 = aws_apigatewayv2_api.poc.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.recipe_api.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 12000
}

resource "aws_apigatewayv2_route" "recipes" {
  for_each = {
    "GET /recipes/{recipeId}" = local.read_scope
    "PUT /recipes/{recipeId}" = local.write_scope
  }

  api_id               = aws_apigatewayv2_api.poc.id
  route_key            = each.key
  target               = "integrations/${aws_apigatewayv2_integration.recipes.id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.poc.id
  authorization_scopes = [each.value]
}

resource "aws_cloudwatch_log_group" "api_gateway" {
  name              = "/aws/apigateway/${local.poc_name}"
  retention_in_days = 7
}

resource "aws_apigatewayv2_stage" "poc" {
  api_id      = aws_apigatewayv2_api.poc.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }

  # Metadata only: no tokens, headers, bodies, email addresses, or recipe content.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway.arn
    format = jsonencode({
      requestId = "$context.requestId"
      routeKey  = "$context.routeKey"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
    })
  }
}

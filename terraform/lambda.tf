data "archive_file" "recipe_api" {
  type        = "zip"
  source_file = "${path.module}/../poc/api/handler.py"
  output_path = "${path.module}/.terraform/recipe-api.zip"
}

resource "aws_cloudwatch_log_group" "recipe_api" {
  name              = "/aws/lambda/${local.poc_name}-recipes"
  retention_in_days = 7
}

resource "aws_iam_role" "recipe_api" {
  name = "${local.poc_name}-recipes"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "recipe_api" {
  name = "recipes-and-logs"
  role = aws_iam_role.recipe_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.recipes.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.recipe_api.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "recipe_api" {
  function_name    = "${local.poc_name}-recipes"
  description      = "Isolated POC: authenticated recipe save/load, never Supabase or live app data"
  role             = aws_iam_role.recipe_api.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.recipe_api.output_path
  source_code_hash = data.archive_file.recipe_api.output_base64sha256
  memory_size      = 128
  timeout          = 10

  environment {
    variables = {
      RECIPES_TABLE = aws_dynamodb_table.recipes.name
      APP_CLIENT_ID = aws_cognito_user_pool_client.poc.id
      READ_SCOPE    = local.read_scope
      WRITE_SCOPE   = local.write_scope
    }
  }

  depends_on = [aws_iam_role_policy.recipe_api]
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id   = "AllowRecipeApiGateway"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.recipe_api.function_name
  principal      = "apigateway.amazonaws.com"
  source_account = "697731339425"
  source_arn     = "${aws_apigatewayv2_api.poc.execution_arn}/*/*/recipes/*"
}

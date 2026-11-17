resource "aws_dynamodb_table" "recipes" {
  name         = "${local.poc_name}-recipes"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "owner_id"
  range_key    = "recipe_id"

  attribute {
    name = "owner_id"
    type = "S"
  }
  attribute {
    name = "recipe_id"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

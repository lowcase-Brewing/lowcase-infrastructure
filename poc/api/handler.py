"""Isolated recipe save/load API. API Gateway verifies signatures before invocation."""

import base64
import binascii
import json
import logging
import math
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

MAX_BODY_BYTES = 64 * 1024
RECIPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
_table = None


class InvalidRequest(ValueError):
    pass


def table():
    global _table
    if _table is None:
        resource = boto3.resource(
            "dynamodb",
            config=Config(
                retries={"mode": "standard", "total_max_attempts": 3},
                connect_timeout=2,
                read_timeout=2,
            ),
        )
        _table = resource.Table(os.environ["RECIPES_TABLE"])
    return _table


def response(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
        },
        "body": json.dumps(payload, ensure_ascii=False, allow_nan=False),
    }


def error(status, code, message):
    return response(status, {"error": {"code": code, "message": message}})


def text(value, field, nonempty=False, limit=None):
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise InvalidRequest(f"{field} must be {'a nonempty string' if nonempty else 'a string'}.")
    if limit is not None and len(value) > limit:
        raise InvalidRequest(f"{field} is too long.")


def number(value, field, nullable=False, minimum=None, maximum=None):
    if value is None and nullable:
        return
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise InvalidRequest(f"{field} must be a finite number.")
    if minimum is not None and value <= minimum:
        raise InvalidRequest(f"{field} is below its allowed range.")
    if maximum is not None and value > maximum:
        raise InvalidRequest(f"{field} is above its allowed range.")


def shape(value, fields, field):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise InvalidRequest(f"{field} contains missing or unsupported fields.")


def timestamp(value, field):
    text(value, field, nonempty=True)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as exc:
        raise InvalidRequest(f"{field} must be an ISO timestamp with a timezone.") from exc


def validate_recipe(recipe, recipe_id):
    # Matches the app's schema-v1 Recipe shape; no calculator formulas run here.
    shape(recipe, ["id", "name", "style", "version", "method", "parameters", "description",
                   "notes", "hopsNotes", "yeastNotes", "processNotes", "grainBill",
                   "grainBillSummary", "createdAt", "updatedAt"], "recipe")
    if recipe["id"] != recipe_id:
        raise InvalidRequest("recipe.id must match the URL recipeId.")
    for field in ["name", "style"]:
        text(recipe[field], field, nonempty=True, limit=200)
    text(recipe["version"], "version")
    if not VERSION.fullmatch(recipe["version"]):
        raise InvalidRequest("version must use major.minor.patch format.")
    if recipe["method"] not in ["all-grain", "partial-mash", "extract"]:
        raise InvalidRequest("method is unsupported.")
    for field in ["description", "notes", "hopsNotes", "yeastNotes", "processNotes"]:
        text(recipe[field], field)
    parameters = recipe["parameters"]
    shape(parameters, ["coldFermenterGal", "efficiencyPct", "targetOG", "extractRecoveryPct"], "parameters")
    number(parameters["coldFermenterGal"], "coldFermenterGal", minimum=0)
    number(parameters["efficiencyPct"], "efficiencyPct", minimum=0, maximum=100)
    number(parameters["targetOG"], "targetOG", nullable=True, minimum=1, maximum=1.3)
    number(parameters["extractRecoveryPct"], "extractRecoveryPct", minimum=0, maximum=100)
    if not isinstance(recipe["grainBill"], list):
        raise InvalidRequest("grainBill must be an array.")
    for row in recipe["grainBill"]:
        shape(row, ["id", "ingredient", "lb", "oz"], "grainBill row")
        text(row["id"], "row.id", nonempty=True)
        text(row["lb"], "row.lb")
        text(row["oz"], "row.oz")
        ingredient = row["ingredient"]
        if ingredient is not None:
            shape(ingredient, ["libraryId", "name", "category", "origin", "extractFraction",
                               "ppg", "notes", "capturedAt"], "ingredient snapshot")
            for field in ["libraryId", "name"]:
                text(ingredient[field], f"ingredient.{field}", nonempty=True)
            for field in ["origin", "notes"]:
                text(ingredient[field], f"ingredient.{field}")
            if ingredient["category"] not in ["Base", "Specialty", "Adjunct", "Extract"]:
                raise InvalidRequest("ingredient.category is unsupported.")
            number(ingredient["extractFraction"], "ingredient.extractFraction", nullable=True)
            number(ingredient["ppg"], "ingredient.ppg")
            timestamp(ingredient["capturedAt"], "ingredient.capturedAt")
    summary = recipe["grainBillSummary"]
    if summary is not None:
        shape(summary, ["savedAt", "complete", "reason", "totalWeightLb", "mashedGrainLb",
                        "totalPoints", "estimatedOG", "differencePoints"], "grainBillSummary")
        timestamp(summary["savedAt"], "summary.savedAt")
        if type(summary["complete"]) is not bool:
            raise InvalidRequest("summary.complete must be a boolean.")
        if summary["reason"] is not None:
            text(summary["reason"], "summary.reason")
        for field in ["totalWeightLb", "mashedGrainLb", "totalPoints", "estimatedOG", "differencePoints"]:
            number(summary[field], f"summary.{field}", nullable=True)
    for field in ["createdAt", "updatedAt"]:
        timestamp(recipe[field], field)


def reject_constant(_value):
    raise InvalidRequest("Non-finite JSON numbers are not supported.")


def request_document(event):
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return None, error(415, "unsupported_media_type", "Use Content-Type: application/json.")
    body = event.get("body")
    if not isinstance(body, str):
        raise InvalidRequest("A JSON request body is required.")
    if len(body) > MAX_BODY_BYTES * 2:
        return None, error(413, "payload_too_large", "Recipe request exceeds 64 KiB.")
    try:
        raw = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode("utf-8")
        if len(raw) > MAX_BODY_BYTES:
            return None, error(413, "payload_too_large", "Recipe request exceeds 64 KiB.")
        document = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (ValueError, UnicodeError, binascii.Error, RecursionError) as exc:
        raise InvalidRequest("Body must contain valid UTF-8 JSON.") from exc
    shape(document, ["schemaVersion", "recipe"], "request")
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise InvalidRequest("Only schemaVersion 1 is supported.")
    return document, None


def lambda_handler(event, context):
    claims = (event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims") or {})
    owner_id = claims.get("sub")
    if (not isinstance(owner_id, str) or not owner_id or len(owner_id) > 128
            or claims.get("token_use") != "access"
            or claims.get("client_id") != os.environ["APP_CLIENT_ID"]):
        return error(401, "unauthorized", "A valid POC access token is required.")
    route = event.get("routeKey")
    scopes = {"GET /recipes/{recipeId}": os.environ["READ_SCOPE"],
              "PUT /recipes/{recipeId}": os.environ["WRITE_SCOPE"]}
    if route not in scopes:
        return error(404, "not_found", "Route not found.")
    token_scopes = claims.get("scope", "")
    if not isinstance(token_scopes, str) or scopes[route] not in token_scopes.split():
        return error(403, "forbidden", "The access token lacks the required recipe scope.")
    recipe_id = (event.get("pathParameters") or {}).get("recipeId")
    if not isinstance(recipe_id, str) or not RECIPE_ID.fullmatch(recipe_id):
        return error(400, "invalid_request", "recipeId must use 1-128 letters, numbers, underscores or hyphens.")

    # No body/query parameter can override this owner. Another user's recipe is unaddressable.
    key = {"owner_id": owner_id, "recipe_id": recipe_id}
    try:
        if route.startswith("PUT "):
            document, failure = request_document(event)
            if failure:
                return failure
            validate_recipe(document["recipe"], recipe_id)
            saved_at = datetime.now(timezone.utc).isoformat()
            # Keep the JSON document intact instead of coercing recipe floats to DynamoDB decimals.
            table().put_item(Item={**key, "schema_version": 1,
                                   "document": json.dumps(document["recipe"], ensure_ascii=False, allow_nan=False),
                                   "saved_at": saved_at})
            return response(200, {**document, "savedAt": saved_at})
        item = table().get_item(Key=key, ConsistentRead=True).get("Item")
        if item is None:
            return error(404, "not_found", "Recipe not found.")
        if item.get("schema_version") != 1:
            return error(500, "stored_data_invalid", "Stored recipe version is unsupported; it was left untouched.")
        try:
            recipe = json.loads(item["document"], parse_constant=reject_constant)
            validate_recipe(recipe, recipe_id)
            saved_at = item["saved_at"]
        except (KeyError, ValueError, TypeError, RecursionError):
            return error(500, "stored_data_invalid", "Stored recipe is unreadable; it was left untouched.")
        return response(200, {"schemaVersion": 1, "recipe": recipe, "savedAt": saved_at})
    except InvalidRequest as exc:
        return error(400, "invalid_request", str(exc))
    except (ClientError, BotoCoreError) as exc:
        # Never log events, tokens or recipe content, even on SDK failures.
        code = exc.response.get("Error", {}).get("Code", "unknown") if isinstance(exc, ClientError) else type(exc).__name__
        LOGGER.error("Recipe storage unavailable code=%s request_id=%s", code, getattr(context, "aws_request_id", "unknown"))
        return error(503, "storage_unavailable", "Recipe storage is unavailable; retry shortly.")

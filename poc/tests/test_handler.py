import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("recipe_handler", ROOT / "api/handler.py")
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)
SAMPLE = json.loads((ROOT / "web/sample-recipe.json").read_text())
READ = "lowcase-grain-bill-poc-api/recipes.read"
WRITE = "lowcase-grain-bill-poc-api/recipes.write"


class FakeTable:
    def __init__(self):
        self.items = {}
        self.reads = []

    def put_item(self, *, Item):
        self.items[(Item["owner_id"], Item["recipe_id"])] = copy.deepcopy(Item)
        return {}

    def get_item(self, *, Key, ConsistentRead):
        self.reads.append((Key, ConsistentRead))
        item = self.items.get((Key["owner_id"], Key["recipe_id"]))
        return {"Item": copy.deepcopy(item)} if item is not None else {}


def event(method="GET", user="user-a", document=None):
    result = {
        "routeKey": f"{method} /recipes/{{recipeId}}",
        "pathParameters": {"recipeId": "poc-recipe-001"},
        "requestContext": {"authorizer": {"jwt": {"claims": {
            "sub": user, "token_use": "access", "client_id": "test-client",
            "scope": f"openid email {READ} {WRITE}",
        }}}},
        "headers": {"content-type": "application/json"},
    }
    if document is not None:
        result["body"] = json.dumps(document)
    return result


class RecipeApiTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeTable()
        self.environment = patch.dict(os.environ, {
            "APP_CLIENT_ID": "test-client", "RECIPES_TABLE": "test-only",
            "READ_SCOPE": READ, "WRITE_SCOPE": WRITE,
        })
        self.environment.start()
        self.storage = patch.object(api, "table", return_value=self.table)
        self.storage.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.storage.stop)

    def call(self, request):
        result = api.lambda_handler(request, SimpleNamespace(aws_request_id="test-request"))
        self.assertEqual(result["headers"]["cache-control"], "no-store")
        return result["statusCode"], json.loads(result["body"])

    def test_round_trip_preserves_numbers_snapshots_and_raw_weight_strings(self):
        document = copy.deepcopy(SAMPLE)
        document["recipe"]["grainBill"][0]["lb"] = "not-yet-valid-input"
        status, saved = self.call(event("PUT", document=document))
        self.assertEqual(status, 200)
        status, loaded = self.call(event())
        self.assertEqual(status, 200)
        self.assertEqual(saved, loaded)
        self.assertEqual(loaded["recipe"], document["recipe"])
        self.assertTrue(self.table.reads[-1][1], "Immediate load must be strongly consistent")

    def test_another_user_cannot_read_or_overwrite_owners_recipe(self):
        self.assertEqual(self.call(event("PUT", document=SAMPLE))[0], 200)
        self.assertEqual(self.call(event(user="user-b"))[0], 404)
        other = copy.deepcopy(SAMPLE)
        other["recipe"]["name"] = "User B's recipe with the same id"
        self.assertEqual(self.call(event("PUT", user="user-b", document=other))[0], 200)
        self.assertEqual(self.call(event())[1]["recipe"]["name"], SAMPLE["recipe"]["name"])
        self.assertEqual(self.call(event(user="user-b"))[1]["recipe"]["name"], other["recipe"]["name"])

    def test_client_cannot_supply_a_different_owner(self):
        for location in ["envelope", "recipe"]:
            with self.subTest(location=location):
                forged = copy.deepcopy(SAMPLE)
                target = forged if location == "envelope" else forged["recipe"]
                target["owner_id"] = "user-b"
                self.assertEqual(self.call(event("PUT", document=forged))[0], 400)
        self.assertEqual(self.table.items, {})

    def test_missing_authorizer_id_token_wrong_client_or_empty_identity_are_rejected(self):
        for change in ["missing", "id-token", "client", "empty"]:
            with self.subTest(change=change):
                request = event()
                claims = request["requestContext"]["authorizer"]["jwt"]["claims"]
                if change == "missing":
                    request["requestContext"] = {}
                elif change == "id-token":
                    claims["token_use"] = "id"
                elif change == "client":
                    claims["client_id"] = "another-client"
                else:
                    claims["sub"] = ""
                self.assertEqual(self.call(request)[0], 401)
        self.assertEqual(self.table.reads, [])

    def test_read_scope_does_not_grant_write(self):
        request = event("PUT", document=SAMPLE)
        request["requestContext"]["authorizer"]["jwt"]["claims"]["scope"] = READ
        self.assertEqual(self.call(request)[0], 403)
        self.assertEqual(self.table.items, {})

    def test_mismatched_id_and_unsupported_schema_are_rejected(self):
        mismatched = copy.deepcopy(SAMPLE)
        mismatched["recipe"]["id"] = "another-id"
        self.assertEqual(self.call(event("PUT", document=mismatched))[0], 400)
        for schema in [2, True, "1"]:
            request = copy.deepcopy(SAMPLE)
            request["schemaVersion"] = schema
            self.assertEqual(self.call(event("PUT", document=request))[0], 400)

    def test_invalid_parameters_and_snapshots_do_not_write(self):
        for field, value in [("efficiencyPct", 0), ("targetOG", 1.5), ("coldFermenterGal", True)]:
            with self.subTest(field=field):
                invalid = copy.deepcopy(SAMPLE)
                invalid["recipe"]["parameters"][field] = value
                self.assertEqual(self.call(event("PUT", document=invalid))[0], 400)
        invalid = copy.deepcopy(SAMPLE)
        del invalid["recipe"]["grainBill"][0]["ingredient"]["ppg"]
        self.assertEqual(self.call(event("PUT", document=invalid))[0], 400)
        self.assertEqual(self.table.items, {})

    def test_malformed_json_nan_wrong_media_type_and_oversized_body(self):
        for body in ["{", '{"schemaVersion":NaN}', "[]"]:
            request = event("PUT")
            request["body"] = body
            self.assertEqual(self.call(request)[0], 400)
        request = event("PUT", document=SAMPLE)
        request["headers"]["content-type"] = "text/plain"
        self.assertEqual(self.call(request)[0], 415)
        request = event("PUT")
        request["body"] = " " * (api.MAX_BODY_BYTES + 1)
        self.assertEqual(self.call(request)[0], 413)

    def test_base64_body_is_supported_and_bounded_after_decoding(self):
        request = event("PUT")
        request["isBase64Encoded"] = True
        request["body"] = base64.b64encode(json.dumps(SAMPLE).encode()).decode()
        self.assertEqual(self.call(request)[0], 200)
        request["body"] = "not/base64!"
        self.assertEqual(self.call(request)[0], 400)
        request["body"] = base64.b64encode(b" " * (api.MAX_BODY_BYTES + 1)).decode()
        self.assertEqual(self.call(request)[0], 413)

    def test_corrupt_or_unknown_stored_version_is_never_silently_replaced(self):
        self.call(event("PUT", document=SAMPLE))
        stored = self.table.items[("user-a", "poc-recipe-001")]
        stored["document"] = "unreadable"
        self.assertEqual(self.call(event())[0], 500)
        self.assertEqual(stored["document"], "unreadable")
        stored["schema_version"] = 99
        self.assertEqual(self.call(event())[0], 500)

    def test_sdk_errors_do_not_expose_tokens_or_recipe_content(self):
        failure = ClientError({"Error": {"Code": "InternalServerError", "Message": "private backend details"}}, "GetItem")
        with patch.object(self.table, "get_item", side_effect=failure), self.assertLogs(api.LOGGER, level="ERROR") as logs:
            status, payload = self.call(event())
        self.assertEqual(status, 503)
        self.assertNotIn("private backend details", json.dumps(payload) + str(logs.output))


if __name__ == "__main__":
    unittest.main()

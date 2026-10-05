import json
import unittest
import uuid
from typing import Any, cast

from src.MutationCoordinator import OperationFailure, OperationReceipt
from src.api.ApiResources import ApiResources
from src.api.ProblemDetails import problem_response, safe_detail
from src.domain.models import OperationIntent, OperationTarget


class ProblemDetailsTest(unittest.TestCase):

    def test_safe_detail_redacts_exact_token_authorization_urls_and_queries(self):
        token = "secret-value-123"
        detail = safe_detail(
            "Authorization: Bearer secret-value-123\n"
            "request https://example.test/path?session=private "
            "?next=private,extra=hidden;other=hidden token=another-secret",
            token,
        )

        self.assertNotIn(token, detail)
        self.assertNotIn("private", detail)
        self.assertNotIn("another-secret", detail)
        self.assertNotIn("extra=hidden", detail)
        self.assertGreaterEqual(detail.count("[redactado]"), 4)

    def test_bearer_redaction_preserves_scheme_casing(self):
        self.assertEqual(
            safe_detail("bEaReR private-credential", "unrelated"),
            "bEaReR [redactado]",
        )

    def test_literal_redaction_marker_remains_unchanged(self):
        self.assertEqual(
            safe_detail("token=[redactado]", "[redactado]"),
            "token=[redactado]",
        )

    def test_secret_assignments_and_control_characters_are_sanitized(self):
        detail = safe_detail(
            "{'Authorization': 'Bearer hidden', 'api_key': 'key-value'}\nnext",
            "configured-token",
        )

        self.assertNotIn("hidden", detail)
        self.assertNotIn("key-value", detail)
        self.assertNotIn("\n", detail)
        self.assertIn("[redactado]", detail)

    def test_problem_response_keeps_only_safe_evidence_and_headers(self):
        response = problem_response(
            status=401,
            code="unauthorized",
            detail="Authentication failed for Bearer private-token",
            request_id="request-1",
            instance="/api/v1/tasks?private=1",
            token="private-token",
            evidence={
                "savedCount": 1_000_001,
                "savedResources": [
                    {"kind": "task", "href": "/api/v1/tasks/task-1"},
                    {"kind": "task", "href": "/api/v1/tasks?secret=1"},
                    {"kind": "task", "href": "https://example.test/task"},
                    {"kind": "task", "href": "//[::1"},
                    {"kind": "project", "href": "/api/v1/projects/../private"},
                    {"kind": "task", "href": "/api/v1/tasks/private-token"},
                    {"kind": "task", "href": "/api/v1/tasks/task-2", "extra": "secret"},
                ],
                "unsafe": {"Authorization": "Bearer private-token"},
            },
            challenge_bearer=True,
            headers={
                "Authorization": "Bearer private-token",
                "Set-Cookie": "secret=private-token",
                "Allow": "GET, POST",
            },
        )
        body = json.loads(response.text)

        self.assertEqual(response.status, 401)
        self.assertEqual(response.headers["WWW-Authenticate"], 'Bearer realm="api"')
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Allow"], "GET, POST")
        self.assertNotIn("Authorization", response.headers)
        self.assertNotIn("Set-Cookie", response.headers)
        self.assertNotIn("private-token", response.text)
        self.assertNotIn("unsafe", body)
        self.assertEqual(body["savedCount"], 1_000_001)
        self.assertEqual(
            body["savedResources"],
            [{"kind": "task", "href": "/api/v1/tasks/task-1"}],
        )
        self.assertNotIn("?private=1", body["instance"])

    def test_response_ignores_unsupported_allow_and_auth_challenge_values(self):
        response = problem_response(
            status=405,
            code="method-not-allowed",
            detail="Method not allowed",
            request_id="request-2",
            instance="/api/v1/tasks",
            token="token",
            headers={
                "Allow": "GET, DELETE",
                "WWW-Authenticate": 'Bearer realm="other"',
            },
        )

        self.assertNotIn("Allow", response.headers)
        self.assertNotIn("WWW-Authenticate", response.headers)

    def test_failed_operation_receipt_redacts_token_from_typed_diagnostics(self):
        token = "credential-hidden-in-failure"
        failure = OperationFailure(
            error_type="provider.Error",
            message=f"provider rejected {token}",
            effects_state="partial",
            code=token,
            details={
                "resource": "task",
                "failed_id": token,
                "uncertain_id": "known-task",
                "saved_ids": [token, "saved-task"],
                "saved_count": 2,
                "write_phase": "replace",
            },
        )
        receipt = OperationReceipt(
            operation_id=str(uuid.uuid4()),
            intent=OperationIntent(
                "edit-task", OperationTarget("task", "target-task"), {}
            ),
            status="failed",
            failure=failure,
        )
        resources = ApiResources(cast(Any, object()), token=token)

        document = resources.operation_resource(receipt)
        serialized = json.dumps(document)

        self.assertNotIn(token, serialized)
        self.assertEqual(document["failure"]["code"], "[redactado]")
        self.assertEqual(
            document["failure"]["details"]["failedId"], "[redactado]"
        )
        self.assertEqual(
            document["failure"]["details"]["uncertainId"], "known-task"
        )
        self.assertEqual(
            document["failure"]["details"]["savedIds"],
            ["[redactado]", "saved-task"],
        )
        self.assertEqual(
            document["failure"]["_links"]["resources"],
            [
                {"href": "/api/v1/tasks/saved-task"},
                {"href": "/api/v1/tasks/known-task"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

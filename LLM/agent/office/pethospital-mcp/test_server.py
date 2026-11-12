"""pethospital-mcp 单元测试：用 mock 替代真实上游，覆盖校验与错误码。"""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SERVER_PATH = Path(__file__).with_name("server.py")
SPEC = importlib.util.spec_from_file_location("pethospital_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(server)


def call_tool(name: str, arguments: dict) -> dict:
    response, status = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        {},
    )
    assert status == 200
    return response["result"]


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ToolErrorTests(unittest.TestCase):
    def assert_error(self, result: dict, code: str) -> None:
        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["code"], code)
        self.assertIn(code, result["content"][0]["text"])

    def test_empty_id_is_validation_error(self):
        result = call_tool("pet_get", {"id": "   "})
        self.assert_error(result, "PET_VALIDATION")
        self.assertIn("id 不能为空", result["structuredContent"]["message"])

    def test_invalid_page_size_is_rejected_before_upstream(self):
        with mock.patch.object(server, "_request") as request:
            result = call_tool("pet_list", {"pageSize": 0})
        request.assert_not_called()
        self.assert_error(result, "PET_VALIDATION")
        self.assertIn("pageSize", result["structuredContent"]["message"])

    def test_invalid_order_is_rejected(self):
        result = call_tool("pet_list", {"order": "sideways"})
        self.assert_error(result, "PET_VALIDATION")

    def test_upstream_500_is_structured(self):
        with mock.patch.object(
            server,
            "_request",
            side_effect=server.PetError("PET_UPSTREAM", "HTTP 500", "boom"),
        ):
            result = call_tool("pet_list", {"page": 1})
        self.assert_error(result, "PET_UPSTREAM")

    def test_timeout_is_structured(self):
        with mock.patch.object(
            server,
            "_request",
            side_effect=server.PetError("PET_TIMEOUT", "超时", "timed out"),
        ):
            result = call_tool("pet_get", {"id": "PET-000001"})
        self.assert_error(result, "PET_TIMEOUT")

    def test_unknown_tool_is_structured(self):
        result = call_tool("pet_nope", {})
        self.assert_error(result, "PET_VALIDATION")
        self.assertIn("Unknown tool", result["structuredContent"]["message"])

    def test_unexpected_exception_is_wrapped(self):
        with mock.patch.object(server, "_request", side_effect=RuntimeError("boom")):
            result = call_tool("pet_list", {})
        self.assert_error(result, "PET_UPSTREAM")
        self.assertIn("RuntimeError", result["structuredContent"]["detail"])

    def test_success_shape(self):
        with mock.patch.object(
            server, "_request", return_value={"items": [{"id": "P1"}], "total": 1}
        ):
            result = call_tool("pet_list", {"page": 1, "pageSize": 10})
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["total"], 1)
        self.assertEqual(result["content"][0]["type"], "text")


class RequestRetryTests(unittest.TestCase):
    def test_get_retries_once_with_exponential_delay(self):
        error = urllib.error.HTTPError(
            "http://x", 500, "server error", {}, io.BytesIO(b"boom")
        )
        responses = [error, FakeResponse({"code": 200, "data": {"ok": True}})]
        with mock.patch.object(
            server.urllib.request, "urlopen", side_effect=responses
        ) as urlopen, mock.patch.object(server.time, "sleep") as sleep:
            data = server._request("GET", "/api/v1/pets")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(server.GET_RETRY_DELAY)

    def test_post_is_never_retried(self):
        error = urllib.error.HTTPError(
            "http://x", 500, "server error", {}, io.BytesIO(b"boom")
        )
        with mock.patch.object(
            server.urllib.request, "urlopen", side_effect=error
        ) as urlopen, mock.patch.object(server.time, "sleep") as sleep:
            with self.assertRaises(server.PetError) as ctx:
                server._request("POST", "/api/v1/pets", body={})
        self.assertEqual(ctx.exception.code, "PET_UPSTREAM")
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_get_timeout_retries_then_reports_timeout(self):
        with mock.patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=socket.timeout("timed out"),
        ) as urlopen, mock.patch.object(server.time, "sleep"):
            with self.assertRaises(server.PetError) as ctx:
                server._request("GET", "/api/v1/pets")
        self.assertEqual(ctx.exception.code, "PET_TIMEOUT")
        self.assertEqual(urlopen.call_count, 2)

    def test_connection_failure_maps_to_unavailable(self):
        with mock.patch.object(
            server.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError(ConnectionRefusedError("refused")),
        ), mock.patch.object(server.time, "sleep"):
            with self.assertRaises(server.PetError) as ctx:
                server._request("GET", "/api/v1/pets")
        self.assertEqual(ctx.exception.code, "PET_UNAVAILABLE")


class SchemaTests(unittest.TestCase):
    def _tool(self, name: str) -> dict:
        return next(tool for tool in server.TOOLS if tool["name"] == name)

    def test_pet_list_schema_constraints(self):
        props = self._tool("pet_list")["inputSchema"]["properties"]
        self.assertIn("待就诊", props["status"]["enum"])
        self.assertEqual(props["order"]["enum"], ["asc", "desc"])
        self.assertEqual(props["pageSize"]["minimum"], 1)
        self.assertEqual(props["pageSize"]["maximum"], server.MAX_PAGE_SIZE)

    def test_pet_stats_top_bounds(self):
        props = self._tool("pet_stats")["inputSchema"]["properties"]
        self.assertEqual(props["top"]["minimum"], 1)
        self.assertEqual(props["top"]["maximum"], server.MAX_TOP)


if __name__ == "__main__":
    unittest.main()

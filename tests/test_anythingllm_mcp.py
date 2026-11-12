"""AnythingLLM MCP：缺 Key 时不得访问上游，tools/call 返回 isError。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "LLM" / "anytingLLM-MCP" / "server.py"
SPEC = importlib.util.spec_from_file_location("anythingllm_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(server)


def call(name: str) -> dict:
    response, status = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
        {},
    )
    assert status == 200
    return response["result"]


class MissingKeyTests(unittest.TestCase):
    def test_tools_call_returns_error_without_upstream(self):
        with mock.patch.object(server, "ANYTHINGLLM_API_KEY", ""), mock.patch.object(
            server, "first_workspace_files"
        ) as upstream:
            result = call("first_workspace_files")
        upstream.assert_not_called()
        self.assertTrue(result["isError"])
        self.assertIn("未配置 ANYTHINGLLM_API_KEY", result["content"][0]["text"])

    def test_tools_list_still_works_without_key(self):
        response, status = server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, {}
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["result"]["tools"][0]["name"], "first_workspace_files")

    def test_anythingllm_get_guard(self):
        with mock.patch.object(server, "ANYTHINGLLM_API_KEY", ""):
            with self.assertRaises(RuntimeError) as ctx:
                server.anythingllm_get("/api/v1/workspaces")
        self.assertIn("未配置 ANYTHINGLLM_API_KEY", str(ctx.exception))

    def test_success_with_key(self):
        payload = {"workspace": {"id": 1}, "fileCount": 0, "files": []}
        with mock.patch.object(server, "ANYTHINGLLM_API_KEY", "test-key"), mock.patch.object(
            server, "first_workspace_files", return_value=payload
        ):
            result = call("first_workspace_files")
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], payload)

    def test_every_tool_is_blocked_without_key(self):
        for tool in server.TOOLS:
            with self.subTest(tool=tool["name"]), mock.patch.object(
                server, "ANYTHINGLLM_API_KEY", ""
            ), mock.patch.object(server, "anythingllm_request") as upstream:
                result = call(tool["name"])
            upstream.assert_not_called()
            self.assertTrue(result["isError"])
            self.assertIn("未配置 ANYTHINGLLM_API_KEY", result["content"][0]["text"])

    def test_tool_schemas_have_constraints(self):
        response, _ = server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, {}
        )
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        self.assertGreaterEqual(len(tools), 4)
        ask = tools["ask_workspace"]["inputSchema"]
        self.assertEqual(ask["properties"]["mode"]["enum"], ["query", "chat"])
        upload = tools["upload_document"]["inputSchema"]
        self.assertIn("file_path", upload["required"])
        self.assertEqual(upload["properties"]["embed"]["type"], "boolean")


class CapabilityTests(unittest.TestCase):
    def test_list_workspaces(self):
        payload = {
            "workspaces": [
                {"id": 1, "name": "默认", "slug": "default", "extra": "x"},
                {"id": 2, "name": "项目", "slug": "project"},
            ]
        }
        with mock.patch.object(server, "anythingllm_get", return_value=payload):
            result = server.list_workspaces()
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["workspaces"][0]["slug"], "default")
        self.assertNotIn("extra", result["workspaces"][0])

    def test_unknown_workspace_is_validation_error(self):
        with mock.patch.object(
            server,
            "anythingllm_get",
            return_value={"workspaces": [{"id": 1, "name": "默认", "slug": "default"}]},
        ):
            with self.assertRaises(server.AnythingLLMError) as ctx:
                server._resolve_workspace("missing")
        self.assertEqual(ctx.exception.code, "ANYTHINGLLM_VALIDATION")
        self.assertIn("default", ctx.exception.detail)

    def test_upload_and_embed_calls_both_endpoints(self):
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path.endswith("/document/upload"):
                return {
                    "success": True,
                    "documents": [{"location": "custom-documents/demo.json"}],
                }
            return {"success": True}

        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "demo.md"
            source.write_text("hello", encoding="utf-8")
            with mock.patch.object(
                server, "_resolve_workspace", return_value=("default", "默认")
            ), mock.patch.object(
                server, "anythingllm_request", side_effect=fake_request
            ):
                result = server.upload_document(str(source))
        self.assertTrue(result["embedded"])
        self.assertEqual(result["location"], "custom-documents/demo.json")
        self.assertEqual([item[1] for item in calls], [
            "/api/v1/document/upload",
            "/api/v1/workspace/default/update-embeddings",
        ])
        self.assertIn(b'filename="demo.md"', calls[0][2]["data"])
        self.assertEqual(
            calls[1][2]["json_body"],
            {"adds": ["custom-documents/demo.json"], "deletes": []},
        )

    def test_ask_workspace_shape_and_mode(self):
        captured = {}

        def fake_request(method, path, **kwargs):
            captured.update({"method": method, "path": path, **kwargs})
            return {
                "id": "chat-1",
                "type": "textResponse",
                "textResponse": "答案",
                "sources": [{"title": "doc"}],
            }

        with mock.patch.object(
            server, "_resolve_workspace", return_value=("default", "默认")
        ), mock.patch.object(server, "anythingllm_request", side_effect=fake_request):
            result = server.ask_workspace("问题", mode="chat")
        self.assertEqual(result["textResponse"], "答案")
        self.assertEqual(result["sources"], [{"title": "doc"}])
        self.assertEqual(captured["json_body"], {"message": "问题", "mode": "chat"})
        self.assertEqual(captured["path"], "/api/v1/workspace/default/chat")


if __name__ == "__main__":
    unittest.main()

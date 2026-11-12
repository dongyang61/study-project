"""Textual TUI：只负责渲染 AgentSession 事件与用户输入。"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Static

from xAgent.agent import AgentSession, load_llm_config

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


class AgentApp(App):
    TITLE = "文件助手 Agent"
    CSS = """
    #log { height: 1fr; padding: 0 1; }
    #input { dock: bottom; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.session = AgentSession(
            load_llm_config(CONFIG_PATH), self._event, config_path=CONFIG_PATH
        )
        self._stream: Static | None = None
        self._buffer = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="log")
        yield Input(
            placeholder="输入消息；/compact /save /sessions /resume <id> /new /exit",
            id="input",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._add(
            Text(
                "输入 /exit 或 /quit 退出；/compact 压缩；/save 保存；"
                "/sessions 列出；/resume <id> 恢复；/new 新建。",
                style="dim",
            )
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.lower() in {"/exit", "/quit"}:
            self.exit()
            return
        if text.lower() == "/compact":
            self._add(Text("你: /compact", style="bold cyan"))
            event.input.disabled = True
            self._compact()
            return
        if text.lower() == "/save":
            self._add(Text("你: /save", style="bold cyan"))
            self.session.save_session()
            return
        if text.lower() == "/sessions":
            self._add(Text("你: /sessions", style="bold cyan"))
            self._add(Text(self.session.sessions_text(), style="dim"))
            return
        if text.lower() == "/new":
            self._add(Text("你: /new", style="bold cyan"))
            self.session.new_session()
            return
        if text.lower().startswith("/resume"):
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                self._add(Text("[会话] 用法：/resume <session-id>", style="red"))
                return
            self._add(Text(f"你: {text}", style="bold cyan"))
            event.input.disabled = True
            self._resume(parts[1].strip())
            return
        if text.lower() in {"/help", "help"}:
            self._add(
                Text(
                    "/compact 压缩；/save 保存；/sessions 列出；"
                    "/resume <id> 恢复；/new 新建；/exit 退出。",
                    style="dim",
                )
            )
            return
        if not self.session.accepts_input():
            self._add(Text(f"[上下文] {self.session.blocked_message()}", style="red"))
            return
        self._add(Text(f"你: {text}", style="bold cyan"))
        event.input.disabled = True
        self._run_turn(text)

    def _event(self, event: dict) -> None:
        self.call_from_thread(self._handle_event, event)

    @work(thread=True, exclusive=True)
    def _run_turn(self, text: str) -> None:
        try:
            self.session.run_turn(text)
        finally:
            self.call_from_thread(self._turn_done)

    @work(thread=True, exclusive=True)
    def _compact(self) -> None:
        try:
            self.session.compact()
        finally:
            self.call_from_thread(self._turn_done)

    @work(thread=True, exclusive=True)
    def _resume(self, session_id: str) -> None:
        try:
            self.session.resume(session_id)
        except Exception as exc:
            self.call_from_thread(self._add, Text(f"[会话] 恢复失败：{exc}", style="red"))
        finally:
            self.call_from_thread(self._turn_done)

    def _handle_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "text":
            self._append_stream(event["text"])
        elif kind == "tool_call":
            self._finish_stream()
            self._add(Text(f"[工具] {event['name']} {event['arguments']}", style="yellow"))
        elif kind == "warning":
            self._finish_stream()
            self._add(Text(f"[上下文] {event['message']}", style="red"))
        elif kind == "error":
            self._finish_stream()
            self._add(Text(f"请求失败：{event['message']}", style="red"))
        elif kind == "compact_start":
            self._finish_stream()
            self._add(Text("正在压缩上下文……", style="dim"))
        elif kind == "compact_done":
            self._add(Text(f"压缩完成，原始记录已保存：{event['path']}", style="green"))
        elif kind == "compact_error":
            self._add(Text(f"{event['message']}，原上下文保持不变，可重试 /compact。", style="red"))
        elif kind == "limit":
            self._finish_stream()
            self._add(
                Text(
                    f"[限制] {event['reason']}，工具循环已停止（共 {event['steps']} 步）。",
                    style="red",
                )
            )
        elif kind == "session_saved":
            self._add(Text(f"[会话] 已保存：{event['path']}", style="green"))
        elif kind == "session_resumed":
            self._add(
                Text(
                    f"[会话] 已恢复 {event['id']}：{event['messageCount']} 条消息，"
                    f"工作目录 {event['cwd']}",
                    style="green",
                )
            )
        elif kind == "session_new":
            self._add(Text(f"[会话] 已新建 {event['id']}", style="green"))
        elif kind == "session_error":
            self._add(Text(f"[会话] {event['message']}", style="red"))

    def _append_stream(self, text: str) -> None:
        if self._stream is None:
            self._stream = Static()
            self.query_one("#log", VerticalScroll).mount(self._stream)
            self._buffer = "AI: "
        self._buffer += text
        self._stream.update(Text(self._buffer))

    def _finish_stream(self) -> None:
        if self._stream is not None:
            self._stream = None
            self._buffer = ""

    def _turn_done(self) -> None:
        self._finish_stream()
        box = self.query_one(Input)
        box.disabled = False
        box.focus()

    def _add(self, content: Text) -> None:
        log = self.query_one("#log", VerticalScroll)
        log.mount(Static(content))
        log.scroll_end(animate=False)


def main() -> None:
    AgentApp().run()
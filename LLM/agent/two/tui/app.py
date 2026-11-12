"""Textual TUI：只负责渲染 core 事件与用户输入。"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, Static

import core

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


class AgentApp(App):
    TITLE = "文件助手 Agent"
    CSS = """
    #log { height: 1fr; padding: 0 1; }
    #input { dock: bottom; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.llm = core.load_llm_config(CONFIG_PATH)
        self.messages: list[dict] = []
        self._stream: Static | None = None
        self._buffer = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="log")
        yield Input(placeholder="输入消息，/exit 退出", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(Input).focus()
        self._add(Text("输入 /exit 或 /quit 退出。", style="dim"))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.lower() in {"/exit", "/quit"}:
            self.exit()
            return
        self._add(Text(f"你: {text}", style="bold cyan"))
        event.input.disabled = True
        self._run_turn(text)

    @work(thread=True, exclusive=True)
    def _run_turn(self, text: str) -> None:
        def on_event(event: dict) -> None:
            self.call_from_thread(self._handle_event, event)

        try:
            core.run_turn(self.llm, self.messages, text, on_event)
        finally:
            self.call_from_thread(self._turn_done)

    def _handle_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "text":
            self._append_stream(event["text"])
        elif kind == "tool_call":
            self._finish_stream()
            self._add(Text(f"[工具] {event['name']} {event['arguments']}", style="yellow"))
        elif kind == "error":
            self._finish_stream()
            self._add(Text(f"请求失败：{event['message']}", style="red"))

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
    try:
        AgentApp().run()
    except core.ConfigError as exc:
        raise SystemExit(str(exc))
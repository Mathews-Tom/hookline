"""Tests for message formatting functions — pure functions, zero I/O."""
from __future__ import annotations

from typing import Any


class TestEsc:
    """Test HTML escaping."""

    def test_escapes_ampersand(self, hookline: Any) -> None:
        assert hookline._esc("a & b") == "a &amp; b"

    def test_escapes_angle_brackets(self, hookline: Any) -> None:
        assert hookline._esc("<script>") == "&lt;script&gt;"

    def test_empty_string(self, hookline: Any) -> None:
        assert hookline._esc("") == ""

    def test_no_escaping_needed(self, hookline: Any) -> None:
        assert hookline._esc("hello world") == "hello world"

    def test_combined_escaping(self, hookline: Any) -> None:
        assert hookline._esc("a & b < c > d") == "a &amp; b &lt; c &gt; d"


class TestTruncate:
    """Test text truncation."""

    def test_short_text_unchanged(self, hookline: Any) -> None:
        assert hookline._truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self, hookline: Any) -> None:
        assert hookline._truncate("hello", 5) == "hello"

    def test_long_text_truncated(self, hookline: Any) -> None:
        result = hookline._truncate("hello world this is long", 10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_newlines_replaced(self, hookline: Any) -> None:
        result = hookline._truncate("line1\nline2\nline3", 200)
        assert "\n" not in result

    def test_whitespace_stripped(self, hookline: Any) -> None:
        result = hookline._truncate("  hello  ", 200)
        assert result == "hello"


class TestStripHtml:
    """Test HTML tag stripping for plain text fallback."""

    def test_strips_tags(self, hookline: Any) -> None:
        assert hookline._strip_html("<b>bold</b>") == "bold"

    def test_strips_nested_tags(self, hookline: Any) -> None:
        result = hookline._strip_html("<b><i>text</i></b>")
        assert result == "text"

    def test_unescapes_entities(self, hookline: Any) -> None:
        result = hookline._strip_html("a &amp; b &lt; c &gt; d")
        assert result == "a & b < c > d"

    def test_empty_string(self, hookline: Any) -> None:
        assert hookline._strip_html("") == ""


class TestFormatFull:
    """Test full event formatting with box-drawing."""

    def test_stop_event_has_header_and_footer(self, hookline: Any) -> None:
        event = {"hook_event_name": "Stop", "cwd": "/test/proj", "stop_hook_active": False}
        result = hookline.format_full("Stop", event, "proj")
        assert "┌─" in result
        assert "└─" in result
        assert "✅" in result
        assert "Stop" in result

    def test_notification_event(self, hookline: Any) -> None:
        event = {"hook_event_name": "Notification", "message": "Hello"}
        result = hookline.format_full("Notification", event, "proj")
        assert "Hello" in result
        assert "blockquote" in result

    def test_includes_project_name(self, hookline: Any) -> None:
        event = {"hook_event_name": "Stop", "cwd": "/test/myproj"}
        result = hookline.format_full("Stop", event, "myproj")
        assert "myproj" in result


class TestFormatCompact:
    """Test compact single-line formatting."""

    def test_teammate_idle(self, hookline: Any) -> None:
        event = {"teammate_name": "researcher"}
        result = hookline.format_compact("TeammateIdle", event, "proj")
        assert "researcher" in result
        assert "idle" in result

    def test_unknown_event(self, hookline: Any) -> None:
        result = hookline.format_compact("CustomEvent", {}, "proj")
        assert "CustomEvent" in result


class TestFormatBody:
    """Test body formatting for different event types."""

    def test_stop_no_transcript(self, hookline: Any) -> None:
        event = {"stop_hook_active": False}
        result = hookline._format_body("Stop", event, "proj")
        assert "Run complete." in result

    def test_stop_with_active_hook(self, hookline: Any) -> None:
        event = {"stop_hook_active": True}
        result = hookline._format_body("Stop", event, "proj")
        assert "Stop hook was already active" in result

    def test_notification_body(self, hookline: Any) -> None:
        event = {"message": "Build done"}
        result = hookline._format_body("Notification", event, "proj")
        assert "Build done" in result

    def test_task_completed_body(self, hookline: Any) -> None:
        event = {"task_id": "3", "task_description": "Do stuff"}
        # Need to set up session state for task tracking
        result = hookline._format_body("TaskCompleted", event, "proj")
        assert "Task" in result
        assert "Do stuff" in result

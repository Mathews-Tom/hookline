"""Tests for JSONL transcript parsing and summary extraction."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _write_transcript(path: Path, entries: list[dict[str, Any]]) -> None:
    """Helper to write a JSONL transcript file."""
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestReadTranscriptTail:
    """Test _read_transcript_tail."""

    def test_empty_path_returns_empty(self, notify: Any) -> None:
        assert notify._read_transcript_tail("") == []

    def test_missing_file_returns_empty(self, notify: Any) -> None:
        assert notify._read_transcript_tail("/nonexistent/path.jsonl") == []

    def test_reads_valid_jsonl(self, notify: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "test.jsonl"
        entries = [
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}},
            {"message": {"role": "user", "content": [{"type": "text", "text": "Hi"}]}},
        ]
        _write_transcript(transcript, entries)
        result = notify._read_transcript_tail(str(transcript))
        assert len(result) == 2

    def test_skips_invalid_json_lines(self, notify: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "test.jsonl"
        transcript.write_text('{"valid": true}\nnot-json\n{"also_valid": true}\n')
        result = notify._read_transcript_tail(str(transcript))
        assert len(result) == 2


class TestExtractTranscriptSummary:
    """Test _extract_transcript_summary."""

    def test_empty_transcript(self, notify: Any) -> None:
        result = notify._extract_transcript_summary({})
        assert result == {"messages": [], "tool_summary": "", "errors": []}

    def test_extracts_assistant_messages(self, notify: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "test.jsonl"
        entries = [
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "First message"}]}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "Second message"}]}},
        ]
        _write_transcript(transcript, entries)
        result = notify._extract_transcript_summary({"transcript_path": str(transcript)})
        assert len(result["messages"]) == 2

    def test_extracts_tool_counts(self, notify: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "test.jsonl"
        entries = [
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Bash"},
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Bash"},
            ]}},
        ]
        _write_transcript(transcript, entries)
        result = notify._extract_transcript_summary({"transcript_path": str(transcript)})
        assert "3 tool calls" in result["tool_summary"]
        assert "Bash" in result["tool_summary"]

    def test_extracts_errors(self, notify: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "test.jsonl"
        entries = [
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "is_error": True, "content": "Command failed"},
            ]}},
        ]
        _write_transcript(transcript, entries)
        result = notify._extract_transcript_summary({"transcript_path": str(transcript)})
        assert len(result["errors"]) == 1
        assert "Command failed" in result["errors"][0]

    def test_cache_returns_same_result(self, notify: Any, tmp_path: Path) -> None:
        """Verify cache returns same result for same file mtime."""
        transcript = tmp_path / "test.jsonl"
        entries = [
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}},
        ]
        _write_transcript(transcript, entries)
        event = {"transcript_path": str(transcript)}

        result1 = notify._extract_transcript_summary(event)
        result2 = notify._extract_transcript_summary(event)
        assert result1 is result2  # same object from cache

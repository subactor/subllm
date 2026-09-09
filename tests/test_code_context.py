import subprocess

import pytest

from subllm.code_context import select_code_context
from subllm.errors import CompletionError


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def tracked(repo, name, content="export const value = 1;\n"):
    file = repo / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    subprocess.run(["git", "add", "--", name], cwd=repo, check=True)
    return file


def test_directory_reference_supplies_source_and_tests_without_unrelated_files(repo):
    tracked(repo, "services/gateway/src/server.mjs")
    tracked(repo, "services/gateway/tests/server.test.mjs")
    tracked(repo, "services/gateway-other/server.mjs")
    tracked(repo, "private/service.py")
    assert select_code_context(repo, "Fix `services/gateway` and run its tests.") == [
        "services/gateway/src/server.mjs", "services/gateway/tests/server.test.mjs",
    ]


def test_explicit_preallocated_ticket_files_are_available_without_adding_all_untracked(repo):
    ticket = repo / "project/ticket-012"
    ticket.mkdir(parents=True)
    (ticket / "intent.json").write_text('{"allowedPaths": ["src/**"]}')
    (ticket / "README.md").write_text("Ticket purpose")
    (repo / "untracked.py").write_text("private content")
    assert select_code_context(repo, "Update project/ticket-012/intent.json") == [
        "project/ticket-012/intent.json",
    ]


def test_context_excludes_secrets_symlinks_binary_and_external_paths(repo, tmp_path_factory):
    tracked(repo, "src/safe.py")
    tracked(repo, "src/.env.py", "private value")
    tracked(repo, "src/credentials.json", "private value")
    tracked(repo, "src/binary.py", "bad\x00content")
    external = tmp_path_factory.mktemp("external") / "external.py"
    external.write_text("private value")
    (repo / "src/linked.py").symlink_to(external)
    subprocess.run(["git", "add", "src/linked.py"], cwd=repo, check=True)
    assert select_code_context(repo, f"Edit src, ../external.py and {external}") == ["src/safe.py"]


def test_file_and_byte_limits_fail_before_invoking_editor(repo):
    tracked(repo, "src/a.py", "a" * 10)
    tracked(repo, "src/b.py", "b" * 10)
    with pytest.raises(CompletionError, match="context exceeds"):
        select_code_context(repo, "Edit src", max_files=1)
    with pytest.raises(CompletionError, match="context exceeds"):
        select_code_context(repo, "Edit src", max_bytes=15)


def test_urls_and_path_substrings_do_not_select_files(repo):
    tracked(repo, "src/server.py")
    assert select_code_context(repo, "See https://example.com/src/server.py and other/src") == []


def test_exact_filename_and_directory_reference_are_deduplicated(repo):
    tracked(repo, "src/server.py")
    assert select_code_context(repo, "Fix src/server.py within src.") == ["src/server.py"]

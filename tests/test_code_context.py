import subprocess
from pathlib import Path

import pytest

from subllm.code_context import select_code_context, write_aider_context_ignore
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


def test_unicode_word_is_not_a_directory_reference(repo):
    tracked(repo, "test/producer-coverage.test.mjs")
    tracked(repo, "src/server.py")
    assert select_code_context(
        repo, "Zaktualizuj testów ingest i src/server.py.",
    ) == ["src/server.py"]


def test_over_budget_bare_directory_falls_back_to_explicit_paths(repo):
    tracked(repo, "docs/README.md", "readme\n")
    tracked(repo, "docs/analysis/producer-auth.md", "analysis\n")
    for index in range(20):
        tracked(repo, f"test/extra-{index:02d}.mjs", "x" * 20)
    tracked(repo, "services/analytics/src/ops-sodl-ingest.mjs", "ingest\n")
    selected = select_code_context(
        repo,
        "See wellmanifest docs 0.1.0 and the test directory plus "
        "services/analytics/src/ops-sodl-ingest.mjs",
        max_files=5,
        max_bytes=400,
    )
    assert selected == ["services/analytics/src/ops-sodl-ingest.mjs"]


def test_discovery_projection_preserves_existing_restrictions_and_hides_other_files(repo, tmp_path_factory):
    tracked(repo, "src/server.py")
    tracked(repo, "src/restricted.py")
    tracked(repo, "README.md")
    tracked(repo, "TODO.md")
    original = repo / ".aiderignore"
    original.write_text("# operator restriction\nsrc/restricted.py\n")
    before = original.read_bytes()
    destination = tmp_path_factory.mktemp("private-editor") / "context.aiderignore"
    write_aider_context_ignore(repo, ["src/server.py", "src/restricted.py"], destination)
    assert destination.read_text() == (
        "# operator restriction\nsrc/restricted.py\n\n/README.md\n/TODO.md\n"
    )
    assert original.read_bytes() == before
    assert not (repo / "context.aiderignore").exists()


def test_discovery_projection_treats_tracked_filenames_as_literal_patterns(repo, tmp_path_factory):
    tracked(repo, "src/item[1]*?.py")
    tracked(repo, "src/with space.py")
    tracked(repo, "!notice.md")
    destination = tmp_path_factory.mktemp("private-editor") / "context.aiderignore"
    write_aider_context_ignore(repo, [], destination)
    assert destination.read_text().splitlines() == [
        "", "/!notice.md", r"/src/item\[1\]\*\?.py", r"/src/with\ space.py",
    ]


def test_discovery_projection_respects_an_operator_selected_ignore_file(repo, tmp_path_factory):
    tracked(repo, "src/server.py")
    (repo / "operator.ignore").write_text("src/server.py\n")
    destination = tmp_path_factory.mktemp("private-editor") / "context.aiderignore"
    write_aider_context_ignore(repo, ["src/server.py"], destination, original=Path("operator.ignore"))
    assert destination.read_text().startswith("src/server.py\n")


def test_discovery_projection_rejects_symlinked_rules_and_multiline_names(repo, tmp_path_factory):
    destination = tmp_path_factory.mktemp("private-editor") / "context.aiderignore"
    (repo / "rules").write_text("src/private.py\n")
    original = repo / ".aiderignore"
    original.symlink_to(repo / "rules")
    with pytest.raises(CompletionError, match="not a regular file"):
        write_aider_context_ignore(repo, [], destination)
    original.unlink()
    tracked(repo, "line\nbreak.py")
    with pytest.raises(CompletionError, match="unsupported filename"):
        write_aider_context_ignore(repo, [], destination)
    assert not destination.exists()

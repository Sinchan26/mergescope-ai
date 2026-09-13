from mergescope.domain.models import AgentReviewIssue, AgentRole, Category, Severity
from mergescope.services.diff_parser import parse_unified_patch, validate_findings


def finding(path: str, line: int, title: str = "Unchecked value") -> AgentReviewIssue:
    return AgentReviewIssue(
        file_path=path,
        line_number=line,
        severity=Severity.high,
        category=Category.correctness,
        title=title,
        message="The value is used before validation.",
        evidence="The added line calls the unsafe operation directly.",
        suggestion="Validate the value first.",
    )


def test_parser_tracks_only_added_lines_across_hunks() -> None:
    patch = """@@ -2,3 +2,4 @@
 keep
-old
+new
+extra
 end
@@ -20,1 +21,2 @@
 context
+added
"""

    parsed = parse_unified_patch(patch)

    assert parsed.changed_lines == {3, 4, 22}
    assert parsed.visible_lines[2] == "keep"
    assert parsed.visible_lines[22] == "added"
    assert "22: added" in (parsed.excerpt(22) or "")


def test_validator_rejects_unknown_paths_invalid_lines_and_duplicates() -> None:
    parsed = {"src/app.py": parse_unified_patch("@@ -4,1 +4,2 @@\n keep\n+unsafe()")}
    findings = [
        (AgentRole.code, finding("src/app.py", 5)),
        (AgentRole.testing, finding("src/app.py", 5)),
        (AgentRole.code, finding("src/app.py", 99, "Outside diff")),
        (AgentRole.code, finding("invented.py", 5, "Invented path")),
        (
            AgentRole.code,
            finding("src/app.py", 5, "Missing line").model_copy(update={"line_number": None}),
        ),
    ]

    accepted, rejected = validate_findings(findings, parsed)

    assert len(accepted) == 1
    assert rejected == 4
    assert accepted[0].agent is AgentRole.code
    assert accepted[0].line_validated is True
    assert "5: unsafe()" in (accepted[0].diff_excerpt or "")

import re
from dataclasses import dataclass, field

from mergescope.domain.models import AgentReviewIssue, AgentRole, PullRequestSnapshot, ReviewIssue

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class ParsedPatch:
    changed_lines: set[int] = field(default_factory=set)
    visible_lines: dict[int, str] = field(default_factory=dict)

    def excerpt(self, line_number: int, radius: int = 2) -> str | None:
        lines = [
            f"{number}: {self.visible_lines[number]}"
            for number in range(line_number - radius, line_number + radius + 1)
            if number in self.visible_lines
        ]
        return "\n".join(lines) or None


def parse_unified_patch(patch: str | None) -> ParsedPatch:
    parsed = ParsedPatch()
    if not patch:
        return parsed

    new_line: int | None = None
    for raw_line in patch.splitlines():
        header = HUNK_HEADER.match(raw_line)
        if header:
            new_line = int(header.group(1))
            continue
        if new_line is None or raw_line.startswith("\\"):
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            parsed.changed_lines.add(new_line)
            parsed.visible_lines[new_line] = raw_line[1:]
            new_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        else:
            content = raw_line[1:] if raw_line.startswith(" ") else raw_line
            parsed.visible_lines[new_line] = content
            new_line += 1
    return parsed


def parse_pull_request_patches(pull_request: PullRequestSnapshot) -> dict[str, ParsedPatch]:
    return {file.filename: parse_unified_patch(file.patch) for file in pull_request.files}


def validate_findings(
    findings: list[tuple[AgentRole, AgentReviewIssue]],
    parsed_patches: dict[str, ParsedPatch],
) -> tuple[list[ReviewIssue], int]:
    accepted: list[ReviewIssue] = []
    rejected = 0
    seen: set[tuple[str, int | None, str]] = set()

    for agent, finding in findings:
        patch = parsed_patches.get(finding.file_path)
        if patch is None:
            rejected += 1
            continue
        if finding.line_number is None or finding.line_number not in patch.changed_lines:
            rejected += 1
            continue
        duplicate_key = (
            finding.file_path,
            finding.line_number,
            re.sub(r"\W+", " ", finding.title.lower()).strip(),
        )
        if duplicate_key in seen:
            rejected += 1
            continue
        seen.add(duplicate_key)
        accepted.append(
            ReviewIssue(
                **finding.model_dump(),
                agent=agent,
                line_validated=True,
                diff_excerpt=patch.excerpt(finding.line_number),
            )
        )
    return accepted, rejected

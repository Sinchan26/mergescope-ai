from pathlib import Path

from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    AgentRole,
    Approval,
    Category,
    EvaluationStatus,
    ReviewIssue,
    ReviewResult,
    Severity,
)
from mergescope.services.evaluations import EvaluationService

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EvaluationOrchestrator:
    async def run(
        self, pull_request, context_sources, parsed_patches, ticket_reference, policy=None
    ):
        expected = {
            3: ("metrics/rates.py", 11, Category.correctness),
            4: ("api/admin.py", 19, Category.security),
            5: ("tools/diagnostics.py", 5, Category.security),
        }.get(pull_request.number)
        issues = []
        if expected:
            path, line, category = expected
            issues.append(
                ReviewIssue(
                    file_path=path,
                    line_number=line,
                    severity=Severity.high,
                    category=category,
                    title="Expected defect",
                    message="The labeled defect is present.",
                    evidence="Evaluation fixture evidence.",
                    suggestion="Correct the labeled defect.",
                    agent=AgentRole.code,
                    line_validated=True,
                    diff_excerpt="fixture",
                )
            )
        return (
            ReviewResult(
                summary="Evaluation result",
                approval=Approval.comment if issues else Approval.approve,
                confidence=0.9,
                issues=issues,
                positive_notes=[],
                reviewed_files=[file.filename for file in pull_request.files],
                skipped_files=[],
                agents_run=[AgentRole.code, AgentRole.synthesizer],
                rejected_issue_count=1 if pull_request.number == 5 else 0,
            ),
            100,
            50,
            10,
        )


async def test_evaluation_suite_measures_and_persists_metrics(tmp_path: Path) -> None:
    repository = ReviewRepository(tmp_path / "reviews.db")
    await repository.initialize()
    service = EvaluationService(
        repository=repository,
        orchestrator=EvaluationOrchestrator(),  # type: ignore[arg-type]
        dataset_path=PROJECT_ROOT / "evaluations/cases.json",
        model="evaluation-model",
        prompt_version="phase4-test",
        input_cost_per_million=2,
        output_cost_per_million=4,
    )

    summary = service.dataset_summary()
    run = await service.run()
    saved = await repository.list_evaluation_runs()

    assert summary.case_count == 6
    assert (summary.good_cases, summary.bad_cases, summary.adversarial_cases) == (2, 2, 2)
    assert run.status is EvaluationStatus.completed
    assert run.completed_cases == 6
    assert (run.true_positives, run.false_positives, run.false_negatives) == (3, 0, 0)
    assert run.precision == 1.0
    assert run.recall == 1.0
    assert run.invalid_line_rate == 0.25
    assert run.estimated_cost_usd == 0.0024
    assert saved.total == 1
    assert saved.items[0].results[4].invalid_findings == 1

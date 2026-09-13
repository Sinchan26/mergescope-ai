import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from mergescope.agents.review_graph import ReviewOrchestrator
from mergescope.db.repository import ReviewRepository
from mergescope.domain.models import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationCaseSummary,
    EvaluationCaseType,
    EvaluationDataset,
    EvaluationDatasetSummary,
    EvaluationRun,
    EvaluationStatus,
    ReviewPolicy,
)
from mergescope.services.diff_parser import parse_pull_request_patches

logger = logging.getLogger(__name__)


class EvaluationError(ValueError):
    pass


class EvaluationService:
    def __init__(
        self,
        *,
        repository: ReviewRepository,
        orchestrator: ReviewOrchestrator | None,
        dataset_path: Path,
        model: str,
        prompt_version: str,
        input_cost_per_million: float,
        output_cost_per_million: float,
    ) -> None:
        self.repository = repository
        self.orchestrator = orchestrator
        self.dataset_path = dataset_path
        self.model = model
        self.prompt_version = prompt_version
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self._lock = asyncio.Lock()

    @property
    def dataset_ready(self) -> bool:
        try:
            self.load_dataset()
        except EvaluationError:
            return False
        return True

    def load_dataset(self) -> EvaluationDataset:
        try:
            payload = json.loads(self.dataset_path.read_text(encoding="utf-8"))
            dataset = EvaluationDataset.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise EvaluationError(f"Invalid evaluation dataset: {exc}") from exc
        if not dataset.cases:
            raise EvaluationError("Evaluation dataset must contain at least one case.")
        case_ids = [case.id for case in dataset.cases]
        if len(case_ids) != len(set(case_ids)):
            raise EvaluationError("Evaluation case IDs must be unique.")
        for case in dataset.cases:
            parsed = parse_pull_request_patches(case.pull_request)
            for expected in case.expected_findings:
                patch = parsed.get(expected.path)
                if patch is None or expected.line not in patch.changed_lines:
                    raise EvaluationError(
                        f"Case {case.id} labels {expected.path}:{expected.line}, "
                        "which is not an added line."
                    )
        return dataset

    def dataset_summary(self) -> EvaluationDatasetSummary:
        dataset = self.load_dataset()
        return EvaluationDatasetSummary(
            version=dataset.version,
            case_count=len(dataset.cases),
            good_cases=sum(case.case_type is EvaluationCaseType.good for case in dataset.cases),
            bad_cases=sum(case.case_type is EvaluationCaseType.bad for case in dataset.cases),
            adversarial_cases=sum(
                case.case_type is EvaluationCaseType.adversarial for case in dataset.cases
            ),
            expected_finding_count=sum(len(case.expected_findings) for case in dataset.cases),
            cases=[
                EvaluationCaseSummary(
                    id=case.id,
                    name=case.name,
                    case_type=case.case_type,
                    description=case.description,
                    expected_finding_count=len(case.expected_findings),
                )
                for case in dataset.cases
            ],
        )

    async def run(self) -> EvaluationRun:
        if self.orchestrator is None:
            raise EvaluationError("OPENAI_API_KEY is required to run the evaluation suite.")
        if self._lock.locked():
            raise EvaluationError("An evaluation run is already in progress.")

        async with self._lock:
            dataset = self.load_dataset()
            run = EvaluationRun(
                id=str(uuid4()),
                status=EvaluationStatus.running,
                dataset_version=dataset.version,
                model=self.model,
                prompt_version=self.prompt_version,
                case_count=len(dataset.cases),
            )
            await self.repository.create_evaluation_run(run)
            log_context = {
                "event": "evaluation_started",
                "evaluation_run_id": run.id,
            }
            logger.info("Evaluation run started.", extra=log_context)
            try:
                for case in dataset.cases:
                    result = await self._run_case(case, run.id)
                    run.results.append(result)
                    if result.error_message is None:
                        run.completed_cases += 1
                    self._aggregate(run)
                    await self.repository.save_evaluation_run(run)
                run.status = (
                    EvaluationStatus.completed
                    if run.completed_cases == run.case_count
                    else EvaluationStatus.failed
                )
                if run.status is EvaluationStatus.failed:
                    run.error_message = "One or more evaluation cases failed to execute."
                run.completed_at = datetime.now(UTC)
                self._aggregate(run)
                await self.repository.save_evaluation_run(run)
                logger.info("Evaluation run finished.", extra=log_context)
                return run
            except asyncio.CancelledError:
                run.status = EvaluationStatus.failed
                run.error_message = "Evaluation was cancelled before completion."
                run.completed_at = datetime.now(UTC)
                await asyncio.shield(self.repository.save_evaluation_run(run))
                raise
            except Exception as exc:
                run.status = EvaluationStatus.failed
                run.error_message = str(exc)[:2_000]
                run.completed_at = datetime.now(UTC)
                await self.repository.save_evaluation_run(run)
                logger.exception("Evaluation run failed.", extra=log_context)
                raise EvaluationError(str(exc)) from exc

    async def _run_case(self, case: EvaluationCase, run_id: str) -> EvaluationCaseResult:
        log_context = {
            "event": "evaluation_case",
            "evaluation_run_id": run_id,
            "case_id": case.id,
        }
        try:
            parsed = parse_pull_request_patches(case.pull_request)
            result, input_tokens, output_tokens, latency_ms = await self.orchestrator.run(
                case.pull_request,
                [],
                parsed,
                f"EVAL-{case.id}",
                ReviewPolicy(),
            )
            true_positives, false_positives, false_negatives = self._match(case, result.issues)
            case_result = EvaluationCaseResult(
                case_id=case.id,
                case_name=case.name,
                case_type=case.case_type,
                true_positives=true_positives,
                false_positives=false_positives,
                false_negatives=false_negatives,
                invalid_findings=result.rejected_issue_count,
                accepted_findings=len(result.issues),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=self._cost(input_tokens, output_tokens),
            )
            logger.info("Evaluation case completed.", extra=log_context)
            return case_result
        except Exception as exc:
            logger.warning("Evaluation case failed: %s", exc, extra=log_context)
            return EvaluationCaseResult(
                case_id=case.id,
                case_name=case.name,
                case_type=case.case_type,
                true_positives=0,
                false_positives=0,
                false_negatives=len(case.expected_findings),
                invalid_findings=0,
                accepted_findings=0,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                estimated_cost_usd=0,
                error_message=str(exc)[:2_000],
            )

    @staticmethod
    def _match(case: EvaluationCase, issues) -> tuple[int, int, int]:
        remaining = list(case.expected_findings)
        true_positives = 0
        false_positives = 0
        for issue in issues:
            match_index = next(
                (
                    index
                    for index, expected in enumerate(remaining)
                    if expected.path == issue.file_path
                    and expected.line == issue.line_number
                    and expected.category is issue.category
                ),
                None,
            )
            if match_index is None:
                false_positives += 1
            else:
                true_positives += 1
                remaining.pop(match_index)
        return true_positives, false_positives, len(remaining)

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        cost = (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000
        return round(cost, 6)

    @staticmethod
    def _aggregate(run: EvaluationRun) -> None:
        run.true_positives = sum(result.true_positives for result in run.results)
        run.false_positives = sum(result.false_positives for result in run.results)
        run.false_negatives = sum(result.false_negatives for result in run.results)
        run.invalid_findings = sum(result.invalid_findings for result in run.results)
        run.accepted_findings = sum(result.accepted_findings for result in run.results)
        run.input_tokens = sum(result.input_tokens for result in run.results)
        run.output_tokens = sum(result.output_tokens for result in run.results)
        run.latency_ms = sum(result.latency_ms for result in run.results)
        run.estimated_cost_usd = round(sum(result.estimated_cost_usd for result in run.results), 6)
        precision_denominator = run.true_positives + run.false_positives
        recall_denominator = run.true_positives + run.false_negatives
        line_denominator = run.accepted_findings + run.invalid_findings
        run.precision = (
            round(run.true_positives / precision_denominator, 4) if precision_denominator else 1.0
        )
        run.recall = (
            round(run.true_positives / recall_denominator, 4) if recall_denominator else 1.0
        )
        run.invalid_line_rate = (
            round(run.invalid_findings / line_denominator, 4) if line_denominator else 0.0
        )

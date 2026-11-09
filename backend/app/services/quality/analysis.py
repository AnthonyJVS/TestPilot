"""The AI half of failure analysis, shared by test runs and the workflow node."""

from __future__ import annotations

import uuid

from app.domain.exceptions import AppError
from app.domain.failure import FailureAnalysisOutput
from app.services.ai import capabilities as caps
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.router import TaskRouter
from app.services.ai.types import Capability, CapabilityStatus, ImageInput, TaskCategory
from app.services.quality import prompts


async def vision_supported(router: TaskRouter, owner_id: uuid.UUID, task: TaskCategory) -> bool:
    """True only with evidence (provider metadata or a passed check) that the model sees images."""
    try:
        route = await router.resolve(owner_id, task)
    except AppError:
        return False
    vision = caps.load(route.model.capabilities)[Capability.VISION]
    return vision.status == CapabilityStatus.SUPPORTED


async def analyse(
    orchestrator: AIOrchestrator,
    owner_id: uuid.UUID,
    *,
    evidence: list[dict[str, str]],
    scenario: str,
    image: bytes | None,
) -> tuple[FailureAnalysisOutput, str]:
    result = await orchestrator.run_structured(
        owner_id,
        TaskCategory.FAILURE_ANALYSIS,
        system=prompts.ANALYSIS_SYSTEM,
        prompt=prompts.analysis_prompt(evidence, scenario, with_screenshot=image is not None),
        output_model=FailureAnalysisOutput,
        images=[ImageInput(data=image, mime_type="image/jpeg")] if image else (),
        origin="failure_analysis",
        max_output_tokens=4096,
    )
    valid_ids = {item["id"] for item in evidence}
    output = result.output
    for hypothesis in output.hypotheses:  # keep only citations that exist
        hypothesis.evidence_ids = [i for i in hypothesis.evidence_ids if i in valid_ids]
    return output, str(result.record.id)

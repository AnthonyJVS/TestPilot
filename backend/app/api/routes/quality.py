"""Failure analysis, repair proposals (approve/reject) and version rollback."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import Ctx, CurrentUser, DbSession
from app.api.dependencies.ai import Registry, get_orchestrator
from app.api.routes.executions import Runtime
from app.api.routes.testing import Plans, Projects
from app.infrastructure.database.models import FailureAnalysis, RepairProposal
from app.schemas.quality import (
    ApprovalOut,
    FailureAnalysisOut,
    FailureReviewOut,
    RejectIn,
    RepairProposalOut,
    RollbackOut,
)
from app.services.ai.orchestrator import AIOrchestrator
from app.services.ai.router import TaskRouter
from app.services.quality.quality_service import QualityService

router = APIRouter(tags=["quality"])


def get_quality_service(
    db: DbSession,
    runtime: Runtime,
    registry: Registry,
    orchestrator: Annotated[AIOrchestrator, Depends(get_orchestrator)],
    projects: Projects,
    plans: Plans,
) -> QualityService:
    return QualityService(
        db,
        artifacts_root=runtime.artifacts_root,
        orchestrator=orchestrator,
        router=TaskRouter(db, registry),
        projects=projects,
        plans=plans,
    )


Quality = Annotated[QualityService, Depends(get_quality_service)]


def _analysis_out(analysis: FailureAnalysis) -> FailureAnalysisOut:
    return FailureAnalysisOut.model_validate(analysis, from_attributes=True)


def _proposal_out(proposal: RepairProposal) -> RepairProposalOut:
    return RepairProposalOut.model_validate(proposal, from_attributes=True)


@router.post(
    "/executions/{execution_id}/failure-analysis",
    response_model=FailureAnalysisOut,
    status_code=status.HTTP_201_CREATED,
)
async def analyse_failure(
    execution_id: uuid.UUID, user: CurrentUser, quality: Quality, ctx: Ctx
) -> FailureAnalysisOut:
    """Collect evidence from a failed run and ask the routed AI model to explain it."""
    return _analysis_out(await quality.analyse_run(user.id, execution_id, ctx))


@router.get("/executions/{execution_id}/failure-analysis", response_model=FailureReviewOut)
async def get_failure_review(
    execution_id: uuid.UUID, user: CurrentUser, quality: Quality
) -> FailureReviewOut:
    analysis, proposals = await quality.latest(user.id, execution_id)
    return FailureReviewOut(
        analysis=_analysis_out(analysis) if analysis else None,
        proposals=[_proposal_out(p) for p in proposals],
    )


@router.post(
    "/failure-analyses/{analysis_id}/repair",
    response_model=RepairProposalOut,
    status_code=status.HTTP_201_CREATED,
)
async def propose_repair(
    analysis_id: uuid.UUID, user: CurrentUser, quality: Quality, ctx: Ctx
) -> RepairProposalOut:
    """Ask the AI for a minimal, validated test change. Nothing changes until it is approved."""
    return _proposal_out(await quality.propose_repair(user.id, analysis_id, ctx))


@router.post("/repair-proposals/{proposal_id}/approve", response_model=ApprovalOut)
async def approve_repair(
    proposal_id: uuid.UUID, user: CurrentUser, quality: Quality, ctx: Ctx
) -> ApprovalOut:
    proposal, version = await quality.approve(user.id, proposal_id, ctx)
    return ApprovalOut(
        proposal=_proposal_out(proposal), version_id=version.id, version=version.version
    )


@router.post("/repair-proposals/{proposal_id}/reject", response_model=RepairProposalOut)
async def reject_repair(
    proposal_id: uuid.UUID, body: RejectIn, user: CurrentUser, quality: Quality, ctx: Ctx
) -> RepairProposalOut:
    return _proposal_out(await quality.reject(user.id, proposal_id, body.note, ctx))


@router.post("/versions/{version_id}/rollback", response_model=RollbackOut)
async def rollback_version(
    version_id: uuid.UUID, user: CurrentUser, quality: Quality, ctx: Ctx, db: DbSession
) -> RollbackOut:
    """Make an earlier approved version the current one again (versions stay immutable)."""
    version = await quality.rollback(user.id, version_id, ctx)
    return RollbackOut(
        test_case_id=version.test_case_id, current_version_id=version.id, version=version.version
    )

"""评估接口：跑一轮 RAG 评估并持久化结果。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.orm import EvaluationRun
from app.models.schemas import EvalRunOut, EvalRunRequest, EvalRunResponse
from app.rag.evaluation import EvaluationService
from app.utils import new_id

router = APIRouter()


@router.post("/run", response_model=EvalRunResponse, status_code=status.HTTP_201_CREATED)
def run_evaluation(req: EvalRunRequest, db: Session = Depends(get_db)) -> EvalRunResponse:
    """对一组问答执行评估：检索指标 + 生成指标（LLM 判分）。"""
    questions = [{"question": q.question, "ground_truth": q.ground_truth} for q in req.questions]
    metrics, detail = EvaluationService().run(questions, top_k=req.top_k)

    run_id = new_id("eval")
    run = EvaluationRun(
        id=run_id,
        name=req.name,
        dataset_size=len(req.questions),
        metrics=metrics,
        detail=detail,
    )
    db.add(run)
    db.commit()

    return EvalRunResponse(
        run_id=run_id,
        name=req.name,
        metrics=metrics,
        dataset_size=len(req.questions),
        created_at=run.created_at,
    )


@router.get("/runs", response_model=list[EvalRunOut])
def list_evaluation_runs(limit: int = 50, db: Session = Depends(get_db)) -> list[EvaluationRun]:
    return db.query(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(min(limit, 200)).all()


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
def get_evaluation_run(run_id: str, db: Session = Depends(get_db)) -> EvalRunResponse:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估任务不存在")
    return EvalRunResponse(
        run_id=run.id,
        name=run.name,
        metrics=run.metrics or {},
        dataset_size=run.dataset_size,
        created_at=run.created_at,
    )

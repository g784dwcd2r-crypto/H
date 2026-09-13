"""Authenticated cited research; provider and corpus readiness are explicit."""

from fastapi import Body, Depends, FastAPI, HTTPException

from filings_hub.research_corpus import ResearchCorpus
from filings_hub.research_provider import ProviderUnavailable
from filings_hub.research_questions import Question, ResearchQuestions
from filings_hub.tenancy import SecurityError


def attach_research_question_routes(app: FastAPI, *, get_index, security, provider, auth, current_user):
    def service():
        return ResearchQuestions(ResearchCorpus(get_index()), security, provider)

    def invoke(method, *args):
        try:
            return method(*args)
        except SecurityError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        except ProviderUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/research/capabilities")
    def capabilities(_=Depends(auth)):
        return service().capabilities()

    @app.post("/research/runs")
    def create(question: Question, user=Depends(current_user)):
        return invoke(service().create, question, user.id)

    @app.get("/research/runs/{ident}")
    def get(ident: str, user=Depends(current_user)):
        return invoke(service().get, ident, user.id)

    @app.post("/research/runs/{ident}/save")
    def save(ident: str, payload: dict = Body(...), user=Depends(current_user)):
        if set(payload) != {"project_id"} or not isinstance(payload["project_id"], str):
            raise HTTPException(422, "Select a project.")
        return invoke(service().save, ident, user.id, payload["project_id"])

    @app.post("/research/runs/{ident}/calculations")
    def calculate(ident: str, payload: dict = Body(...), user=Depends(current_user)):
        return invoke(service().calculate, ident, user.id, payload)

    @app.get("/projects/{project_id}/research-runs")
    def project_runs(project_id: str, user=Depends(current_user)):
        return invoke(service().list_project, project_id, user.id)

    @app.get("/research/spans/{ident}")
    def span(ident: str, _=Depends(auth)):
        record = service().corpus.span(ident)
        if record is None:
            raise HTTPException(404, "Research evidence not found.")
        return record

    @app.get("/research/projections/{ident}")
    def projection(ident: str, _=Depends(auth)):
        record = service().corpus.projection(ident)
        if record is None:
            raise HTTPException(404, "Research evidence projection not found.")
        return record

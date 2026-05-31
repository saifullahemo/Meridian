from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.core import projects
from backend.core.auth import require_api_key


router = APIRouter(prefix="/api/projects")


class ProjectRequest(BaseModel):
    name: str
    description: str = ""
    instructions: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    archived: bool | None = None


class ProjectChatRequest(BaseModel):
    instruction: str


class ProjectFileUpdateRequest(BaseModel):
    enabled: bool | None = None


class ProjectMemoryRequest(BaseModel):
    content: str
    kind: str = "note"


class ProjectQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    answer: bool = True


@router.get("")
def list_projects(_authorized: bool = Depends(require_api_key)):
    return {"success": True, "projects": projects.list_projects()}


@router.post("")
def create_project(req: ProjectRequest, _authorized: bool = Depends(require_api_key)):
    try:
        return {"success": True, "project": projects.create_project(req.name, req.description, req.instructions)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{project_id}")
def get_project(project_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        return {"success": True, "project": projects.get_project(project_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{project_id}")
def update_project(project_id: int, req: ProjectUpdateRequest, _authorized: bool = Depends(require_api_key)):
    patch: dict[str, Any] = {key: value for key, value in req.dict().items() if value is not None}
    try:
        return {"success": True, "project": projects.update_project(project_id, patch)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    confirm_name: str = Query(default=""),
    _authorized: bool = Depends(require_api_key),
):
    try:
        project = projects.get_project(project_id)
        if confirm_name != project["name"]:
            raise HTTPException(status_code=409, detail="Confirm the project name before deleting.")
        projects.delete_project(project_id)
        return {"success": True, "message": "Project deleted."}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id}/history")
def project_history(project_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        projects.get_project(project_id)
        return {"success": True, "history": projects.get_history(project_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/chat")
async def project_chat_form(
    project_id: int,
    instruction: str = Form(...),
    files: List[UploadFile] = File(default_factory=list),
    _authorized: bool = Depends(require_api_key),
):
    try:
        return projects.chat(project_id, instruction, files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{project_id}/chat-json")
def project_chat_json(project_id: int, req: ProjectChatRequest, _authorized: bool = Depends(require_api_key)):
    try:
        return projects.chat(project_id, req.instruction, [])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{project_id}/files")
def list_project_files(project_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        projects.get_project(project_id)
        return {"success": True, "files": projects.list_files(project_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/files")
async def upload_project_files(
    project_id: int,
    files: List[UploadFile] = File(...),
    _authorized: bool = Depends(require_api_key),
):
    try:
        return {"success": True, "files": projects.add_uploaded_files(project_id, files)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{project_id}/files/{file_id}")
def delete_project_file(project_id: int, file_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        projects.delete_file(project_id, file_id)
        return {"success": True, "message": "File removed from project."}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/{project_id}/files/{file_id}")
def update_project_file(
    project_id: int,
    file_id: int,
    req: ProjectFileUpdateRequest,
    _authorized: bool = Depends(require_api_key),
):
    try:
        return {"success": True, "file": projects.update_file(project_id, file_id, req.dict(exclude_none=True))}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id}/artifacts")
def project_artifacts(project_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        projects.get_project(project_id)
        return {"success": True, "artifacts": projects.list_artifacts(project_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id}/memory")
def project_memory(project_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        projects.get_project(project_id)
        return {"success": True, "memory": projects.list_memory(project_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/memory")
def add_project_memory(
    project_id: int,
    req: ProjectMemoryRequest,
    _authorized: bool = Depends(require_api_key),
):
    try:
        return {"success": True, "memory": projects.add_memory(project_id, req.content, req.kind)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{project_id}/memory/{memory_id}")
def delete_project_memory(project_id: int, memory_id: int, _authorized: bool = Depends(require_api_key)):
    try:
        projects.delete_memory(project_id, memory_id)
        return {"success": True, "message": "Project memory removed."}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/query")
def query_project(project_id: int, req: ProjectQueryRequest, _authorized: bool = Depends(require_api_key)):
    try:
        top_k = max(1, min(req.top_k, 10))
        return projects.query_project(project_id, req.query, top_k=top_k, answer=req.answer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

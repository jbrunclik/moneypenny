"""Todoist project, section and collaborator actions."""

from __future__ import annotations

from typing import Any

from src.agent.tools import todoist_client


def todoist_list_projects(token: str) -> dict[str, Any]:
    """List all projects with their full metadata."""
    projects = todoist_client.todoist_api_request("GET", "/projects", token)
    if not isinstance(projects, list):
        projects = []

    formatted_projects = []
    for p in projects:
        proj: dict[str, Any] = {
            "id": p["id"],
            "name": p["name"],
            "color": p.get("color"),
            "is_favorite": p.get("is_favorite", False),
        }
        # Include parent_id for nested project hierarchy
        if p.get("parent_id"):
            proj["parent_id"] = p["parent_id"]
        # View style (list or board) - useful for understanding project structure
        if p.get("view_style"):
            proj["view_style"] = p["view_style"]
        # Mark the inbox project for special handling (API v1: inbox_project)
        if p.get("inbox_project"):
            proj["is_inbox_project"] = True
        # Shared/collaborative projects
        if p.get("is_shared"):
            proj["is_shared"] = True
        formatted_projects.append(proj)

    return {
        "action": "list_projects",
        "count": len(formatted_projects),
        "projects": formatted_projects,
    }


def todoist_get_project(token: str, project_id: str) -> dict[str, Any]:
    """Fetch a single project by ID."""
    project = todoist_client.todoist_api_request("GET", f"/projects/{project_id}", token)
    if not isinstance(project, dict):
        raise Exception("Failed to fetch project")
    return {"action": "get_project", "project": project}


def todoist_add_project(
    token: str,
    project_name: str,
    color: str | None = None,
    parent_project_id: str | None = None,
    is_favorite: bool | None = None,
    view_style: str | None = None,
) -> dict[str, Any]:
    """Create a new Todoist project."""
    data: dict[str, Any] = {"name": project_name}
    if color:
        data["color"] = color
    if parent_project_id:
        data["parent_id"] = parent_project_id
    if is_favorite is not None:
        data["is_favorite"] = is_favorite
    if view_style:
        data["view_style"] = view_style

    project = todoist_client.todoist_api_request("POST", "/projects", token, data=data)
    if not isinstance(project, dict):
        raise Exception("Failed to create project")
    return {"action": "add_project", "success": True, "project": project}


def todoist_update_project(
    token: str,
    project_id: str,
    project_name: str | None = None,
    color: str | None = None,
    parent_project_id: str | None = None,
    is_favorite: bool | None = None,
    view_style: str | None = None,
) -> dict[str, Any]:
    """Update project metadata (name, color, favorite state, etc.)."""
    data: dict[str, Any] = {}
    if project_name:
        data["name"] = project_name
    if color:
        data["color"] = color
    if parent_project_id is not None:
        data["parent_id"] = parent_project_id
    if is_favorite is not None:
        data["is_favorite"] = is_favorite
    if view_style:
        data["view_style"] = view_style

    if not data:
        return {"error": "No project fields provided for update"}

    project = todoist_client.todoist_api_request(
        "POST", f"/projects/{project_id}", token, data=data
    )
    if not isinstance(project, dict):
        raise Exception("Failed to update project")
    return {"action": "update_project", "success": True, "project": project}


def todoist_delete_project(token: str, project_id: str) -> dict[str, Any]:
    """Delete a project permanently."""
    todoist_client.todoist_api_request("DELETE", f"/projects/{project_id}", token)
    return {
        "action": "delete_project",
        "success": True,
        "project_id": project_id,
        "message": "Project deleted",
    }


def todoist_archive_project(token: str, project_id: str) -> dict[str, Any]:
    """Archive a project to hide it from active view."""
    todoist_client.todoist_api_request("POST", f"/projects/{project_id}/archive", token)
    return {
        "action": "archive_project",
        "success": True,
        "project_id": project_id,
        "message": "Project archived",
    }


def todoist_unarchive_project(token: str, project_id: str) -> dict[str, Any]:
    """Bring an archived project back."""
    todoist_client.todoist_api_request("POST", f"/projects/{project_id}/unarchive", token)
    return {
        "action": "unarchive_project",
        "success": True,
        "project_id": project_id,
        "message": "Project unarchived",
    }


def todoist_list_sections(token: str, project_id: str) -> dict[str, Any]:
    """List all sections for a specific project.

    Sections help organize tasks within a project (e.g., "To Do", "In Progress", "Done").
    """
    sections = todoist_client.todoist_api_request(
        "GET", "/sections", token, params={"project_id": project_id}
    )
    if not isinstance(sections, list):
        sections = []

    formatted_sections = [
        {
            "id": s["id"],
            "name": s["name"],
            "order": s.get("section_order", 0),
        }
        for s in sections
    ]

    # Sort by order for logical display
    formatted_sections.sort(key=lambda s: s["order"])

    return {
        "action": "list_sections",
        "project_id": project_id,
        "count": len(formatted_sections),
        "sections": formatted_sections,
    }


def todoist_get_section(token: str, section_id: str) -> dict[str, Any]:
    """Fetch a section by ID."""
    section = todoist_client.todoist_api_request("GET", f"/sections/{section_id}", token)
    if not isinstance(section, dict):
        raise Exception("Failed to fetch section")
    return {"action": "get_section", "section": section}


def todoist_add_section(token: str, project_id: str, section_name: str) -> dict[str, Any]:
    """Create a new section inside a project."""
    data = {"project_id": project_id, "name": section_name}
    section = todoist_client.todoist_api_request("POST", "/sections", token, data=data)
    if not isinstance(section, dict):
        raise Exception("Failed to create section")
    return {"action": "add_section", "success": True, "section": section}


def todoist_update_section(token: str, section_id: str, section_name: str) -> dict[str, Any]:
    """Rename an existing section."""
    data = {"name": section_name}
    section = todoist_client.todoist_api_request(
        "POST", f"/sections/{section_id}", token, data=data
    )
    if not isinstance(section, dict):
        raise Exception("Failed to update section")
    return {"action": "update_section", "success": True, "section": section}


def todoist_delete_section(token: str, section_id: str) -> dict[str, Any]:
    """Delete a section from a project."""
    todoist_client.todoist_api_request("DELETE", f"/sections/{section_id}", token)
    return {
        "action": "delete_section",
        "success": True,
        "section_id": section_id,
        "message": "Section deleted",
    }


def todoist_list_collaborators(token: str, project_id: str) -> dict[str, Any]:
    """List all collaborators for a shared project.

    Returns information about who can be assigned tasks in the project.
    """
    collaborators = todoist_client.todoist_api_request(
        "GET", f"/projects/{project_id}/collaborators", token
    )
    if not isinstance(collaborators, list):
        collaborators = []

    formatted_collaborators = [
        {
            "id": c["id"],
            "name": c["name"],
            "email": c["email"],
        }
        for c in collaborators
    ]

    return {
        "action": "list_collaborators",
        "project_id": project_id,
        "count": len(formatted_collaborators),
        "collaborators": formatted_collaborators,
    }

"""
Compute priority management tools.
"""

from .. import state
from ..api_client import api_get, api_put
from ..mcp_app import mcp


@mcp.tool()
def kompany_compute_priority_get() -> str:
    """Get the compute priority order for the current project.

    Returns the ordered list of compute IDs that determines where tasks run.
    First available compute in the list is used.
    """
    if not state.CURRENT_PROJECT_ID:
        return "⚠️ No project focused. Use `kompany_project_focus <project_id>` first."

    try:
        result = api_get(f"/api/compute-priority?project_id={state.CURRENT_PROJECT_ID}")
        priority = result.get("compute_priority", [])

        if not priority:
            return f"No compute priority set for **{state.CURRENT_PROJECT_NAME}**. Tasks use the default recommendation engine.\n\nUse `kompany_compute_priority_set` to configure priority."

        output = f"# Compute Priority (Project: {state.CURRENT_PROJECT_NAME})\n\n"
        for i, compute_id in enumerate(priority, 1):
            output += f"{i}. `{compute_id}`\n"
        output += "\nFirst available compute in this order is used for new tasks."
        return output
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def kompany_compute_priority_set(compute_ids: str) -> str:
    """Set the compute priority order for the current project.

    Args:
        compute_ids: Comma-separated list of compute IDs in priority order.
                     Example: "comp_abc123,comp_def456,provider_vercel"
                     Use compute IDs from the Compute Pool (comp_xxx for local machines,
                     provider_vercel or provider_e2b for cloud providers).
    """
    if not state.CURRENT_PROJECT_ID:
        return "⚠️ No project focused. Use `kompany_project_focus <project_id>` first."

    priority = [cid.strip() for cid in compute_ids.split(",") if cid.strip()]
    if not priority:
        return "⚠️ Provide at least one compute ID."

    try:
        result = api_put("/api/compute-priority", {
            "project_id": state.CURRENT_PROJECT_ID,
            "compute_priority": priority
        })

        if result.get("success"):
            output = f"Compute priority updated for **{state.CURRENT_PROJECT_NAME}**:\n\n"
            for i, cid in enumerate(priority, 1):
                output += f"{i}. `{cid}`\n"
            return output
        return f"Failed: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error: {str(e)}"

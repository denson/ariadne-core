# Fix: Setup script install process — collision handling + MCP path

Two bugs exposed during REE deployment testing.

## Bug 1: Project name collision gives no useful information

When a project name already exists, the script just says "already exists" and offers update/rename/deploy-anyway. The user has no idea WHAT they're looking at — could be a running deployment, a deleted ghost, or an empty shell from a failed deploy.

### Fix

When a name collision is detected, query the matching project(s) and display:

```
  A project named "ree-research" already exists in this workspace.

  Existing projects with this name:

  1. ree-research (fb2b9c04)
     Status:   running (last deployed 2h ago)
     URL:      ariadne-core-production-b410.up.railway.app
     Services: ariadne-core, pgvector
     Docs:     5 documents across 3 collections

  2. ree-research (f0573785)
     Status:   empty (no deployments)
     Services: ariadne-core, pgvector
     
  3. ree-research (2de4d940)
     Status:   empty (no deployments)
     Services: ariadne-core, pgvector

  What would you like to do?
    [1] Update project 1 (fb2b9c04 — running)
    [2] Use a different name
    [3] Deploy as a new project (creates another "ree-research")
```

For each matching project, query and display:
- **Project ID** (short hash for identification)
- **Status**: Check latest deployment — "running" with time since deploy, "deploying", "failed", "empty" (no deployments), or "deleted" (if you can detect scheduled deletion)
- **URL**: The public domain if one exists
- **Services**: List service names
- **Health**: If running, hit `/api/health` and report healthy/unhealthy/unreachable
- **Document count**: If healthy, hit `/api/stats` and show total docs/collections (optional — skip if health fails)

If there's only one match and it's running+healthy, default to "Update" as option 1. If there are multiple matches, let the user pick which one.

### Where to change

`scripts/setup.py` — find the project collision handling section (search for "already exists"). Replace the simple 3-option prompt with the enriched display above.

You'll need to:
1. Query all projects in the workspace (already done — that's how collision is detected)
2. For each matching project, get its services, latest deployment status, and domain
3. Display the table
4. If user picks "Update", use that specific project ID

### GraphQL queries needed

For each matching project:
```graphql
# Get services
{ project(id: "...") { services { edges { node { id name } } } } }

# Get latest deployment status
{ deployments(input: { serviceId: "..." }, first: 1) { edges { node { status createdAt } } } }

# Get domain
{ service(id: "...") { serviceInstances { edges { node { domains { serviceDomains { domain } } } } } } }
```

Health check is just `curl https://{domain}/api/health`.

## Bug 2: MCP config defaults to wrong directory

The script asks where to write `.mcp.json` and defaults to the current directory. But the user runs the script from inside `ariadne-core/` (the cloned repo), so the MCP config lands in the tool's repo instead of the user's project root.

### Fix

When suggesting the default path for project-scoped MCP config, use the **parent directory** of where the script is running, not the current directory.

```python
# Current (wrong):
default_path = Path.cwd()

# Fixed:
# The script lives at ariadne-core/scripts/setup.py
# The user's project is one level above ariadne-core/
script_dir = Path(__file__).resolve().parent  # scripts/
repo_dir = script_dir.parent                  # ariadne-core/
project_dir = repo_dir.parent                 # the user's project
default_path = project_dir
```

Display it as:

```
  Where should this MCP connection be available in?
  (This is where you'll run Claude Code to work with your documents)

  Suggested: D:\video_projects\world_bank_project_reports
  (parent of the ariadne-core repo you cloned into)

  Press Enter to accept, or type a different path:
```

### Where to change

`scripts/setup.py` — find where it prompts for the MCP project directory path (search for "project directory" or "MCP connection" or the path prompt). Change the default from `Path.cwd()` to the parent-of-repo calculation above.

## Do not touch

- SPEC.md, skills, docs
- Any files outside `scripts/setup.py`

## Do not commit

Report when done. Leave for Bob.

1. Search the current directory and its ancestors for `.phn.json`.
2. Read `phn_project_id`, `phn_api`, and `phn_web`. Pass the project id to
   every project-scoped MCP call.
3. If the id is `null`, call `list_projects`, compare the folder name with the
   returned project names/BT numbers, and ask the user to choose if more than
   one match is plausible. Update only `phn_project_id` in `.phn.json` after
   confirmation; preserve the URLs.
4. If a call returns `project_not_found` / `refresh`, re-run `list_projects`
   and re-resolve the marker. Do not claim this proves a permissions failure.

# BLDGTYP Project Folder

This is a BLDGTYP Passive House consulting project working folder. Use the
installed `/bldgtyp:phn` skill and `phn` MCP server for PH-Navigator project data. If the PHN credential is missing, run `/bldgtyp:phn-login`;
never paste or store a token in this project folder.

## Resolve the PH-Navigator project

1. Search the current directory and its ancestors for `.phn.json`.
2. Read `phn_project_id`, `phn_api`, and `phn_web`. Pass the project id to
   every project-scoped MCP call.
3. If the id is `null`, call `list_projects`, compare the folder name with the
   returned project names/BT numbers, and ask the user to choose if more than
   one match is plausible. Update only `phn_project_id` in `.phn.json` after
   confirmation; preserve the URLs.
4. If a call returns `project_not_found` / `refresh`, re-run `list_projects`
   and re-resolve the marker. Do not claim this proves a permissions failure.

## Folder map

- `01_Reference` — incoming reference documents
- `02_Admin` — project administration
- `03_Submissions` — outgoing and received submissions
- `04_Web` — web-report files
- `05_Rhino` — Rhino models
- `06_GH` — Grasshopper files
- `07_PHPP` — PHPP models and exports
- `08_DesignPH` — designPH files
- `09_Flixo` — thermal-bridge models
- `10_Certification` — Passive House certification documents
- `11_QAQC` — QA/QC records
- `12_HVAC` — mechanical-system documents
- `13_WUFI` — WUFI files
- `14_HBJSON` — Honeybee JSON models

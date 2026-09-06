from __future__ import annotations

from worldloom.connector_definition import builtin_connector_definitions

# Extracted from the user-supplied results-100k.jsonl.gz: 100,001 rows,
# 73 distinct executed tool names. This is a compact regression oracle for the
# existing benchmark surface without checking a multi-megabyte result file into
# the package.
EXPECTED_100K_TOOLS = {
    "jira.create_issue",
    "sharepoint.create_file",
    "drive.get_file",
    "jira.search_issues",
    "sharepoint.get_file",
    "confluence.create_page",
    "salesforce.update_record",
    "servicenow.create_record",
    "salesforce.get_record",
    "salesforce.query",
    "servicenow.search_records",
    "jira.update_issue",
    "confluence.get_page",
    "salesforce.create_task",
    "jira.get_issue",
    "servicenow.get_record",
    "drive.upload_file",
    "servicenow.update_record",
    "confluence.update_page",
    "salesforce.create_record",
    "servicenow.create_kb_article",
    "jira.add_comment",
    "confluence.create_blogpost",
    "confluence.add_comment",
    "drive.search",
    "sharepoint.update_file",
    "confluence.search",
    "drive.create_doc",
    "sharepoint.create_page",
    "servicenow.update_kb_article",
    "confluence.get_blogpost",
    "sharepoint.search_files",
    "drive.create_slides",
    "salesforce.run_report",
    "drive.create_sheet",
    "sharepoint.delete_list_item",
    "drive.update_file",
    "servicenow.get_kb_article",
    "confluence.upload_attachment",
    "servicenow.add_work_note",
    "drive.update_doc",
    "sharepoint.update_page",
    "sharepoint.get_page",
    "salesforce.add_case_comment",
    "drive.update_sheet",
    "salesforce.log_activity",
    "sharepoint.get_list_items",
    "jira.get_sprint",
    "servicenow.query_cmdb",
    "sharepoint.update_list_item",
    "servicenow.search_kb",
    "jira.transition_issue",
    "sharepoint.search_pages",
    "drive.update_slides",
    "servicenow.update_cmdb_ci",
    "servicenow.create_catalog_request",
    "sharepoint.create_list_item",
    "drive.create_folder",
    "confluence.get_comments",
    "confluence.update_attachment",
    "drive.move_file",
    "jira.get_comments",
    "sharepoint.convert_file",
    "confluence.get_attachment",
    "jira.get_attachment",
    "drive.export_file",
    "salesforce.get_dashboard",
    "drive.list_folder",
    "sharepoint.list_folder",
    "jira.update_sprint",
    "sharepoint.move_file",
    "sharepoint.create_folder",
    "jira.create_sprint",
}


def test_every_tool_observed_in_the_100k_run_is_definition_owned() -> None:
    definitions = builtin_connector_definitions()
    available = {
        f"{connector}.{tool}"
        for connector, definition in definitions.items()
        for tool in definition.tools
    }

    assert len(EXPECTED_100K_TOOLS) == 73
    assert EXPECTED_100K_TOOLS <= available

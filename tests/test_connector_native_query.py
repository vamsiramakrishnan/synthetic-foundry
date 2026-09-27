"""The shared vendor-query evaluator: golden trees, evaluation, vendor errors, determinism, the emulator opt-in."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from worldloom import packkit
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator, ConnectorError
from worldloom.connectors.query import (
    ELEMENT,
    And,
    AnyOf,
    Compare,
    In,
    IsEmpty,
    Not,
    Op,
    Or,
    OrderKey,
    Query,
    QueryError,
    TextMatch,
    TimeWindow,
    connector_search,
    execute,
    parse,
    run,
    target_for,
)

CLOCK = datetime.fromisoformat("2026-09-05T09:00:00+08:00")  # a Saturday, the shipped definitions' clock
SGT = timezone(timedelta(hours=8))


def at(*parts: int, tz: Any = SGT) -> datetime:
    return datetime(*parts, tzinfo=tz)


# ---------------------------------------------------------------------------
# Golden trees, one per language
# ---------------------------------------------------------------------------

GOLDEN = [
    (
        "jql",
        'project = PHX AND status IN ("To Do", Done) AND created >= -7d ORDER BY created DESC',
        Query(
            language="jql",
            where=And((
                Compare("project", Op.EQ, "PHX"),
                In("status", ("To Do", "Done")),
                Compare("created", Op.GE, at(2026, 8, 29, 9)),
            )),
            order=(OrderKey("created", True),),
        ),
    ),
    (
        "jql",
        'text ~ "checkout" OR NOT assignee = currentUser() AND updated < startOfWeek(-1) AND labels IS NOT EMPTY',
        Query(
            language="jql",
            where=Or((
                TextMatch(None, "checkout"),
                And((
                    Not(Compare("assignee", Op.EQ, "agent")),
                    Compare("updated", Op.LT, at(2026, 8, 23)),
                    Not(IsEmpty("labels")),
                )),
            )),
        ),
    ),
    (
        "soql",
        "SELECT Id, Name, Account.Name FROM Opportunity WHERE StageName = 'Closed Won' AND CloseDate = THIS_QUARTER "
        "AND Amount >= 100000 ORDER BY Amount DESC NULLS LAST LIMIT 5 OFFSET 2",
        Query(
            language="soql",
            where=And((
                Compare("StageName", Op.EQ, "Closed Won"),
                TimeWindow("CloseDate", at(2026, 7, 1), at(2026, 10, 1)),
                Compare("Amount", Op.GE, 100000),
            )),
            source="Opportunity",
            order=(OrderKey("Amount", True, False),),
            limit=5,
            offset=2,
            select=("Id", "Name", "Account.Name"),
        ),
    ),
    (
        "soql",
        "SELECT Id FROM Case WHERE (Status != 'Closed' OR Priority IN ('High')) AND Subject LIKE '%outage%' "
        "AND CreatedDate = LAST_N_DAYS:30 AND Tags__c INCLUDES ('a;b', 'c')",
        Query(
            language="soql",
            where=And((
                Or((
                    Compare("Status", Op.NE, "Closed", missing_matches=True),
                    In("Priority", ("High",)),
                )),
                TextMatch("Subject", "%outage%", "like"),
                TimeWindow("CreatedDate", at(2026, 8, 6), at(2026, 9, 6)),
                Or((
                    And((AnyOf("Tags__c", Compare(ELEMENT, Op.EQ, "a")), AnyOf("Tags__c", Compare(ELEMENT, Op.EQ, "b")))),
                    AnyOf("Tags__c", Compare(ELEMENT, Op.EQ, "c")),
                )),
            )),
            source="Case",
            select=("Id",),
        ),
    ),
    (
        "encoded_query",
        "priority=1^ORpriority=2^stateNOT IN6,7^short_descriptionLIKEcheckout"
        "^sys_created_on>javascript:gs.daysAgoStart(7)^NQcategory=network^ORDERBYDESCsys_created_on",
        Query(
            language="encoded_query",
            where=Or((
                And((
                    Or((Compare("priority", Op.EQ, "1"), Compare("priority", Op.EQ, "2"))),
                    Not(In("state", ("6", "7"))),
                    TextMatch("short_description", "checkout", "contains"),
                    Compare("sys_created_on", Op.GT, at(2026, 8, 29)),
                )),
                Compare("category", Op.EQ, "network"),
            )),
            order=(OrderKey("sys_created_on", True),),
        ),
    ),
    (
        "odata",
        "$filter=startswith(subject,'Q3') and receivedDateTime ge 2026-09-01T00:00:00Z and categories/any(c:c eq 'Red')"
        " and not (importance eq 'low')&$orderby=receivedDateTime desc&$top=5&$select=subject",
        Query(
            language="odata",
            where=And((
                TextMatch("subject", "Q3", "startswith"),
                Compare("receivedDateTime", Op.GE, at(2026, 9, 1, tz=UTC)),
                AnyOf("categories", Compare(ELEMENT, Op.EQ, "Red")),
                Not(Compare("importance", Op.EQ, "low")),
            )),
            order=(OrderKey("receivedDateTime", True),),
            limit=5,
            select=("subject",),
        ),
    ),
    (
        "cql",
        'space = ENG AND type = page AND text ~ "data residency" AND lastmodified > now("-4w") ORDER BY lastmodified DESC',
        Query(
            language="cql",
            where=And((
                Compare("space", Op.EQ, "ENG"),
                Compare("type", Op.EQ, "page"),
                TextMatch(None, "data residency"),
                Compare("lastmodified", Op.GT, at(2026, 8, 8, 9)),
            )),
            order=(OrderKey("lastmodified", True),),
        ),
    ),
    (
        "kql",
        'budget "quarterly review" filetype:docx LastModifiedTime>=2026-08-01 NOT draft',
        Query(
            language="kql",
            where=And((
                TextMatch(None, "budget"),
                TextMatch(None, "quarterly review", "phrase"),
                TextMatch("filetype", "docx"),
                TimeWindow("LastModifiedTime", at(2026, 8, 1), None),
                Not(TextMatch(None, "draft")),
            )),
        ),
    ),
    (
        "drive_q",
        "name contains 'Budget' and modifiedTime > '2026-08-01T00:00:00' and '1abc' in parents and not trashed = true",
        Query(
            language="drive_q",
            where=And((
                TextMatch("name", "Budget", "prefix"),
                Compare("modifiedTime", Op.GT, at(2026, 8, 1, tz=UTC)),
                AnyOf("parents", Compare(ELEMENT, Op.EQ, "1abc", case_sensitive=True)),
                Not(Compare("trashed", Op.EQ, True)),
            )),
        ),
    ),
    (
        "slack_search",
        'in:#incidents from:@maria "checkout down" after:2026-09-01 -resolved',
        Query(
            language="slack_search",
            where=And((
                Compare("in", Op.EQ, "incidents"),
                Compare("from", Op.EQ, "maria"),
                TextMatch(None, "checkout down", "phrase"),
                TimeWindow("timestamp", at(2026, 9, 2), None),
                Not(TextMatch(None, "resolved")),
            )),
        ),
    ),
]


@pytest.mark.parametrize(("language", "text", "expected"), GOLDEN, ids=[f"{row[0]}-{i}" for i, row in enumerate(GOLDEN)])
def test_each_language_parses_into_the_golden_tree(language: str, text: str, expected: Query) -> None:
    assert parse(language, text, clock=CLOCK, user="agent") == expected


def test_relative_time_resolves_against_the_clock_given_never_the_wall_clock() -> None:
    later = CLOCK + timedelta(days=30)
    for language, text in (("jql", "created >= -7d"), ("soql", "SELECT Id FROM Case WHERE CreatedDate = TODAY"),
                           ("encoded_query", "sys_created_on>javascript:gs.daysAgo(1)"),
                           ("cql", 'created > now("-1w")'), ("slack_search", "on:yesterday")):
        first = parse(language, text, clock=CLOCK)
        assert first == parse(language, text, clock=CLOCK)
        assert first != parse(language, text, clock=later)


def test_the_calendar_helpers_follow_each_vendor() -> None:
    jql = parse("jql", "due <= endOfMonth(-1) AND created >= startOfMonth(\"+14d\")", clock=CLOCK)
    assert jql.where == And((
        Compare("due", Op.LE, at(2026, 8, 31, 23, 59, 59, 999999)),
        Compare("created", Op.GE, at(2026, 9, 15)),
    ))
    # ServiceNow weeks start on Monday; beginningOfThisWeek on a Saturday is five days back.
    snow = parse("encoded_query", "opened_at>=javascript:gs.beginningOfThisWeek()", clock=CLOCK)
    assert snow.where == Compare("opened_at", Op.GE, at(2026, 8, 31))
    soql = parse("soql", "SELECT Id FROM Case WHERE CreatedDate > LAST_WEEK", clock=CLOCK)
    assert soql.where == TimeWindow("CreatedDate", at(2026, 8, 30), None)


# ---------------------------------------------------------------------------
# Evaluation over a small built corpus
# ---------------------------------------------------------------------------


def _jira() -> list[dict[str, Any]]:
    summaries = ["Checkout outage in payments", "Login slow for staff", "Checkout button misaligned", "Payments reconciliation drift"]
    return [
        {
            "fid": f"jr:{index:02d}", "entity": "bug" if index % 2 else "story", "ident": f"PHX-{100 + index}",
            "summary": summaries[index % 4], "project": "PHX" if index < 6 else "OPS",
            "status": {"name": "Done"} if index % 3 == 0 else "In Progress", "priority": "High" if index % 2 else "Low",
            "assignee": "agent" if index in (1, 4) else None, "labels": ["payments"] if index % 4 in (0, 3) else [],
            "created_at": f"2026-09-0{1 + index % 5}T10:00:00+08:00",
        }
        for index in range(8)
    ]


def _keys(result: Any, records: list[dict[str, Any]], key: str = "ident") -> list[str]:
    return [records[index][key] for index in result.matches]


def _run(connector: str, text: str, records: list[dict[str, Any]], *, entity: str | None = None, language: str | None = None) -> Any:
    definition = load_connector_definition(connector)
    target = target_for(definition, language=language, entity=entity, records=records)
    return run(language or definition.query_language, text, records, target, clock=CLOCK, user="agent")


@pytest.mark.parametrize(("text", "expected"), [
    ("project = PHX AND status = done", ["PHX-100", "PHX-103"]),
    ("status != Done AND priority = High ORDER BY created ASC, key DESC", ["PHX-105", "PHX-101", "PHX-107"]),
    ("assignee = currentUser()", ["PHX-101", "PHX-104"]),
    ("assignee IS EMPTY AND project = OPS", ["PHX-106", "PHX-107"]),
    ("labels = payments AND NOT project = OPS", ["PHX-100", "PHX-103", "PHX-104"]),
    ("issuetype = Bug AND created >= -3d", ["PHX-101", "PHX-103", "PHX-107"]),
    ("summary ~ \"checkout\" ORDER BY created DESC", ["PHX-104", "PHX-102", "PHX-106", "PHX-100"]),
    ("summary !~ checkout AND key in (PHX-101, PHX-103, PHX-104)", ["PHX-101", "PHX-103"]),
    ("summary ~ \"pay*\"", ["PHX-100", "PHX-103", "PHX-104", "PHX-107"]),
])
def test_jql_evaluates_over_records(text: str, expected: list[str]) -> None:
    records = _jira()
    assert _keys(_run("jira", text, records), records) == expected


def test_free_text_ranks_by_bm25_with_ties_broken_by_id() -> None:
    records = _jira()
    result = _run("jira", 'text ~ "checkout outage"', records)
    # PHX-100 and PHX-104 have the same summary, so the same score: the id decides.
    assert _keys(result, records) == ["PHX-100", "PHX-104"]
    assert result.scores[0] == result.scores[1] > 0
    shuffled = list(reversed(records))
    assert _keys(_run("jira", 'text ~ "checkout outage"', shuffled), shuffled) == ["PHX-100", "PHX-104"]


def _salesforce() -> list[dict[str, Any]]:
    rows = [
        ("0061", "Stark renewal", "Closed Won", 250000, "Stark Retail", "2026-08-15", ["a", "b"]),
        ("0062", "Wayne expansion", "Prospecting", 90000, "Wayne Corp", "2026-09-20", ["b"]),
        ("0063", "Acme pilot", "Closed Won", 120000, "Acme", "2026-06-30", []),
        ("0064", "Stark services", "Negotiation", None, "Stark Retail", "2026-09-02", "a;b"),
    ]
    return [
        {"fid": f"sf:{ident}", "entity": "opportunity", "ident": ident, "name": name, "stage": stage,
         "amount": amount, "company": company, "close": close, "tags": tags}
        for ident, name, stage, amount, company, close, tags in rows
    ]


@pytest.mark.parametrize(("text", "expected"), [
    ("SELECT Id FROM Opportunity WHERE StageName = 'closed won' ORDER BY Amount DESC", ["0061", "0063"]),
    ("SELECT Id FROM Opportunity WHERE CloseDate = THIS_QUARTER AND Account.Name LIKE 'stark%'", ["0061", "0064"]),
    ("SELECT Id FROM Opportunity WHERE Amount != 90000 ORDER BY Amount ASC NULLS LAST", ["0063", "0061", "0064"]),
    ("SELECT Id FROM Opportunity WHERE NOT (StageName IN ('Closed Won', 'Negotiation'))", ["0062"]),
    ("SELECT Id FROM Opportunity ORDER BY CloseDate DESC LIMIT 2 OFFSET 1", ["0064", "0061"]),
    ("SELECT Id FROM Opportunity WHERE tags INCLUDES ('a;b')", ["0061", "0064"]),
    ("SELECT Id FROM Opportunity WHERE CloseDate < 2026-07-01", ["0063"]),
])
def test_soql_evaluates_over_records(text: str, expected: list[str]) -> None:
    records = _salesforce()
    assert _keys(_run("salesforce", text, records, entity="opportunity"), records) == expected


def _servicenow() -> list[dict[str, Any]]:
    return [
        {"fid": "sn:1", "entity": "incident", "number": "INC0000001", "short_description": "Checkout API outage",
         "priority": "1", "state": "In Progress", "assignment_group": "Major Incident Management",
         "opened_at": "2026-09-04T08:00:00+08:00"},
        {"fid": "sn:2", "entity": "incident", "number": "INC0000002", "short_description": "Printer jam",
         "priority": "4", "state": "Resolved", "assignment_group": "Service Desk", "opened_at": "2026-08-01T08:00:00+08:00"},
        {"fid": "sn:3", "entity": "incident", "number": "INC0000003", "short_description": "Checkout latency",
         "priority": "2", "state": "In Progress", "assignment_group": "", "opened_at": "2026-09-01T08:00:00+08:00"},
    ]


@pytest.mark.parametrize(("text", "expected"), [
    ("priority=1^ORpriority=2^ORDERBYopened_at", ["INC0000003", "INC0000001"]),
    ("short_descriptionLIKEcheckout^opened_at>javascript:gs.daysAgoStart(2)", ["INC0000001"]),
    ("assignment_groupISEMPTY^NQpriorityIN4,5", ["INC0000002", "INC0000003"]),
    ("priorityBETWEEN1@2^stateSTARTSWITHin^ORDERBYDESCnumber", ["INC0000003", "INC0000001"]),
    ("sys_created_onONThis week@javascript:gs.beginningOfThisWeek()@javascript:gs.endOfThisWeek()", ["INC0000001", "INC0000003"]),
    ("sys_created_onNOTONThis week@javascript:gs.beginningOfThisWeek()@javascript:gs.endOfThisWeek()", ["INC0000002"]),
])
def test_encoded_query_evaluates_over_records(text: str, expected: list[str]) -> None:
    records = _servicenow()
    assert _keys(_run("servicenow", text, records, entity="incident"), records, "number") == expected


def test_servicenow_drops_an_unknown_field_as_servicenow_does() -> None:
    records = _servicenow()
    dropped = _run("servicenow", "no_such_field=7^priority=1", records, entity="incident")
    assert _keys(dropped, records, "number") == ["INC0000001"]
    either = _run("servicenow", "priority=1^ORno_such_field=7", records, entity="incident")
    assert _keys(either, records, "number") == ["INC0000001"]
    ordered = _run("servicenow", "ORDERBYno_such_field", records, entity="incident")
    assert ordered.total == 3


def _messages() -> list[dict[str, Any]]:
    return [
        {"fid": "m1", "entity": "message", "ident": "m1", "subject": "Q3 forecast", "from": "cfo@stark.example",
         "sent_at": "2026-09-02T09:00:00Z", "categories": ["Red", "Finance"], "importance": "high", "body": "Forecast attached"},
        {"fid": "m2", "entity": "message", "ident": "m2", "subject": "q3 offsite", "from": "hr@stark.example",
         "sent_at": "2026-08-20T09:00:00Z", "categories": ["Blue"], "importance": "low", "body": "Agenda for the offsite"},
        {"fid": "m3", "entity": "message", "ident": "m3", "subject": "Incident review", "from": "sre@stark.example",
         "sent_at": "2026-09-03T09:00:00Z", "categories": [], "importance": "normal", "body": "Checkout forecast impact"},
    ]


@pytest.mark.parametrize(("text", "expected"), [
    ("startswith(subject,'Q3')", ["m1", "m2"]),
    ("$filter=receivedDateTime ge 2026-09-01T00:00:00Z&$orderby=receivedDateTime desc", ["m3", "m1"]),
    ("categories/any(c:c eq 'red') or importance eq 'normal'", ["m1", "m3"]),
    ("from/emailAddress/address eq 'hr@stark.example' or contains(subject,'incident')", ["m2", "m3"]),
    ("$search=\"forecast\"&$top=1", ["m1"]),
    ("not (importance in ('low','normal'))", ["m1"]),
])
def test_odata_evaluates_over_records(text: str, expected: list[str]) -> None:
    records = _messages()
    assert _keys(_run("outlook", text, records, entity="message"), records) == expected


def test_cql_kql_drive_and_slack_evaluate_over_records() -> None:
    pages = [
        {"fid": "p1", "entity": "page", "ident": "101", "title": "Data residency policy", "space": "ENG",
         "body": "Where customer data may be stored", "labels": ["policy"], "modified_at": "2026-09-01T10:00:00+08:00"},
        {"fid": "p2", "entity": "page", "ident": "102", "title": "Runbook", "space": "OPS",
         "body": "data residency exceptions", "labels": [], "modified_at": "2026-07-01T10:00:00+08:00"},
        {"fid": "p3", "entity": "blogpost", "ident": "103", "title": "Residency news", "space": "ENG",
         "body": "An update on data residency", "labels": ["policy"], "modified_at": "2026-09-04T10:00:00+08:00"},
    ]
    cql = _run("confluence", 'type = page AND text ~ "data residency" AND lastmodified > now("-4w")', pages)
    assert _keys(cql, pages) == ["101"]
    assert _keys(_run("confluence", "label = policy ORDER BY lastmodified DESC", pages), pages) == ["103", "101"]

    files = [
        {"fid": "f1", "entity": "docx", "ident": "f1", "name": "Q3 budget review.docx", "modified_at": "2026-08-10T00:00:00Z",
         "body": "quarterly review of the budget", "author": "Maria Chen"},
        {"fid": "f2", "entity": "xlsx", "ident": "f2", "name": "Budget draft.xlsx", "modified_at": "2026-07-10T00:00:00Z",
         "body": "draft budget", "author": "Sam Lee"},
    ]
    kql = _run("sharepoint", 'budget "quarterly review" LastModifiedTime>=2026-08-01 NOT draft', files, language="kql")
    assert _keys(kql, files) == ["f1"]
    assert _keys(_run("sharepoint", 'author:"sam lee" OR filetype:docx', files, language="kql"), files) == ["f1", "f2"]

    drive = [
        {"fid": "d1", "entity": "gsheet", "ident": "d1", "name": "BudgetPlan 2026", "mime_type": "application/vnd.google-apps.spreadsheet",
         "modified_at": "2026-08-15T00:00:00Z", "parents": ["1abc"]},
        {"fid": "d2", "entity": "gdoc", "ident": "d2", "name": "Team budget notes", "mime_type": "application/vnd.google-apps.document",
         "modified_at": "2026-08-20T00:00:00Z", "parents": ["9xyz"], "trashed": True},
        {"fid": "d3", "entity": "gdoc", "ident": "d3", "name": "Offsite plan", "mime_type": "application/vnd.google-apps.document",
         "modified_at": "2026-06-20T00:00:00Z", "parents": ["1abc"]},
    ]
    assert _keys(_run("drive", "name contains 'budget' and trashed = false", drive), drive) == ["d1"]
    assert _keys(_run("drive", "'1abc' in parents and modifiedTime > '2026-08-01T00:00:00'", drive), drive) == ["d1"]
    # Drive's `name contains` is a prefix match at a word boundary: 'Plan' is not a prefix of 'BudgetPlan'.
    assert _keys(_run("drive", "name contains 'plan'", drive), drive) == ["d3"]

    slack = [
        {"fid": "s1", "entity": "message", "ident": "s1", "channel": "incidents", "sender": "maria",
         "text": "checkout down again", "ts": "2026-09-03T10:00:00+08:00"},
        {"fid": "s2", "entity": "message", "ident": "s2", "channel": "incidents", "sender": "sam",
         "text": "checkout down, resolved", "ts": "2026-09-04T10:00:00+08:00"},
        {"fid": "s3", "entity": "message", "ident": "s3", "channel": "general", "sender": "maria",
         "text": "lunch?", "ts": "2026-09-01T12:00:00+08:00"},
    ]
    assert _keys(_run("slack", '"checkout down" -resolved', slack), slack) == ["s1"]
    assert _keys(_run("slack", "from:@maria", slack), slack) == ["s1", "s3"]  # no text: newest first
    assert _keys(_run("slack", "in:#incidents on:2026-09-04", slack), slack) == ["s2"]
    assert _keys(_run("slack", "in:#general in:#incidents before:2026-09-03", slack), slack) == ["s3"]


# ---------------------------------------------------------------------------
# Vendor-shaped errors
# ---------------------------------------------------------------------------


def _refusal(connector: str, text: str, records: list[dict[str, Any]], **options: Any) -> QueryError:
    with pytest.raises(QueryError) as caught:
        _run(connector, text, records, **options)
    return caught.value


def test_jira_refuses_unknown_fields_and_bad_syntax_in_jiras_words() -> None:
    records = _jira()
    error = _refusal("jira", "foo = bar", records)
    assert (error.status, error.body) == (400, {
        "errorMessages": ["Field 'foo' does not exist or you do not have permission to view it."], "errors": {}})
    assert _refusal("jira", "project = PHX ORDER BY foo", records).message == "Not able to sort using field 'foo'."
    assert _refusal("jira", "sprint in openSprints()", records).message == "Unable to find JQL function 'openSprints'."
    syntax = _refusal("jira", "project = PHX AND", records)
    assert syntax.message.startswith("Error in the JQL Query: Expecting a field name but got '<EOF>'.")
    assert syntax.message.endswith("(line 1, character 18)")


def test_salesforce_refuses_like_salesforce() -> None:
    records = _salesforce()
    text = "SELECT Id, Foo FROM Opportunity"
    error = _refusal("salesforce", text, records, entity="opportunity")
    assert error.body[0]["errorCode"] == "INVALID_FIELD"
    assert error.message == (
        f"\n{text}\n           ^\nERROR at Row:1:Column:12\nNo such column 'Foo' on entity 'Opportunity'. If you are "
        "attempting to use a custom field, be sure to append the '__c' after the custom field name. Please reference "
        "your WSDL or the describe call for the appropriate names.")
    relationship = _refusal("salesforce", "SELECT Id FROM Opportunity WHERE Owner.Name = 'x'", records, entity="opportunity")
    assert "Didn't understand relationship 'Owner' in field path." in relationship.message
    mixed = _refusal("salesforce", "SELECT Id FROM Opportunity WHERE Amount > 1 AND Amount < 5 OR Name = 'x'", records)
    assert mixed.body[0]["errorCode"] == "MALFORMED_QUERY" and mixed.message.endswith("unexpected token: 'OR'")

    definition = load_connector_definition("salesforce")
    with pytest.raises(QueryError) as caught:
        connector_search(definition, "query", "SELECT Id FROM Widget__x", pool=lambda entity: records)
    assert caught.value.body[0]["errorCode"] == "INVALID_TYPE"
    assert "sObject type 'Widget__x' is not supported." in caught.value.message


def test_graph_confluence_drive_and_kql_refuse_or_tolerate_like_their_vendors() -> None:
    graph = _refusal("outlook", "foo eq 'x'", _messages(), entity="message")
    assert graph.body == {"error": {"code": "BadRequest", "message": (
        "Invalid filter clause: Could not find a property named 'foo' on type 'microsoft.graph.message'.")}}
    syntax = _refusal("outlook", "subject eq", _messages(), entity="message")
    assert syntax.message == "Invalid filter clause: Syntax error at position 11 in 'subject eq'."
    unknown_function = _refusal("outlook", "substringof('x', subject)", _messages(), entity="message")
    assert "An unknown function with name 'substringof' was found." in unknown_function.message

    cql = _refusal("confluence", "foo = bar", [])
    assert cql.body["statusCode"] == 400
    assert cql.message == "com.atlassian.confluence.api.service.exceptions.BadRequestException: Could not parse cql : foo = bar"

    drive = _refusal("drive", "fullText = 'x'", [])
    assert drive.body["error"]["errors"][0] == {"domain": "global", "reason": "invalid", "message": "Invalid Value",
                                                "locationType": "parameter", "location": "q"}
    assert _refusal("drive", "colour = 'blue'", []).message == "Invalid Value"

    # SharePoint searches an unknown property as text rather than refusing it.
    files = [{"fid": "f1", "entity": "docx", "body": "colour:blue swatches"}, {"fid": "f2", "entity": "docx", "body": "red"}]
    assert _keys(_run("sharepoint", "colour:blue", files, language="kql"), files, "fid") == ["f1"]
    assert _refusal("sharepoint", '"unterminated', files, language="kql").message == (
        "Your query is malformed. Please rephrase your query.")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_results_are_identical_across_runs_and_independent_of_input_order_when_ranked() -> None:
    records = _jira()
    definition = load_connector_definition("jira")
    target = target_for(definition, records=records)
    query = parse("jql", 'text ~ "checkout payments" OR priority = High', clock=CLOCK)
    first = execute(query, records, target)
    assert first == execute(query, records, target)
    assert json.dumps([records[i]["ident"] for i in first.matches]) == json.dumps(
        [records[i]["ident"] for i in execute(query, records, target).matches])
    ordered = parse("jql", "project = PHX ORDER BY priority DESC", clock=CLOCK)
    forward = [records[i]["ident"] for i in execute(ordered, records, target).matches]
    backward_records = list(reversed(records))
    backward = [backward_records[i]["ident"] for i in execute(ordered, backward_records, target).matches]
    assert forward == backward  # ties in the ORDER BY fall back to record id, not input order


# ---------------------------------------------------------------------------
# The emulator opt-in
# ---------------------------------------------------------------------------


def test_the_default_emulator_reads_the_vendor_language_and_predicate_stays_selectable() -> None:
    # The default flipped to `native`: a pilot's call errors were mostly
    # valid vendor queries the historical conjunctive parser refused.
    records = _jira()
    default = ConnectorEmulator(load_connector_definition("jira"), records)
    assert default.query_engine == "native"
    assert default.call("search_issues", query="project = PHX OR project = OPS")["total"] == 8
    assert default.call("search_issues", query="summary !~ checkout")["total"] == 4
    assert default.fork().query_engine == "native"
    # The historical subset reads `OR` as part of a value and refuses `!~`;
    # it is still there for whoever selects it.
    legacy = ConnectorEmulator(load_connector_definition("jira"), records, query_engine="predicate")
    assert legacy.call("search_issues", query="project = PHX OR project = OPS")["total"] == 0
    with pytest.raises(ConnectorError, match="unsupported jql query clause"):
        legacy.call("search_issues", query="summary !~ checkout")
    assert legacy.fork().query_engine == "predicate"
    with pytest.raises(ValueError, match="unknown query engine"):
        ConnectorEmulator(load_connector_definition("jira"), records, query_engine="fancy")


def test_an_agent_search_through_the_opted_in_emulator_returns_the_expected_records(tmp_path: Path) -> None:
    packs = tmp_path / "packs" / "policy"
    packs.mkdir(parents=True)
    (packs / "native.json").write_text(json.dumps({
        "schema": "worldloom.pack/v1", "kind": "policy", "name": "native",
        "body": {"values": {"connectors.query.engine": "native"}}}), encoding="utf-8")
    records = [{**record, "server": "salesforce"} for record in _salesforce()]
    with packkit.use("policy:native", roots=[tmp_path / "packs"]):
        emulator = ConnectorEmulator(load_connector_definition("salesforce"), records)
    assert emulator.query_engine == "native"
    run_copy = emulator.transaction(fresh=True)
    page = run_copy.call(
        "query",
        query="SELECT Id, StageName, Amount FROM Opportunity WHERE StageName = 'Closed Won' AND Amount > 100000 "
              "ORDER BY Amount DESC",
    )
    assert page["total"] == 2
    assert [item["Id"] for item in page["items"]] == ["0061", "0063"]
    assert set(page["items"][0]) <= {"attributes", "Id", "StageName", "Amount", "Name"}
    assert run_copy.trace[-1].reads == ("sf:0061", "sf:0063")

    with pytest.raises(ConnectorError) as caught:
        run_copy.call("query", query="SELECT Id FROM Opportunity WHERE Colour__c = 'red'")
    assert caught.value.code == 400 and "No such column 'Colour__c' on entity 'Opportunity'" in caught.value.message
    assert run_copy.trace[-1].error is not None

    jira = ConnectorEmulator(load_connector_definition("jira"), [{**record, "server": "jira"} for record in _jira()],
                             query_engine="native")
    paged = jira.call("search_issues", query="project = PHX OR project = OPS ORDER BY key DESC", max_results=3, start_at=3)
    assert paged["total"] == 8 and [item["key"] for item in paged["items"]] == ["PHX-104", "PHX-103", "PHX-102"]

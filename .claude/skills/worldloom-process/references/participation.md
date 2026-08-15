# Binding and participation

Purpose: the company's half of a process — seating LOB roles into declared
slots, and deriving who is in a process instead of maintaining a roster.

The company's half lives on the LOB: `lob.SlotBinding(process=..., slot=...,
role_key=...)` rows in `Lob.slot_bindings`. Lint them with
`lob.lint_bindings(my_lob, spec)` — an unbound **required** slot and a binding
to a role the LOB lacks are both refused.

Who is *in* a process is never a table — it is the join of the LOB's
responsibility edges against the kinds the process's steps mint (dot-prefix
semantics: answering for `financial.revenue` meets minting
`financial.revenue.actual`), plus the slot bindings:

```python
from worldloom import lob, sdk

lob.participation(my_lob, spec)         # tuple of Participant(role, slots, kinds, via)
lob.describe("hr")["participation"]     # per installed process, for installed LOBs

blueprint = sdk.retail().lob(my_lob, bind={"HrOnboarding": {"preparer": "recruiter",
                                                            "approver": "head_of_people"}})
blueprint.participation("HrOnboarding") # {lob_name: participants}, spec must be installed
```

The blueprint's `bind` adds `SlotBinding` rows to the attached copy without
editing the LOB; a binding naming a role the LOB lacks is refused at that
call. `lob.describe` covers *installed* LOBs only — it returns `None` for a
name never passed to `lob.install`.

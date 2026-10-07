# CUJ catalogue conformance files

Shared test files for the `cuj-catalogue/1` contract
([schema](../schemas/cuj_catalogue.schema.json),
[rules](../docs/cuj-catalogue.md)). The miner's checker and Worldloom's
checker must both give the same verdict on every file here. Worldloom keeps a
copy of this folder; see section 5.10 of
[the miner design](../docs/design/cuj-catalogue-miner.md).

| Folder | Contents |
| --- | --- |
| `valid/` | Catalogues that pass the schema and all ten invariants. |
| `invalid/` | Catalogues that each break exactly one rule. |

`valid/` holds:

- `example.json`: identical to
  [`examples/cuj_catalogue.example.json`](../examples/cuj_catalogue.example.json).
  Update both together.
- `minimal.json`: one `domain_cluster` CUJ, `text_policy: none`, and no
  optional fields.
- `no_phrasings.json`: two tool CUJs, one of them `multi_turn`, with
  `text_policy: none`.

## Invalid files

Each invalid file is a valid file with one small edit, so
`diff valid/<base> invalid/<file>` shows exactly what is wrong.

Invariants assume a well-shaped file, so they are checked only when the
schema passes. A file that fails the schema is therefore expected to report
`schema` and nothing else, even if its edit would also upset an invariant.

These fail the schema:

| File | Base | Edit |
| --- | --- | --- |
| `unknown_operation.json` | `no_phrasings.json` | A connector tool's `operation` is `fetch`, which is not in the operation enum. |
| `step_tool_and_capability.json` | `example.json` | A step names both a tool (`connector`, `entity`, `operation`) and a `capability`. |
| `domain_cluster_without_cluster.json` | `minimal.json` | A `domain_cluster` CUJ has no `cluster`. |
| `multi_turn_without_journey_outcomes.json` | `no_phrasings.json` | A `multi_turn` CUJ has no `journey_outcomes`. |
| `bad_outcome_key.json` | `no_phrasings.json` | An `outcomes` key is `TIMEOUT`, which is not an outcome label. |
| `tool_signature_without_connector_step.json` | `no_phrasings.json` | A `tool_signature` CUJ has only a capability step. Its id is recomputed to match. |
| `raw_text_field.json` | `no_phrasings.json` | A CUJ carries a `raw_text` field, which the schema does not allow. |
| `bad_cuj_id.json` | `no_phrasings.json` | A CUJ id uses upper-case hex, so it fails the id pattern. |
| `wrong_schema_version.json` | `minimal.json` | `schema_version` is `cuj-catalogue/2`. |

These pass the schema but break one invariant, named by the file's prefix:

| File | Base | Edit |
| --- | --- | --- |
| `inv1_step_entity_not_declared.json` | `no_phrasings.json` | A step uses entity `ticket`, which no connector declares. Its id is recomputed to match. |
| `inv2_depends_on_later_step.json` | `no_phrasings.json` | The `generate` step depends on the `create_issue` step after it. |
| `inv3_slot_field_not_in_argument_fields.json` | `example.json` | A slot binds to `project_key`, which is not in its step's `argument_fields`. |
| `inv3_slot_step_not_in_cuj.json` | `example.json` | A slot's `step_id` is `find_notes`, a step of another CUJ. Its `field` is in that step's `argument_fields`, so only the same-CUJ half of the rule fails. |
| `inv4_failure_mode_step_not_in_cuj.json` | `no_phrasings.json` | A failure mode's `step_id` is `read_issue`, a step of the other CUJ, not its own. |
| `inv5_support_below_min.json` | `no_phrasings.json` | `min_support` is 13, above one CUJ's 12 sessions. |
| `inv5_phrasing_support_below_min.json` | `example.json` | A phrasing's `support` is 2, below `min_support` 3. Every CUJ still has at least 3 sessions. |
| `inv6_phrasing_with_text_policy_none.json` | `example.json` | `text_policy` is `none`, but phrasings are present. |
| `inv7_redaction_marker_in_template.json` | `example.json` | A template contains `[NAME_REDACTED]`. |
| `inv8_id_mismatch.json` | `no_phrasings.json` | A well-formed CUJ id is hashed from the wrong signature (the `~answer` step left out). |
| `inv9_shares_do_not_sum.json` | `no_phrasings.json` | Coverage shares sum to 1.02, outside the ±0.01 tolerance. |
| `inv9_covered_share_mismatch.json` | `no_phrasings.json` | 0.02 moves from `unclassified_share` to `covered_share`: the shares still sum to 1, but `covered_share` is 0.72 while the CUJ shares sum to 0.7, just outside the ±0.01 tolerance. |
| `inv10_histogram_mismatch.json` | `no_phrasings.json` | Hardness counts sum to 29, but `support.queries` is 30. |
| `inv10_outcomes_mismatch.json` | `no_phrasings.json` | Outcome counts sum to 29, but hardness counts and `support.queries` are 30. |

## EXPECTED.json

Maps every file, by its path under `conformance/`, to the verdict a checker
must give:

```json
"invalid/inv2_depends_on_later_step.json": { "valid": false, "violation": "inv2" },
"invalid/raw_text_field.json": { "valid": false, "violation": "schema" },
"valid/minimal.json": { "valid": true, "violation": null }
```

`violation` is one of the shared codes `schema` and `inv1` to `inv10`. When
adding a file, add its entry here too.

Every value is invented. Never add customer data to these files.

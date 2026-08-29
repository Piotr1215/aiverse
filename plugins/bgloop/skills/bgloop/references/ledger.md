# Reading the bgloop ledger

`~/.local/state/prompt-coach/ledger.jsonl` is one JSON object per line, append only, shared by every observer and every config home. It is the record the runtime is tuned from, so read it rather than inferring what happened from behavior.

## Row shape

Every row carries the same identity fields, written by `base_event`:

| Field | Meaning |
| --- | --- |
| `ts` | Epoch seconds when the row was written |
| `job_id` | The job this row belongs to, stable across its whole life |
| `session_id` | The session the event came from and the action goes back to |
| `purpose` | Provider tag plus job purpose, for example `claude:recap+coach` |
| `event` | Which stage of the pipeline wrote the row |
| `decision` | What that stage concluded |

A completed row adds `usage`, `cost_usd`, and the observer's own fields: `kind`, `tip`, `proposed_tip`, `capability_id`, `reason`.

The `purpose` prefix is load bearing. Claude personal, Claude work and Codex share one ledger, and the relay matches on that prefix so a Codex tip can never surface in a Claude session.

## Event vocabulary

Events in the order a healthy job produces them:

| Event | Written when |
| --- | --- |
| `queued` | The hook accepted the event and wrote a job file |
| `started` | The worker woke and began retrieval |
| `request` | The request is built, about to be priced |
| `reserved` | Budget reserved atomically, the job may call the model |
| `complete` | The model answered and the observer interpreted it |
| `relayed` | Tips were handed to a session as prompt context |
| `channel-attempt` | A live push at the session was attempted, delivered or not |
| `replayed` | A past decision was re-delivered on request |
| `blocked` | The job stopped before the model call |
| `failed` | The model call itself errored |
| `learned` | A tip was marked as already known |
| `restore` | A learned suppression was lifted |
| `simulated` | A decision was produced by `simulate` |

## Decision vocabulary

Blocked before spending anything:

| Decision | What it rules out |
| --- | --- |
| `disabled` | The runtime is off. Nothing else was evaluated |
| `unknown-observer` | The job named an observer kind nothing registered. A wiring bug, not a judgment |
| `coalesced` | A later job for the same prompt owns the work |
| `session-token-cap` | This session's cap would have been exceeded by the reservation |
| `daily-token-cap` | The daily cap would have been exceeded |
| `estimate-error` | Token counting failed, so no reservation could be made honestly |

Failed during the call:

| Decision | What it rules out |
| --- | --- |
| `response-error` | The transport or the model errored. Tokens may still have been spent |
| `invalid-response` | The model returned something unusable or incomplete |
| `invalid-capability` | The model named a capability it was not shown, or attached an id to a kind that may not carry one |

Completed, with a verdict:

| Decision | Meaning |
| --- | --- |
| `none` | The model was asked and had nothing worth saying |
| `learned` | A real tip, suppressed because it is already marked learned |
| `fired` | A tip worth delivering. This is the only decision that produces an action |

## Following one job

Filter on `job_id` and read the rows in time order. The three questions worth asking:

Did it reach the model? Look for `reserved`. No reservation means no call and no spend, and the `blocked` row's decision says why.

Did it produce advice? A `complete` row with decision `fired` carries the `tip` field. Any other decision carries `proposed_tip` instead when the model did answer, which is how a suppressed tip stays visible without being delivered.

Did it arrive? Publishing is not receipt. A `channel-attempt` row records that a live push was tried, and it never consumes the tip. The tip is consumed only by a `relayed` row, whose `through_ts` is the cursor. Anything after that cursor is still owed and arrives on the session's next prompt.

## Useful one-liners

Today's spend, all observers, both accounts:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/coach.py" status
```

Every decision for one session, newest last:

```bash
jq -c 'select(.session_id | startswith("<prefix>")) | {ts, event, decision, tip}' ~/.local/state/prompt-coach/ledger.jsonl
```

Why the last few jobs produced nothing:

```bash
jq -c 'select(.event == "blocked") | {ts, decision, session_id}' ~/.local/state/prompt-coach/ledger.jsonl | tail
```

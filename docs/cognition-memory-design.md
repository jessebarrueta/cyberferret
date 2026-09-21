# Cognition & Memory: Laya Pick-and-Pull

Status: design notes, not an implementation commitment.

Laya is a local-first event-processing and context system. It is not a robotics runtime, but several of its solutions map closely to problems Cyber Ferret and future Enormous Brain entities will need to solve. We should borrow the patterns, not adopt Laya wholesale.

## Preserve our core boundary

The Pi remains the nervous system: sensors, normalized state, deterministic events, safety arbitration, and motor control. Slow cognition may observe and propose behavior but must not directly command PWM. Memory, semantic retrieval, summarization, and model inference can run on the Mac or an entity service.

## Useful patterns

### 1. Normalize inputs into events

Laya normalizes heterogeneous sources before cognition and recommends deterministic event IDs so retries deduplicate.

For us, distinguish:
- observation: raw/derived sensor measurement
- state: current best estimate
- event: meaningful state change
- memory: retained event/state information
- belief: revisable interpretation
- prediction: expected future observation
- outcome: actual observation

High-frequency samples should not automatically become memories. Raw session recordings can remain available while the event layer emits meaningful changes.

A future EntityEvent envelope should carry a stable event ID, timestamp, source/device, event type, actor/self, subject/entity IDs, content, salience, and confidence.

### 2. Fast routing before expensive cognition

Laya applies rules before a fast router, specialist processing, and stronger synthesis. It also debounces bursty work.

Our equivalent should be:

event -> deterministic relevance/safety -> salience -> optional cheap router -> optional specialist/reasoner -> behavior proposal or memory update -> audit record

Most sensor events should terminate before an LLM call. Safety always acts before cognition.

### 3. Hybrid retrieval, not vector search alone

Laya Coherence combines dense vector search, lexical BM25/SQLite FTS5, and explicit entity lookup, then fuses ranked results with Reciprocal Rank Fusion (RRF). It expands related entities and organizes results chronologically.

Entity recall should eventually combine:
1. exact/structured lookup
2. lexical search
3. semantic search
4. temporal filtering
5. relationship expansion

This matters for questions like "Have I seen this person before?", "What happened last time I heard this sound?", and "What usually follows this action?" RRF is attractive because it combines rankings without pretending unlike scores are directly comparable.

### 4. Form episodes from events

Laya context association groups records that appear to belong to the same real-world context. Strong matches can be automatic; ambiguous matches can use model confirmation; explicit human link/unlink corrections win.

For embodied memory, add episode_id/context_id. Candidate grouping signals include temporal proximity, location, recognized person/object, active goal, behavior, causal adjacency, and semantic similarity.

Do not copy Laya's numeric similarity thresholds. They are tuned for work notifications, not physical experience.

### 5. Learn from corrections without immediate model training

Laya records link/unlink corrections, periodically extracts generalizable natural-language rules, injects a bounded rule set into later grouping decisions, and consolidates the rule set as it grows.

We can use the same pattern for corrections such as:
- "That was not the same person."
- "Those sounds came from the same device."
- "This belongs to the marker-following episode."
- "Do not treat the TV remote IR flash as an interesting object."

Learned rules must remain inspectable, reversible hypotheses rather than truth.

### 6. Rolling summaries instead of infinite context

Laya maintains rolling group summaries and a rolling cross-source summary. New information updates compact representations rather than continually reprocessing all history.

Our hierarchy can be:

raw session -> events -> episode summary -> person/object/place summaries -> longer-term self/world model

Every summary should retain references to lower-level evidence. Summaries are revisable caches, not canonical truth. Preserve stable facts, uncertainty, contradictions, meaningful changes, and important predictions/outcomes.

### 7. Explicit decay, retention, and consolidation

Laya uses configurable retention, housekeeping, bounded correction history, and limited context injection.

Our memories should eventually carry lifecycle metadata such as created_at, last_recalled_at, last_reinforced_at, salience, confidence, recall_count, source_count, retention class, superseded_by, and consolidated_into.

Possible classes: ephemeral, working, episodic, semantic, identity, and safety. Old detail can expire after consolidation without deleting the useful higher-level lesson.

### 8. Bound retrieval

Laya caps semantic results, seed results, related context, learned rules, examples, and chat context.

Every cognition request should have a context budget. Prefer a few exact facts + highly relevant episodes + current state + compact long-term summaries over a large bag of vaguely similar embeddings. Record why each memory was retrieved.

### 9. Predictions and outcomes are first-class records

This is our extension rather than a Laya feature.

For embodied learning:

state + action -> prediction -> observed outcome -> prediction error -> revised belief

Predictions should record their evidence, expected observation/window, confidence, actual outcome, error, resolution time, and resulting belief updates. This lets the entity later ask whether similar predictions were correct.

### 10. Audit cognition

Laya records pipeline stages, model use, latency, success/failure, and retries.

For meaningful Cyber Ferret decisions, record triggering events, retrieved memories, model/backend/version, prompt/policy version, proposed behavior, confidence, safety decision, executed action, resulting observations, latency/failure, and prediction error.

"Why did the ferret do that?" should be an engineering query with evidence.

### 11. Pluggable model roles

Laya can assign different providers to different roles and supports local OpenAI-compatible backends.

We should define capabilities instead of one global LLM: router, reasoner, summarizer, embedder, vision semantics, speech, memory consolidator. Each role can select local or remote implementations. The Pi should not care which model implements cognition.

### 12. MCP is a useful cognition boundary

Laya exposes scoped read/write/egress capabilities through one MCP endpoint.

A future Enormous Brain service could expose tools such as recall_experiences, search_events, get_episode, get_self_state, get_world_belief, record_prediction, resolve_prediction, remember_episode, link_memories, and correct_association.

Do not expose raw motor control through cognition MCP. The service proposes intent; the body's deterministic safety/control layer decides whether it is permitted.

### 13. Explicit authority levels

Laya's staged/approved actions suggest a useful authority pattern.

Potential levels: OBSERVE, ADVISE, ACT_IN_SANDBOX, ACT_LOW_RISK, ACT_WITH_APPROVAL, PROHIBITED.

Examples: summarize an episode = OBSERVE; recommend turning toward sound = ADVISE; simulate a path = ACT_IN_SANDBOX; vehicle motion = initially ACT_WITH_APPROVAL; bypass emergency stop = PROHIBITED.

Authority should be metadata/policy, not prompt wording.

### 14. Idempotency and stale-output handling

Any body/cortex network boundary must tolerate duplicate delivery, reordered events, disconnection, restarts, delayed responses, partial processing, and stale recommendations.

Therefore ingestion should be idempotent, recommendations need timestamps/expiry, body safety cannot depend on cortex availability, stale cognition output is discarded, and failed jobs remain inspectable.

## Do not copy

Do not add n8n to the robot runtime, productivity personas, Action Cards, Laya's work-notification priorities, its exact semantic thresholds, LLM processing in the real-time control path, or ChromaDB as a permanent commitment before benchmarking alternatives.

## Proposed sequence

1. Freeze a normalized EntityEvent schema around the event system we already have.
2. Add stable IDs and idempotent persistence.
3. Add episode/context IDs with simple deterministic grouping.
4. Store episode summaries with source-event references.
5. Add hybrid retrieval: structured + lexical + semantic.
6. Add prediction/outcome records and prediction-error linkage.
7. Add salience/retention/consolidation lifecycle.
8. Add correction records and inspectable learned association rules.
9. Add pluggable model roles.
10. Expose cognition/memory through a scoped service/MCP boundary.

This keeps each stage independently testable and avoids building an elaborate memory brain before we have enough embodied data to evaluate it.

## Research questions

- What constitutes an episode boundary in physical experience?
- Which sensor changes deserve events rather than raw observations?
- How should salience combine novelty, prediction error, drives, human interaction, and safety?
- How should contradictory memories coexist before a belief is revised?
- How much episodic detail is needed after consolidation?
- Which retrieval mix works best: exact, temporal, lexical, semantic, spatial, relational?
- How do we measure whether memory improves behavior rather than merely producing plausible narratives?
- How do we prevent summaries from laundering hallucinations into long-term memory?

## Evaluation principle

Memory quality should be measured behaviorally: prediction accuracy, recognition continuity, task completion, avoidance of repeated mistakes, retrieval precision/recall, reduced unnecessary model calls, and evidence-backed behavior explanations. A compelling autobiographical narrative is not sufficient evidence that the entity learned anything.

## Provenance

Primary sources:
- https://laya.aay.sh/docs.html
- https://github.com/aayushch/laya

Laya concepts examined: normalized ingestion, deterministic event IDs, staged processing, hybrid retrieval/RRF, context association, correction-driven context rules, rolling summaries, retention, bounded retrieval, audit/retry behavior, local model roles, and scoped MCP capabilities.

The Cyber Ferret adaptations, prediction/outcome loop, safety boundary, authority levels, lifecycle proposal, and implementation sequence are our design extrapolations rather than claims about Laya.

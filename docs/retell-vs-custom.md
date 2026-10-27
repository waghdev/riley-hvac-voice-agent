# Retell vs a custom LiveKit pipeline

> Draft structure. Dev writes the opinions here from shipping production agents on Retell AI.
> Each section lists the facts this repo can back with numbers; the judgement is his.

## Where each one fits

<!-- Dev: one paragraph. When would you pick Retell for a client, and when a custom pipeline? -->

## Time to a working agent

- This repo: M0 to a deployed, tested agent took about a week (PROGRESS.md session log).
<!-- Dev: what the same agent takes on Retell. -->

## Latency and turn-taking

- Measured here: total response p50 1,409 ms / p90 2,565 ms on the deployed agent (README).
- Levers that only exist with the pipeline in hand: per-question endpointing, a spoken
  acknowledgement inside tool calls, waiting for the rest of a phone number.
<!-- Dev: how this compares with what you see on Retell in production. -->

## Control over the decision layer

- Here, every business rule is plain Python with table tests (`gates.py`); the LLM can't book an
  out-of-area caller even if talked into it.
<!-- Dev: how you enforce the same on Retell (custom functions, middleware) and what it costs. -->

## Testing and evaluation

- Here: unit tests in CI, LLM behavior tests, LiveKit simulations graded on final state, a QA
  rubric.
<!-- Dev: Retell's testing tools and where you needed your own regression suite. -->

## Cost

- Here: $0 on free tiers for a demo; per-minute costs at scale are in LiveKit's pricing.
<!-- Dev: Retell's per-minute price against a self-run pipeline at a real client's volume. -->

## Operations

- Here: you own deploys, rollbacks, secrets, quotas and provider outages (the LLM fallback).
<!-- Dev: what Retell takes off your plate, and what you still had to build. -->

## What I'd choose, and why

<!-- Dev -->

# voice-agent-reference

A production-style AI phone agent built on an open-source real-time pipeline (LiveKit Agents),
for a fictional HVAC company. Call it, and it qualifies you, handles safety situations, and books
a service appointment.

> Status: in progress. Sections marked TODO fill in as milestones land.

## Try it

TODO: "Talk to Riley" link to the public web-call page (works in any browser, no phone needed).
Phone number for live testing, if kept active.

## Demo

TODO: 60 to 90 second video of a real call.

## What it does

TODO: one paragraph and the outcomes table (booked, safety redirect, out of area, not offered,
callback, incomplete).

## Architecture

TODO: Mermaid diagram (web page and token endpoint, caller, LiveKit number, room, agent worker, STT/LLM/TTS, gates, tools, mock CRM).

## Latency (measured)

TODO: p50/p90 per stage, web vs phone, number of calls and turns, what dominates and what was tuned.

| Stage | p50 | p90 |
| --- | --- | --- |
| End of utterance | | |
| STT final | | |
| LLM first token | | |
| TTS first audio | | |
| Total response | | |

## The decision layer

TODO: "the LLM extracts, code decides", with a short code excerpt from gates.py.

## Testing

TODO: unit, behavior and scenario layers, how to run them, and the call-quality grader.

## Retell vs a custom pipeline

TODO: link to docs/retell-vs-custom.md (written from production experience).

## Run it yourself

TODO: prerequisites, `.env`, `uv sync`, run locally, connect a phone number.

## Built by

Devendra (Dev) Wagh, Co-Founder & CTO at Scaile AI. Built with Claude Code.

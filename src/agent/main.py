"""Agent server entrypoint: one AgentSession per call (web page, phone or local console).

Run locally:
    uv run python -m agent.main console   # talk through your mic and speakers
    uv run python -m agent.main dev       # join rooms on LiveKit Cloud (Agent Console, web page)

LiveKit APIs used here were checked against the livekit-agents 1.8.8 docs and installed source
(see docs/decisions.md, M1 entries).
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    CloseEvent,
    ConversationItemAddedEvent,
    JobContext,
    TurnHandlingOptions,
    UserStateChangedEvent,
    cli,
    inference,
    room_io,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.agents.llm import ChatMessage
from livekit.plugins import ai_coustics, deepgram

from agent import prompts
from agent.config import REPO_ROOT, load_business
from agent.metrics import JsonlWriter, TurnPairer
from agent.silence import SilenceMonitor

load_dotenv(REPO_ROOT / ".env")
logger = logging.getLogger("riley")

BUSINESS = load_business()
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")
TTS_VOICE = os.getenv("TTS_VOICE", "aura-2-andromeda-en")  # chosen by listening, decisions.md
MAX_CALL_SECONDS = float(os.getenv("MAX_CALL_SECONDS", "300"))
METRICS_DIR = Path(os.getenv("METRICS_DIR", REPO_ROOT / "metrics"))

# Unset = the model's default. Gemini 3 models should keep theirs (LiveKit's Gemini docs: other
# values can cause looping); set a low value only for models where that's safe.
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE")
SILENCE_SECONDS = 7.0  # caller silent this long -> "Are you still there?" (CLAUDE.md section 4)
SILENCE_PROMPTS = 2  # unanswered check-ins before a polite close


def build_llm() -> inference.LLM:
    """The production LLM; behavior tests use this too, so they test what callers get."""
    # One tool call per response: a voice turn does one thing, and parallel calls made
    # end_call fire four times in one turn (debugger call, 2026-10-20).
    extra: dict[str, object] = {"parallel_tool_calls": False}
    if LLM_TEMPERATURE:
        extra["temperature"] = float(LLM_TEMPERATURE)
    return inference.LLM(model=LLM_MODEL, extra_kwargs=extra)


class Riley(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=prompts.build_instructions(BUSINESS),
            tools=[
                # ignore_on_enter: the model can't end the call during the greeting.
                # delete_room=False: RoomOptions.delete_room_on_close already deletes the room
                # for every way a call ends, so this tool doesn't need to.
                # end_instructions is the tool's result. The default ("say goodbye to the
                # user") let the model loop on end_call instead of speaking (behavior test,
                # 2026-10-20), so it says exactly what to do next.
                EndCallTool(
                    ignore_on_enter=True,
                    delete_room=False,
                    end_instructions=prompts.END_CALL_RESULT,
                ),
            ],
        )

    async def on_enter(self) -> None:
        # The greeting carries the recording disclosure, so the caller can't talk over it.
        self.session.say(prompts.greeting(BUSINESS), allow_interruptions=False)


server = AgentServer()


@server.rtc_session(agent_name="riley")  # explicit dispatch: rooms must ask for "riley"
async def entrypoint(ctx: JobContext) -> None:
    call_id = ctx.job.id
    ctx.log_context_fields = {"call_id": call_id}
    # Phone calls (SIP participants) get their own label in M6.
    channel = "console" if ctx.is_fake_job() else "web"

    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en-US", keyterm=["Kestrel"]),
        llm=build_llm(),
        tts=deepgram.TTS(model=TTS_VOICE),
        # The audio turn detector is also the default; it's explicit here because it's what
        # stops Riley cutting in when a caller pauses mid-sentence. Interruptions, false-
        # interruption recovery and preemptive generation use their defaults (all on).
        turn_handling=TurnHandlingOptions(turn_detection=inference.TurnDetector()),
        user_away_timeout=SILENCE_SECONDS,
    )

    pairer = TurnPairer(call_id=call_id, channel=channel, session_started_at=time.time())
    writer = JsonlWriter(METRICS_DIR)

    async def end_with(line: str) -> None:
        """Say a final line nobody can talk over, then close (which deletes the room)."""
        session.interrupt()
        await session.say(line, allow_interruptions=False)
        session.shutdown()

    # --- Silence: two check-ins, then a polite close ------------------------------------
    silence = SilenceMonitor(
        say=lambda line: session.say(line),  # a SpeechHandle resolves when playout ends
        close=end_with,
        wait_seconds=SILENCE_SECONDS,
        prompts=SILENCE_PROMPTS,
        still_there=prompts.STILL_THERE,
        goodbye=prompts.SILENCE_GOODBYE,
    )

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent) -> None:
        # Riley speaking doesn't clear "away"; only caller activity does, so the check-in
        # isn't cancelled by its own "Are you still there?".
        silence.on_user_state(ev.new_state)

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        if not isinstance(ev.item, ChatMessage):
            return
        if ev.item.role == "user":
            # Typed input (web chat, debugger) doesn't go through VAD, so tell both the
            # monitor and the session's away timer that the caller is active.
            silence.on_caller_turn()
            session.reset_away_timer()
        record = pairer.add(ev.item.role, ev.item.metrics or {})
        if record:
            writer.write(record)
            logger.info("turn metrics", extra=record)

    # --- Maximum call length, to protect the free quotas --------------------------------
    async def time_limit() -> None:
        await asyncio.sleep(MAX_CALL_SECONDS)
        await end_with(prompts.TIME_LIMIT_GOODBYE)

    limit_task: asyncio.Task[None] | None = None

    @session.on("close")
    def _on_close(ev: CloseEvent) -> None:
        silence.stop()
        if limit_task is not None:
            limit_task.cancel()
        # Ends the job in console mode too, where there's no room to delete.
        ctx.shutdown(reason=f"session closed: {ev.reason}")

    await session.start(
        agent=Riley(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # Background noise suppression: included on the Build plan at no extra charge.
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_L
                ),
            ),
            # Every way a call ends (end_call tool, silence, time limit, caller hanging up)
            # closes the session; deleting the room then disconnects everyone, phone included.
            delete_room_on_close=True,
        ),
    )
    limit_task = asyncio.create_task(time_limit())


if __name__ == "__main__":
    cli.run_app(server)

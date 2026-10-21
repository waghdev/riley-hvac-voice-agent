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
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AudioConfig,
    BackgroundAudioPlayer,
    BuiltinAudioClip,
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

from agent import prompts, tools
from agent.config import DEFAULT_TTS_VOICE, REPO_ROOT, load_business
from agent.greeting_audio import GreetingClip, load_greeting
from agent.metrics import JsonlWriter, TurnPairer
from agent.silence import SilenceMonitor
from agent.spoken import NameGuard, speak_numbers_stream
from agent.state import CallState, Outcome

load_dotenv(REPO_ROOT / ".env")
logger = logging.getLogger("riley")

BUSINESS = load_business()
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")
TTS_VOICE = os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE)
# Loaded once per process, so a call never waits on it. None if missing or stale (wrong text or
# voice): Riley then speaks the greeting with live TTS instead.
GREETING_CLIP = load_greeting(prompts.greeting(BUSINESS), TTS_VOICE)
if GREETING_CLIP is None:
    logger.warning("no greeting clip for this text and voice; using live TTS for the greeting")
MAX_CALL_SECONDS = float(os.getenv("MAX_CALL_SECONDS", "300"))
METRICS_DIR = Path(os.getenv("METRICS_DIR", REPO_ROOT / "metrics"))

# Unset = the model's default. Gemini 3 models should keep theirs (LiveKit's Gemini docs: other
# values can cause looping); set a low value only for models where that's safe.
LLM_TEMPERATURE = os.getenv("LLM_TEMPERATURE")
# Call-center ambience under Riley's voice, like Retell's ambient sound. AMBIENT_SOUND=off
# disables it. The clips ship with livekit-agents and are mastered very differently, so the
# volumes are gains measured against Andromeda's speech (2026-10-21): office at 1.0 sits ~31 dB
# under speech. Dev picked 2.5 from previews, then asked for a little louder after a live call:
# 3.5 (+3 dB, ~17 dB under speech, peaks at -27 dBFS). That's above the documented 0.0-1.0 range;
# it works because the player multiplies samples and clips them to 16-bit.
AMBIENT_CLIPS = {
    "office": BuiltinAudioClip.OFFICE_AMBIENCE,
    "crowded": BuiltinAudioClip.CROWDED_ROOM,
}
AMBIENT_SOUND = os.getenv("AMBIENT_SOUND", "office")
AMBIENT_VOLUME = float(os.getenv("AMBIENT_VOLUME", "3.5"))
# Keyboard typing while Riley is "thinking" (between the caller's turn and her reply). The clips
# are ~6 dB under speech at 1.0; 0.5 (+3 dB on the first pick of 0.35) puts them ~12 dB under.
# 0 disables typing.
THINKING_VOLUME = float(os.getenv("THINKING_VOLUME", "0.5"))
BACKGROUND_CLOSE_SECONDS = 2.0  # bound on closing the background-audio player at hang-up
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


async def clip_frames(clip: GreetingClip, frame_ms: int = 20) -> AsyncIterator[rtc.AudioFrame]:
    """The pre-rendered greeting as 20 ms audio frames, which is what say(audio=...) plays."""
    samples = clip.sample_rate * frame_ms // 1000
    step = samples * 2  # 16-bit mono: 2 bytes per sample
    for start in range(0, len(clip.pcm), step):
        chunk = clip.pcm[start : start + step].ljust(step, b"\x00")  # pad the last frame
        yield rtc.AudioFrame(
            data=chunk, sample_rate=clip.sample_rate, num_channels=1, samples_per_channel=samples
        )


class Riley(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=prompts.build_instructions(BUSINESS),
            tools=[
                # The decision layer: each tool runs the gates in gates.py (see tools.py).
                *tools.ALL_TOOLS,
                # ignore_on_enter: the model can't end the call during the greeting.
                # delete_room=False: the session's close handler deletes the room for every way
                # a call ends, after closing background audio (see finish_call below).
                # end_instructions is the tool's result. The default ("say goodbye to the
                # user") let the model loop on end_call instead of speaking (behavior test,
                # 2026-10-20), so it says exactly what to do next.
                EndCallTool(
                    ignore_on_enter=True,
                    delete_room=False,
                    end_instructions=prompts.END_CALL_RESULT,
                    on_tool_completed=tools.no_second_goodbye,
                ),
            ],
        )

    async def on_enter(self) -> None:
        # The greeting carries the recording disclosure, so the caller can't talk over it.
        # It plays from one pre-rendered clip: live TTS renders each sentence separately, and
        # Aura-2 read the disclosure sentence in a different-sounding voice (cloud call,
        # 2026-10-21). The text still goes to the transcript and chat history.
        text = prompts.greeting(BUSINESS)
        if GREETING_CLIP is not None:
            self.session.say(text, audio=clip_frames(GREETING_CLIP), allow_interruptions=False)
        else:
            self.session.say(text, allow_interruptions=False)


server = AgentServer()


@server.rtc_session(agent_name="riley")  # explicit dispatch: rooms must ask for "riley"
async def entrypoint(ctx: JobContext) -> None:
    call_id = ctx.job.id
    ctx.log_context_fields = {"call_id": call_id}
    # Phone calls (SIP participants) get their own label in M6.
    channel = "console" if ctx.is_fake_job() else "web"

    state = CallState(call_id=call_id)  # everything Riley learns on this call; tools write it

    session = AgentSession[CallState](
        stt=deepgram.STT(model="nova-3", language="en-US", keyterm=["Kestrel"]),
        llm=build_llm(),
        tts=deepgram.TTS(model=TTS_VOICE),
        # The audio turn detector is also the default; it's explicit here because it's what
        # stops Riley cutting in when a caller pauses mid-sentence. Interruptions, false-
        # interruption recovery and preemptive generation use their defaults (all on).
        # max_delay is tools.py's DEFAULT_MAX_DELAY; tools shorten it for short answers.
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            endpointing={"max_delay": tools.DEFAULT_MAX_DELAY},
        ),
        user_away_timeout=SILENCE_SECONDS,
        userdata=state,
        # What TTS hears: LiveKit's markdown and emoji filters (the defaults, kept), the caller's
        # name at most once per call, then numbers spoken the way people say them.
        tts_text_transforms=[
            "filter_markdown",
            "filter_emoji",
            NameGuard(lambda: state.first_name),
            speak_numbers_stream,
        ],
    )

    pairer = TurnPairer(call_id=call_id, channel=channel, session_started_at=time.time())
    writer = JsonlWriter(METRICS_DIR)

    async def end_with(line: str) -> None:
        """Say a final line nobody can talk over, then close the session (see finish_call)."""
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
            # The short-answer wait applies to one answer only; the next tool sets it again if
            # Riley's next question also has a short answer.
            state.expecting = None
            session.update_options(endpointing_opts=tools.endpointing_for(state))
        record = pairer.add(ev.item.role, ev.item.metrics or {})
        if record:
            writer.write(record)
            logger.info("turn metrics", extra=record)

    # --- Maximum call length, to protect the free quotas --------------------------------
    async def time_limit() -> None:
        await asyncio.sleep(MAX_CALL_SECONDS)
        await end_with(prompts.TIME_LIMIT_GOODBYE)

    limit_task: asyncio.Task[None] | None = None
    background: BackgroundAudioPlayer | None = None
    finishing: asyncio.Task[None] | None = None

    async def finish_call(reason: str) -> None:
        """Hang up in an order that lets the job exit cleanly.

        The SDK disconnects the room *before* it runs shutdown callbacks, so closing background
        audio as a shutdown callback tried to unpublish its track from a disconnected room
        ("could not find publication to remove"), and the job hung for 10 s until LiveKit killed
        it (cloud call, 2026-10-21). So: close background audio while the room is still connected
        (bounded, so a stuck close can't leave the caller on a silent line), then delete the room,
        which disconnects the caller (phone included), then end the job.
        """
        if background is not None:
            try:
                await asyncio.wait_for(background.aclose(), timeout=BACKGROUND_CLOSE_SECONDS)
            except Exception:  # TimeoutError included: still hang up
                logger.warning("background audio didn't close cleanly", exc_info=True)
        await ctx.delete_room()  # a no-op with a warning in console mode
        ctx.shutdown(reason=reason)

    @session.on("close")
    def _on_close(ev: CloseEvent) -> None:
        # Every way a call ends (end_call tool, silence, time limit, caller hanging up) closes
        # the session, so this is the one place a call is finished.
        nonlocal finishing
        silence.stop()
        if limit_task is not None:
            limit_task.cancel()
        # Every call ends in exactly one outcome; a call no gate settled is incomplete.
        if state.outcome is None:
            state.outcome = Outcome.INCOMPLETE
        logger.info("call outcome", extra={"outcome": state.outcome.value})
        finishing = asyncio.create_task(finish_call(f"session closed: {ev.reason}"))

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
            # The room is deleted by finish_call instead, after background audio is closed;
            # deleting it here at the same moment raced that cleanup.
            delete_room_on_close=False,
        ),
    )
    limit_task = asyncio.create_task(time_limit())

    # --- Background audio: call-center ambience and keyboard typing -----------------------
    # Plays on its own track, to the caller only. Riley's STT hears the caller's microphone, not
    # this track. (Console mode doesn't support it; the player logs that and stays quiet.)
    ambient = None
    if AMBIENT_SOUND in AMBIENT_CLIPS:
        ambient = AudioConfig(AMBIENT_CLIPS[AMBIENT_SOUND], volume=AMBIENT_VOLUME, fade_in=1.0)
    elif AMBIENT_SOUND != "off":
        logger.warning("unknown AMBIENT_SOUND %r; ambience is off", AMBIENT_SOUND)
    thinking = None
    if THINKING_VOLUME > 0:
        # Probabilities sum to 0.8, so about 1 in 5 pauses has no typing; that keeps it from
        # sounding canned.
        thinking = [
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=THINKING_VOLUME, probability=0.5),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=THINKING_VOLUME, probability=0.3),
        ]
    if ambient or thinking:
        background = BackgroundAudioPlayer(ambient_sound=ambient, thinking_sound=thinking)
        await background.start(room=ctx.room, agent_session=session)
        # Closed by finish_call, not a shutdown callback (see its docstring).


if __name__ == "__main__":
    cli.run_app(server)

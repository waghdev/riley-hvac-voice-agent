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
import tempfile
import time
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

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
    ErrorEvent,
    JobContext,
    ModelSettings,
    SimulationContext,
    StopResponse,
    TurnHandlingOptions,
    UserStateChangedEvent,
    cli,
    inference,
    llm,
    room_io,
)
from livekit.agents.beta.tools import EndCallTool
from livekit.agents.llm import ChatMessage
from livekit.agents.simulation import SimulationMode
from livekit.plugins import ai_coustics, deepgram

from agent import prompts, scenarios, tools
from agent.clips import Clip, load_clip
from agent.config import DEFAULT_TTS_VOICE, REPO_ROOT, load_business
from agent.metrics import CLIENT_TIMING_TOPIC, JsonlWriter, TurnPairer, client_timing_record
from agent.silence import SilenceMonitor
from agent.spoken import (
    LeadingAckGuard,
    NameGuard,
    RepeatedConfirmationGuard,
    speak_numbers_stream,
)
from agent.state import CallState, Outcome
from agent.turns import DigitHold

load_dotenv(REPO_ROOT / ".env")
logger = logging.getLogger("riley")

BUSINESS = load_business()
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-3.1-flash-lite")
TTS_VOICE = os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE)
# Loaded once per process, so a call never waits on them. None if missing or stale (wrong text or
# voice): Riley then says that line with live TTS instead.
GREETING_CLIP = load_clip("greeting", prompts.greeting(BUSINESS), TTS_VOICE)
UNAVAILABLE_CLIP = load_clip("unavailable", prompts.SERVICE_UNAVAILABLE, TTS_VOICE)
for _name, _clip in (("greeting", GREETING_CLIP), ("unavailable", UNAVAILABLE_CLIP)):
    if _clip is None:
        logger.warning("no %s clip for this text and voice; using live TTS for it", _name)
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
# After the caller is gone: how long CRM deliveries still in flight get to finish. Under the
# ~10 s LiveKit gives a job to shut down before killing it (livekit-agents 1.8.8,
# shutdown_process_timeout). Usually nothing is left: a lead goes out the moment it's booked.
# Anything cut off stays pending in the outbox for scripts/redeliver_outbox.py.
LEAD_DRAIN_SECONDS = 7.0
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


async def clip_frames(clip: Clip, frame_ms: int = 20) -> AsyncIterator[rtc.AudioFrame]:
    """A pre-rendered clip as 20 ms audio frames, which is what say(audio=...) plays."""
    samples = clip.sample_rate * frame_ms // 1000
    step = samples * 2  # 16-bit mono: 2 bytes per sample
    for start in range(0, len(clip.pcm), step):
        chunk = clip.pcm[start : start + step].ljust(step, b"\x00")  # pad the last frame
        yield rtc.AudioFrame(
            data=chunk, sample_rate=clip.sample_rate, num_channels=1, samples_per_channel=samples
        )


def spoken_guards(state: CallState) -> list[Callable[[AsyncIterable[str]], AsyncIterable[str]]]:
    """What code removes from a reply before anyone hears or reads it (spoken.py), for one
    stream: TTS and the transcript each get their own, since NameGuard counts uses."""
    return [
        LeadingAckGuard(lambda: state.acknowledged),
        RepeatedConfirmationGuard(lambda: state.confirmed_aloud),
        NameGuard(lambda: state.first_name),
    ]


def close_on_fatal_error(
    end_with: Callable[..., Awaitable[None]],
) -> Callable[[ErrorEvent], None]:
    """The session's "error" handler: on the first unrecoverable error, say SERVICE_UNAVAILABLE
    and hang up (end_with does both).

    Recoverable errors are retried by the SDK. An unrecoverable one means retries are exhausted
    or the request can't succeed (LiveKit Inference refusing once the free LLM credit runs
    out). LiveKit's docs say to say a line before the session closes, but 1.8.8 only closes
    after 3 unrecoverable errors in a row (max_unrecoverable_errors): after one, the caller
    heard the line and then dead air (debugger call, 2026-10-25). The line is pre-rendered, so
    it plays even when TTS is what failed.
    """
    closing: list[asyncio.Task[None]] = []  # holds the task, and means "already hanging up"

    def on_error(ev: ErrorEvent) -> None:
        if ev.error.recoverable or closing:
            return
        source = type(ev.source).__name__
        logger.error("unrecoverable error", extra={"source": source, "error": str(ev.error)})
        closing.append(
            asyncio.create_task(
                end_with(prompts.SERVICE_UNAVAILABLE, by="error", clip=UNAVAILABLE_CLIP)
            )
        )

    return on_error


TextTransform = Callable[[AsyncIterable[str]], AsyncIterable[str]]


class Riley(Agent):
    def __init__(
        self,
        transcript_transforms: Sequence[TextTransform] = (),
        digit_hold: DigitHold | None = None,
    ) -> None:
        self._transcript_transforms = transcript_transforms
        self._digit_hold = digit_hold
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
                    on_tool_called=tools.end_call_requested,
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

    async def transcription_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ) -> AsyncIterator[str]:
        """The transcript (web page, simulations) shows what the caller hears: the same
        acknowledgement and name rules as TTS (entrypoint), with digits left as digits."""
        for transform in self._transcript_transforms:
            text = transform(text)
        async for chunk in Agent.default.transcription_node(self, text, model_settings):
            yield chunk

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: ChatMessage
    ) -> None:
        """Half a phone number or ZIP gets no reply yet (turns.DigitHold). The SDK drops a
        turn that raises StopResponse from the history, so the held words are put in front of
        the next turn's message instead: the model and digits_heard see the whole number."""
        if self._digit_hold is None:
            return
        said = new_message.text_content or ""
        hold, text = self._digit_hold.on_turn(said)
        if text != said:
            new_message.content = [text]
        if hold:
            # Speech only: typed text (debugger, text simulations) skips this hook entirely.
            logger.info("waiting for the rest of a number")
            raise StopResponse()


class SimulatedRiley(Riley):
    """Riley in an agent simulation, where hanging up on a call that ended wrong leaves the
    line open (see entrypoint): once she has hung up, she doesn't answer anything the
    simulated caller still says."""

    def __init__(self, hung_up: Callable[[], bool], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._hung_up = hung_up

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: ChatMessage
    ) -> None:
        if self._hung_up():
            raise StopResponse()
        await super().on_user_turn_completed(turn_ctx, new_message)


async def check_final_state(sim: SimulationContext) -> None:
    """End of an agent simulation: fail the run if the call ended differently from what the
    scenario expects (scenarios.py). The judge only reads the transcript."""
    state: CallState = sim.job_context.primary_session.userdata
    failure = scenarios.final_state_failure(sim.userdata().get("expected"), state)
    logger.info(
        "simulation final state",
        extra={
            "scenario": sim.scenario.label,
            "outcome": (state.outcome or Outcome.INCOMPLETE).value,
            "window": state.held_window if state.booking_id else None,
            "failure": failure,
            "judge_passed": sim.simulator_verdict.success,
        },
    )
    if failure:
        sim.fail(reason=f"final state: {failure}")


server = AgentServer()


# Explicit dispatch: rooms must ask for "riley".
@server.rtc_session(agent_name="riley", on_simulation_end=check_final_state)
async def entrypoint(ctx: JobContext) -> None:
    call_id = ctx.job.id
    ctx.log_context_fields = {"call_id": call_id}
    # Phone calls (SIP participants) get their own label in M6.
    channel = "console" if ctx.is_fake_job() else "web"

    # Under an agent simulation (tests/scenarios), this call gets its own calendar and a fixed
    # clock, and its turn metrics are labelled so they never mix with real web calls. Nothing
    # else changes: the simulator tests what callers get. In production this is None.
    if (sim := ctx.simulation_context()) is not None:
        # session.start connects the room while the greeting starts, which saves time on real
        # calls. A text simulation has no audio to wait for, so the greeting could reach the
        # room before it was connected ("cannot access local participant before connecting",
        # local runs, 2026-10-25). Connecting first, as LiveKit's simulation example does.
        await ctx.connect()
        text = sim.simulation_mode == SimulationMode.SIMULATION_MODE_TEXT
        channel = "sim_text" if text else "sim_audio"
        at = scenarios.scenario_now(sim.userdata(), tools.TZ)
        tools.start_simulation(call_id, Path(tempfile.mkdtemp(prefix="riley-sim-")), at)

        async def end_simulation() -> None:
            tools.end_simulation(call_id)

        ctx.add_shutdown_callback(end_simulation)
        logger.info("simulated call", extra={"scenario": sim.scenario.label, "now": at.isoformat()})

    state = CallState(call_id=call_id)  # everything Riley learns on this call; tools write it

    session = AgentSession[CallState](
        stt=deepgram.STT(model="nova-3", language="en-US", keyterm=["Kestrel"]),
        llm=build_llm(),
        tts=deepgram.TTS(model=TTS_VOICE),
        # The audio turn detector is also the default; it's explicit here because it's what
        # stops Riley cutting in when a caller pauses mid-sentence. Interruptions, false-
        # interruption recovery and preemptive generation use their defaults (all on).
        # Endpointing starts at the detector's defaults; tools.endpointing_for adjusts it per
        # question (shorter max for short answers, longer min for digits).
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            endpointing={
                "min_delay": tools.DEFAULT_MIN_DELAY,
                "max_delay": tools.DEFAULT_MAX_DELAY,
            },
        ),
        user_away_timeout=SILENCE_SECONDS,
        userdata=state,
        # What TTS hears: LiveKit's markdown and emoji filters (the defaults, kept); no second
        # acknowledgement after tools.py's spoken "Got it." (first, so a dropped "Thanks,
        # Jordan." doesn't use up the name); no second "You're all set" after the booking
        # line; the caller's name at most once per call; then numbers spoken the way people
        # say them. The transcript gets all but the last (Riley).
        tts_text_transforms=[
            "filter_markdown",
            "filter_emoji",
            *spoken_guards(state),
            speak_numbers_stream,
        ],
    )

    pairer = TurnPairer(call_id=call_id, channel=channel, session_started_at=time.time())
    writer = JsonlWriter(METRICS_DIR)

    async def end_with(line: str, by: str, clip: Clip | None = None) -> None:
        """Say a final line nobody can talk over, then close the session (see finish_call).
        With a clip, it plays instead of TTS."""
        logger.info("hanging up", extra={"by": by})
        session.interrupt()
        audio = clip_frames(clip) if clip is not None else None
        try:
            await session.say(line, audio=audio, allow_interruptions=False)
        except RuntimeError:  # already closing for another reason
            return
        session.shutdown()

    # A model that fails for good: say why, then hang up.
    session.on("error", close_on_fatal_error(end_with))

    # --- Silence: two check-ins, then a polite close ------------------------------------
    silence = SilenceMonitor(
        say=lambda line: session.say(line),  # a SpeechHandle resolves when playout ends
        close=lambda line: end_with(line, by="silence"),
        wait_seconds=SILENCE_SECONDS,
        prompts=SILENCE_PROMPTS,
        still_there=prompts.STILL_THERE,
        goodbye=prompts.SILENCE_GOODBYE,
    )

    # --- Half a number: wait for the rest (turns.py) --------------------------------------
    # If the caller has really stopped, the held words become a normal turn and get a reply.
    digit_hold = DigitHold(
        lambda: state.expecting, reply=lambda text: session.generate_reply(user_input=text)
    )

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent) -> None:
        # Riley speaking doesn't clear "away"; only caller activity does, so the check-in
        # isn't cancelled by its own "Are you still there?".
        silence.on_user_state(ev.new_state)
        if ev.new_state == "speaking":
            digit_hold.on_caller_speaking()
        elif ev.new_state == "listening":
            digit_hold.on_caller_silent()

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
            state.acknowledged = False  # this new turn may get its own "Got it."
            state.confirmed_aloud = False
        record = pairer.add(ev.item.role, ev.item.metrics or {})
        if record:
            writer.write(record)
            logger.info("turn metrics", extra=record)

    # --- The web page's own measurement of the greeting (what the caller waited) --------
    timing_reads: set[asyncio.Task[None]] = set()

    async def read_client_timing(reader: rtc.TextStreamReader) -> None:
        record = client_timing_record(await reader.read_all(), call_id, channel)
        if record is None:
            logger.info("client timing ignored: not a valid measurement")
            return
        writer.write(record)
        logger.info("turn metrics", extra=record)  # same log line, so metrics_from_logs finds it

    def on_client_timing(reader: rtc.TextStreamReader, participant_identity: str) -> None:
        task = asyncio.create_task(read_client_timing(reader))
        timing_reads.add(task)  # a reference, so the task isn't garbage-collected mid-read
        task.add_done_callback(timing_reads.discard)

    ctx.room.register_text_stream_handler(CLIENT_TIMING_TOPIC, on_client_timing)

    # --- Maximum call length, to protect the free quotas --------------------------------
    async def time_limit() -> None:
        await asyncio.sleep(MAX_CALL_SECONDS)
        await end_with(prompts.TIME_LIMIT_GOODBYE, by="time_limit")

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

    async def drain_leads() -> None:
        # A shutdown callback, not a step in finish_call: deleting the room starts the job's
        # shutdown by itself, and only shutdown callbacks are awaited before the process ends.
        await tools.drain_leads(LEAD_DRAIN_SECONDS)

    ctx.add_shutdown_callback(drain_leads)

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
        # user_initiated: our code or end_call closed it ("hanging up" logs say which);
        # participant_disconnected: the caller hung up.
        logger.info(
            "call outcome", extra={"outcome": state.outcome.value, "close_reason": str(ev.reason)}
        )
        finishing = asyncio.create_task(finish_call(f"session closed: {ev.reason}"))

    # The transcript gets its own guards (NameGuard keeps per-call state), fed the same text.
    transcript = spoken_guards(state)
    agent = Riley(transcript_transforms=transcript, digit_hold=digit_hold)

    # --- Hanging up under an agent simulation --------------------------------------------
    # The simulator collects check_final_state's verdict over a link that closes with the
    # session, so when Riley hangs up, a wrong final state never reached it: the run was
    # graded on the transcript alone (first simulation runs, 2026-10-25; livekit-agents
    # 1.8.8). Every hang-up (end_call, a gate, silence, the time limit) goes through
    # session.shutdown, so in a simulation it checks first:
    # - final state right: hang up exactly as in production. Nothing to report, and the
    #   judge sees the same ending callers get.
    # - final state wrong: keep the line open and stop answering, so the simulator ends the
    #   call and check_final_state fails the run. (Leaving it open every time made the judge
    #   fail right endings: the simulated caller kept talking to a silent Riley.)
    if sim is not None:
        expected = sim.userdata().get("expected")
        hang_up_for_real = session.shutdown
        hung_up = False

        def hang_up(*, drain: bool = True) -> None:
            nonlocal hung_up
            if scenarios.final_state_failure(expected, state) is None:
                hang_up_for_real(drain=drain)
                return
            if hung_up:
                return
            hung_up = True
            silence.stop()
            if limit_task is not None:
                limit_task.cancel()
            logger.info("wrong final state: line left open for the simulator to grade")

        session.shutdown = hang_up  # type: ignore[method-assign]
        agent = SimulatedRiley(
            lambda: hung_up, transcript_transforms=transcript, digit_hold=digit_hold
        )

    await session.start(
        agent=agent,
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

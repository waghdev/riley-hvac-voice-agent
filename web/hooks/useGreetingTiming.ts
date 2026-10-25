'use client';

import { useEffect, useRef, useState } from 'react';
import { useAgent, useSessionContext } from '@livekit/components-react';

/**
 * How long a visitor waits for Riley's first words, measured where they experience it.
 *
 * - click_to_speech_ms: "Start call" pressed -> Riley starts speaking
 * - connect_to_speech_ms: room connected -> Riley starts speaking (CLAUDE.md's greeting target)
 *
 * "Speaking" is the agent's own state attribute (lk.agent.state), so this includes the time that
 * update takes to reach the browser. Sent once per call to the agent as a text stream on
 * TIMING_TOPIC, which logs it next to its own metrics; also returned for display.
 */
export const TIMING_TOPIC = 'riley.client_timing';

export type GreetingTiming = { clickToSpeechMs: number; connectToSpeechMs: number };

export function useGreetingTiming(clickedAt: number | null): GreetingTiming | null {
  const { room, isConnected } = useSessionContext();
  const agent = useAgent();
  const connectedAt = useRef<number | null>(null);
  const [timing, setTiming] = useState<GreetingTiming | null>(null);

  useEffect(() => {
    if (!isConnected) {
      connectedAt.current = null;
      setTiming(null);
    } else if (connectedAt.current === null) {
      connectedAt.current = performance.now();
    }
  }, [isConnected]);

  useEffect(() => {
    if (timing || clickedAt === null || connectedAt.current === null) return;
    if (agent.state !== 'speaking') return;
    const now = performance.now();
    const measured = {
      clickToSpeechMs: Math.round(now - clickedAt),
      connectToSpeechMs: Math.round(now - connectedAt.current),
    };
    setTiming(measured);
    room.localParticipant
      .sendText(
        JSON.stringify({
          click_to_speech_ms: measured.clickToSpeechMs,
          connect_to_speech_ms: measured.connectToSpeechMs,
        }),
        { topic: TIMING_TOPIC }
      )
      .catch(() => {}); // a measurement must never break the call
  }, [agent.state, clickedAt, room, timing]);

  return timing;
}

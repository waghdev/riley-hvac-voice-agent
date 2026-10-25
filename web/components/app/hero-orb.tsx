'use client';

import { useTheme } from 'next-themes';
import { type AgentState } from '@livekit/components-react';
import { AgentAudioVisualizerAura } from '@/components/agents-ui/agent-audio-visualizer-aura';

/** Riley's color: the cool side of "heating and cooling". The page's glows add the warm side. */
export const ORB_COLOR = '#38BDF8';

interface HeroOrbProps {
  /** Idles until the visitor can call, pulses when ready, spins up while connecting. */
  state: AgentState;
}

/** The landing page's voice orb: the same shader that reacts to Riley's voice during a call. */
export function HeroOrb({ state }: HeroOrbProps) {
  const { resolvedTheme } = useTheme();
  return (
    <div className="relative grid place-items-center" aria-hidden="true">
      {/* A soft halo behind the orb, cool on top and warm below. */}
      <div className="absolute inset-6 rounded-full bg-gradient-to-b from-sky-400/25 via-cyan-300/10 to-amber-400/20 blur-3xl" />
      <AgentAudioVisualizerAura
        state={state}
        color={ORB_COLOR}
        colorShift={0.35}
        themeMode={resolvedTheme === 'light' ? 'light' : 'dark'}
        className="relative size-[220px] md:size-[280px]"
      />
    </div>
  );
}

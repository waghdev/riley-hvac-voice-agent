'use client';

import { useTheme } from 'next-themes';
import { AnimatePresence, motion } from 'motion/react';
import { useAgent, useSessionContext } from '@livekit/components-react';
import { AgentSessionView_01 } from '@/components/agents-ui/blocks/agent-session-view-01';
import { ORB_COLOR } from '@/components/app/hero-orb';
import { WelcomeView } from '@/components/app/welcome-view';
import { useGreetingTiming } from '@/hooks/useGreetingTiming';

const MotionWelcomeView = motion.create(WelcomeView);
const MotionSessionView = motion.create(AgentSessionView_01);

const VIEW_MOTION_PROPS = {
  variants: {
    visible: {
      opacity: 1,
    },
    hidden: {
      opacity: 0,
    },
  },
  initial: 'hidden',
  animate: 'visible',
  exit: 'hidden',
  transition: {
    duration: 0.5,
    ease: 'linear',
  },
};

interface ViewControllerProps {
  turnstileSiteKey: string;
  onTurnstileToken: (token: string | null) => void;
  turnstileReset: number;
  canStart: boolean;
  starting: boolean;
  refusal: string | null;
  onStartCall: () => void;
  clickedAt: number | null;
}

export function ViewController({ clickedAt, ...welcome }: ViewControllerProps) {
  const { isConnected } = useSessionContext();
  const agent = useAgent();
  const { resolvedTheme } = useTheme();
  const timing = useGreetingTiming(clickedAt);

  return (
    <AnimatePresence mode="wait">
      {/* Welcome view */}
      {!isConnected && <MotionWelcomeView key="welcome" {...VIEW_MOTION_PROPS} {...welcome} />}
      {/* Session view: voice only, so no chat input, camera or screen share */}
      {isConnected && (
        <MotionSessionView
          key="session-view"
          {...VIEW_MOTION_PROPS}
          preConnectMessage={agent.isConnected ? 'Riley is listening' : 'Connecting you to Riley…'}
          supportsChatInput={false}
          supportsVideoInput={false}
          supportsScreenShare={false}
          isPreConnectBufferEnabled={true}
          // The landing page's orb, now reacting to Riley's voice.
          audioVisualizerType="aura"
          audioVisualizerColor={ORB_COLOR}
          audioVisualizerColorShift={0.35}
          themeMode={resolvedTheme === 'light' ? 'light' : 'dark'}
          className="fixed inset-0"
        />
      )}
      {isConnected && timing && (
        <p
          key="timing"
          className="text-muted-foreground fixed top-16 left-1/2 z-50 -translate-x-1/2 font-mono text-xs whitespace-nowrap md:top-6"
        >
          Riley picked up {(timing.connectToSpeechMs / 1000).toFixed(1)} s after connecting
        </p>
      )}
    </AnimatePresence>
  );
}

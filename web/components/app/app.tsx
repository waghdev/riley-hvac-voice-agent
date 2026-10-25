'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import { TokenSource } from 'livekit-client';
import { useSession } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { refusalMessage } from '@/lib/refusals';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

function AppSetup() {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors();

  return null;
}

/** Thrown by the token source when /api/token refuses, so start() fails without a toast. */
class CallRefused extends Error {}

interface AppProps {
  turnstileSiteKey: string;
}

export function App({ turnstileSiteKey }: AppProps) {
  // The Turnstile token is single-use: held in a ref for the token source, mirrored in state
  // so the start button knows when it may be pressed.
  const turnstileToken = useRef<string | null>(null);
  const [hasTurnstileToken, setHasTurnstileToken] = useState(false);
  const [turnstileReset, setTurnstileReset] = useState(0);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [clickedAt, setClickedAt] = useState<number | null>(null);

  const onTurnstileToken = useCallback((token: string | null) => {
    turnstileToken.current = token;
    setHasTurnstileToken(token !== null);
  }, []);

  // TokenSource.literal with a function: a fresh request for every call, no caching. (A cached
  // token, as TokenSource.custom/endpoint keep, could rejoin a room and skip the checks.)
  const tokenSource = useMemo(
    () =>
      TokenSource.literal(async () => {
        const token = turnstileToken.current;
        turnstileToken.current = null; // spent, whatever the answer
        setHasTurnstileToken(false);
        setTurnstileReset((n) => n + 1);
        const res = await fetch('/api/token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ turnstile_token: token }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setRefusal(refusalMessage(data.error));
          throw new CallRefused(String(data.error));
        }
        return { serverUrl: data.server_url, participantToken: data.participant_token };
      }),
    []
  );

  const session = useSession(tokenSource);

  const startCall = useCallback(async () => {
    setRefusal(null);
    setClickedAt(performance.now());
    try {
      await session.start();
    } catch (error) {
      if (!(error instanceof CallRefused)) setRefusal(refusalMessage('unavailable'));
    }
  }, [session]);

  return (
    <AgentSessionProvider session={session}>
      <AppSetup />
      <main className="grid h-svh grid-cols-1 place-content-center">
        <ViewController
          turnstileSiteKey={turnstileSiteKey}
          onTurnstileToken={onTurnstileToken}
          turnstileReset={turnstileReset}
          canStart={hasTurnstileToken}
          refusal={refusal}
          onStartCall={startCall}
          clickedAt={clickedAt}
        />
      </main>
      <StartAudioButton label="Start Audio" />
      <Toaster
        icons={{
          warning: <WarningIcon weight="bold" />,
        }}
        position="top-center"
        className="toaster group"
        style={
          {
            '--normal-bg': 'var(--popover)',
            '--normal-text': 'var(--popover-foreground)',
            '--normal-border': 'var(--border)',
          } as React.CSSProperties
        }
      />
    </AgentSessionProvider>
  );
}

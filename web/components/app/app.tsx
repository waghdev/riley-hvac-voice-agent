'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { TokenSource } from 'livekit-client';
import { useSession } from '@livekit/components-react';
import { WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { AgentSessionProvider } from '@/components/agents-ui/agent-session-provider';
import { StartAudioButton } from '@/components/agents-ui/start-audio-button';
import { ViewController } from '@/components/app/view-controller';
import { Toaster } from '@/components/ui/sonner';
import { useAgentErrors } from '@/hooks/useAgentErrors';
import { useDebugMode } from '@/hooks/useDebug';
import { CallRefused, createCallTokenSource } from '@/lib/call-token-source';
import { refusalMessage } from '@/lib/refusals';

const IN_DEVELOPMENT = process.env.NODE_ENV !== 'production';

function AppSetup() {
  useDebugMode({ enabled: IN_DEVELOPMENT });
  useAgentErrors();

  return null;
}

interface AppProps {
  turnstileSiteKey: string;
  /** The LiveKit server URL (public: it's in every token response), for the connection warm-up. */
  livekitUrl?: string;
}

export function App({ turnstileSiteKey, livekitUrl }: AppProps) {
  // The Turnstile token is single-use: held in a ref for the token source, mirrored in state
  // so the start button knows when it may be pressed.
  const turnstileToken = useRef<string | null>(null);
  const [hasTurnstileToken, setHasTurnstileToken] = useState(false);
  const [turnstileReset, setTurnstileReset] = useState(0);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [clickedAt, setClickedAt] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);

  const onTurnstileToken = useCallback((token: string | null) => {
    turnstileToken.current = token;
    setHasTurnstileToken(token !== null);
  }, []);

  // Only the Call button may ask /api/token for a token (see lib/call-token-source.ts).
  const calls = useMemo(
    () =>
      createCallTokenSource({
        turnstileToken: () => turnstileToken.current,
        onTurnstileSpent: () => {
          turnstileToken.current = null;
          setHasTurnstileToken(false);
          setTurnstileReset((n) => n + 1);
        },
      }),
    []
  );
  const tokenSource = useMemo(() => TokenSource.literal(() => calls.fetch()), [calls]);

  const session = useSession(tokenSource);

  // Our own warm-up, since the hook's needs a token: DNS, TLS and the region lookup for the
  // LiveKit server happen while the visitor reads the page, not after they press Call.
  const { room } = session;
  useEffect(() => {
    if (livekitUrl) room.prepareConnection(livekitUrl).catch(() => {});
  }, [room, livekitUrl]);

  const startCall = useCallback(async () => {
    setRefusal(null);
    setClickedAt(performance.now());
    setStarting(true);
    calls.request();
    try {
      await session.start();
    } catch (error) {
      setRefusal(refusalMessage(error instanceof CallRefused ? error.code : 'unavailable'));
    } finally {
      calls.cancel();
      setStarting(false);
    }
  }, [session, calls]);

  return (
    <AgentSessionProvider session={session}>
      <AppSetup />
      <main className="min-h-svh">
        <ViewController
          turnstileSiteKey={turnstileSiteKey}
          onTurnstileToken={onTurnstileToken}
          turnstileReset={turnstileReset}
          canStart={hasTurnstileToken}
          starting={starting}
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

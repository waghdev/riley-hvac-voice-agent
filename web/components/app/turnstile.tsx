'use client';

import { useEffect, useRef } from 'react';

/**
 * Cloudflare Turnstile widget (explicit rendering). Calls onToken with a single-use token once
 * Cloudflare is satisfied, and with null when the token expires or fails. Bump `resetSignal`
 * after a token has been spent to get a fresh one.
 */

type TurnstileApi = {
  render(el: HTMLElement, options: Record<string, unknown>): string;
  reset(widgetId: string): void;
  remove(widgetId: string): void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
let scriptLoading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  scriptLoading ??= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = SCRIPT_URL;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptLoading = null; // let a later render try again
      reject(new Error('Turnstile failed to load'));
    };
    document.head.appendChild(script);
  });
  return scriptLoading;
}

interface TurnstileProps {
  siteKey: string;
  onToken: (token: string | null) => void;
  resetSignal: number;
}

export function Turnstile({ siteKey, onToken, resetSignal }: TurnstileProps) {
  const container = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | null>(null);
  const latestOnToken = useRef(onToken);
  latestOnToken.current = onToken;

  useEffect(() => {
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !container.current || !window.turnstile) return;
        widgetId.current = window.turnstile.render(container.current, {
          sitekey: siteKey,
          action: 'start-call',
          theme: 'auto',
          size: 'flexible',
          callback: (token: string) => latestOnToken.current(token),
          'expired-callback': () => latestOnToken.current(null),
          'error-callback': () => latestOnToken.current(null),
        });
      })
      .catch(() => latestOnToken.current(null));
    return () => {
      cancelled = true;
      if (widgetId.current && window.turnstile) window.turnstile.remove(widgetId.current);
      widgetId.current = null;
    };
  }, [siteKey]);

  useEffect(() => {
    if (resetSignal > 0 && widgetId.current && window.turnstile) {
      latestOnToken.current(null);
      window.turnstile.reset(widgetId.current);
    }
  }, [resetSignal]);

  return <div ref={container} className="w-72 max-w-full" />;
}

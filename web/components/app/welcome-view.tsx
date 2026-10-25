import { Turnstile } from '@/components/app/turnstile';
import { Button } from '@/components/ui/button';

function WelcomeImage() {
  // A phone handset: Riley is a phone agent, reached here from the browser.
  return (
    <svg
      width="64"
      height="64"
      viewBox="0 0 256 256"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="text-fg0 mb-4 size-14"
      aria-hidden="true"
    >
      <path
        d="M222 158.4 175.6 137.6a20 20 0 0 0-19 1.7l-24.8 16.5a76 76 0 0 1-31.6-31.4l16.4-25a20 20 0 0 0 1.6-18.9L97.6 34a20 20 0 0 0-20.8-12A52.3 52.3 0 0 0 30 74c0 83.8 68.2 152 152 152a52.3 52.3 0 0 0 52-46.8 20 20 0 0 0-12-20.8Z"
        fill="currentColor"
      />
    </svg>
  );
}

interface WelcomeViewProps {
  turnstileSiteKey: string;
  onTurnstileToken: (token: string | null) => void;
  turnstileReset: number;
  canStart: boolean;
  refusal: string | null;
  onStartCall: () => void;
}

export const WelcomeView = ({
  turnstileSiteKey,
  onTurnstileToken,
  turnstileReset,
  canStart,
  refusal,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    <div ref={ref} className="px-4">
      <section className="bg-background flex flex-col items-center justify-center text-center">
        <WelcomeImage />

        <h1 className="text-foreground text-2xl font-semibold tracking-tight">
          Kestrel Comfort Heating &amp; Air
        </h1>
        <p className="text-foreground max-w-prose pt-2 leading-6 font-medium">
          Talk to Riley, the AI receptionist who answers our phones
        </p>
        <p className="text-muted-foreground max-w-md pt-3 text-sm leading-6 text-pretty">
          Tell her your AC is blowing warm air and she&apos;ll book a technician. Use a made-up
          name, a 555 number and a Phoenix ZIP like 85016. You can also ask about prices, give a ZIP
          outside Phoenix, or say you smell gas.
        </p>

        <div className="mt-6 flex min-h-[65px] items-center justify-center">
          <Turnstile
            siteKey={turnstileSiteKey}
            onToken={onTurnstileToken}
            resetSignal={turnstileReset}
          />
        </div>

        <Button
          size="lg"
          onClick={onStartCall}
          disabled={!canStart}
          className="mt-4 w-64 rounded-full font-mono text-xs font-bold tracking-wider uppercase"
        >
          Call Riley
        </Button>

        <p
          role="status"
          aria-live="polite"
          className="text-foreground mt-4 min-h-6 max-w-md text-sm"
        >
          {refusal}
        </p>
      </section>

      <div className="fixed bottom-5 left-0 flex w-full items-center justify-center px-4">
        <p className="text-muted-foreground max-w-prose pt-1 text-center text-xs leading-5 font-normal text-pretty">
          Kestrel Comfort is a fictional business, and Riley is a demo: please don&apos;t share real
          personal details. Calls end after 5 minutes. Demo by Dev Wagh, Scaile AI.
        </p>
      </div>
    </div>
  );
};

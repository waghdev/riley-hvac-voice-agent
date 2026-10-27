import { type AgentState } from '@livekit/components-react';
import {
  ArrowRightIcon,
  BrainIcon,
  CalendarCheckIcon,
  FlameIcon,
  LightningIcon,
  MapPinIcon,
  MicrophoneIcon,
  PhoneIcon,
  SpeakerHighIcon,
  WaveformIcon,
} from '@phosphor-icons/react/dist/ssr';
import { HeroOrb } from '@/components/app/hero-orb';
import { AUTHOR, SocialLinks } from '@/components/app/social-links';
import { Turnstile } from '@/components/app/turnstile';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/shadcn/utils';

// Every claim here is something Riley does today; keep it that way (README, docs/decisions.md).
const CAPABILITIES = [
  {
    Icon: CalendarCheckIcon,
    title: 'Books the visit',
    body: 'Offers open windows, reads back your number and the time, and books only after you confirm.',
  },
  {
    Icon: FlameIcon,
    title: 'Safety first',
    body: 'Mention a gas smell or a CO alarm and she gives the safety steps word for word, then ends the call.',
  },
  {
    Icon: MapPinIcon,
    title: 'Knows the rules',
    body: "Out-of-area ZIPs and services the company doesn't offer are turned away by code, not the model, and she never invents a price.",
  },
  {
    Icon: LightningIcon,
    title: 'Real-time voice',
    body: 'Streaming speech in and out on LiveKit, with a turn detector so she waits while you think.',
  },
];

const TRY_SAYING = [
  'My AC is blowing warm air',
  'How much is a visit?',
  'Do you come out to 85301?',
  'I smell gas',
];

const PIPELINE = [
  { Icon: MicrophoneIcon, label: 'You speak' },
  { Icon: WaveformIcon, label: 'Deepgram Nova-3', note: 'speech to text' },
  { Icon: BrainIcon, label: 'Gemini Flash-Lite', note: 'plus Python decision gates' },
  { Icon: SpeakerHighIcon, label: 'Deepgram Aura-2', note: 'text to speech' },
  { Icon: PhoneIcon, label: 'Riley answers' },
];

/** Cool and warm glows plus a faint grid: heating and cooling. Decorative only. */
function Backdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute -top-40 -left-40 size-[36rem] rounded-full bg-sky-500/20 blur-[120px] dark:bg-sky-500/15" />
      <div className="absolute -right-40 -bottom-48 size-[36rem] rounded-full bg-amber-500/20 blur-[120px] dark:bg-amber-500/10" />
      <div
        className="absolute inset-0 opacity-[0.06] dark:opacity-[0.08]"
        style={{
          backgroundImage:
            'linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at 50% 30%, black 20%, transparent 70%)',
        }}
      />
    </div>
  );
}

interface WelcomeViewProps {
  turnstileSiteKey: string;
  onTurnstileToken: (token: string | null) => void;
  turnstileReset: number;
  canStart: boolean;
  starting: boolean;
  refusal: string | null;
  onStartCall: () => void;
}

export const WelcomeView = ({
  turnstileSiteKey,
  onTurnstileToken,
  turnstileReset,
  canStart,
  starting,
  refusal,
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  const orbState: AgentState = starting ? 'connecting' : canStart ? 'listening' : 'idle';

  return (
    <div ref={ref} className="relative w-full">
      <Backdrop />

      {/* Hero: the orb, who Riley is, and the call itself */}
      <section className="mx-auto flex max-w-3xl flex-col items-center px-4 pt-20 text-center md:pt-24">
        <p className="border-border bg-background/60 text-muted-foreground inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs backdrop-blur">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
          </span>
          Live demo · fictional HVAC company in Phoenix
        </p>

        <HeroOrb state={orbState} />

        <h1 className="text-foreground -mt-4 text-4xl font-semibold tracking-tight md:text-6xl">
          Meet{' '}
          <span className="bg-gradient-to-r from-sky-400 via-cyan-300 to-amber-300 bg-clip-text text-transparent">
            Riley
          </span>
        </h1>
        <p className="text-muted-foreground mt-4 max-w-xl text-base leading-7 text-pretty md:text-lg">
          The AI receptionist for Kestrel Comfort Heating &amp; Air. She answers the phone, works
          out what you need, and books the technician, in real time.
        </p>

        {/* The call card */}
        <div className="border-border bg-background/70 mt-8 flex w-full max-w-md flex-col items-center gap-4 rounded-3xl border p-6 shadow-[0_0_80px_-20px] shadow-sky-500/30 backdrop-blur">
          <div className="flex min-h-[65px] w-full items-center justify-center">
            <Turnstile
              siteKey={turnstileSiteKey}
              onToken={onTurnstileToken}
              resetSignal={turnstileReset}
            />
          </div>
          <Button
            size="lg"
            onClick={onStartCall}
            disabled={!canStart || starting}
            className="h-12 w-full rounded-full font-mono text-xs font-bold tracking-wider uppercase"
          >
            <PhoneIcon weight="fill" />
            {starting ? 'Connecting…' : 'Call Riley'}
          </Button>
          <p
            role="status"
            aria-live="polite"
            className={cn('text-sm', refusal ? 'text-foreground' : 'text-muted-foreground')}
          >
            {refusal ??
              (canStart
                ? 'Allow your microphone when asked. Calls last up to 5 minutes.'
                : 'One quick check that you’re human, then you can call.')}
          </p>
        </div>

        {/* Things to try */}
        <div className="mt-6 flex max-w-xl flex-wrap justify-center gap-2">
          {TRY_SAYING.map((line) => (
            <span
              key={line}
              className="border-border bg-background/60 text-muted-foreground rounded-full border px-3 py-1 text-xs backdrop-blur"
            >
              “{line}”
            </span>
          ))}
        </div>
        <p className="text-muted-foreground mt-3 max-w-md text-xs leading-5 text-pretty">
          Use a made-up name, a 555 number and a Phoenix ZIP like 85016.
        </p>
      </section>

      {/* What Riley can do */}
      <section
        aria-label="What Riley can do"
        className="mx-auto mt-16 grid max-w-5xl grid-cols-1 gap-4 px-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        {CAPABILITIES.map(({ Icon, title, body }) => (
          <div
            key={title}
            className="border-border bg-background/60 rounded-2xl border p-5 text-left backdrop-blur"
          >
            <span className="inline-flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-sky-400/20 to-amber-400/20 text-sky-400">
              <Icon size={20} weight="duotone" />
            </span>
            <h2 className="text-foreground mt-3 text-sm font-semibold">{title}</h2>
            <p className="text-muted-foreground mt-1 text-sm leading-6">{body}</p>
          </div>
        ))}
      </section>

      {/* How a turn works */}
      <section aria-label="How a turn works" className="mx-auto mt-16 max-w-5xl px-4">
        <h2 className="text-muted-foreground text-center font-mono text-xs font-bold tracking-wider uppercase">
          How a turn works
        </h2>
        <ol className="mt-5 flex flex-col items-center justify-center gap-2 md:flex-row md:gap-0">
          {PIPELINE.map(({ Icon, label, note }, i) => (
            <li key={label} className="flex flex-col items-center md:flex-row">
              <div className="border-border bg-background/60 flex w-56 items-center gap-3 rounded-xl border px-3 py-2 backdrop-blur md:w-auto">
                <Icon size={18} weight="duotone" className="shrink-0 text-sky-400" />
                <div className="text-left">
                  <p className="text-foreground text-sm leading-5">{label}</p>
                  {note && <p className="text-muted-foreground text-xs leading-4">{note}</p>}
                </div>
              </div>
              {i < PIPELINE.length - 1 && (
                <ArrowRightIcon
                  size={16}
                  className="text-muted-foreground mx-2 my-1 rotate-90 md:rotate-0"
                />
              )}
            </li>
          ))}
        </ol>
        <p className="text-muted-foreground mx-auto mt-4 max-w-2xl text-center text-xs leading-5 text-pretty">
          The model listens and talks; it never decides. Whether a ZIP is served, a call is urgent
          or a booking may happen is decided by plain Python, so a confused or manipulated model
          can&apos;t book an out-of-area caller.
        </p>
      </section>

      {/* Footer */}
      <footer className="mx-auto mt-16 flex max-w-5xl flex-col items-center gap-3 px-4 pb-10 text-center">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-sm">Built by {AUTHOR.name}</span>
          <SocialLinks />
        </div>
        <p className="text-muted-foreground max-w-xl text-xs leading-5 text-pretty">
          Kestrel Comfort is a fictional business, and Riley is a demo: please don&apos;t share real
          personal details. Riley&apos;s replies come from Google Gemini&apos;s free tier, which may
          use what you say to improve Google&apos;s models. Built with{' '}
          <a
            href="https://docs.livekit.io/agents"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-foreground underline underline-offset-4"
          >
            LiveKit Agents
          </a>
          .
        </p>
      </footer>
    </div>
  );
};

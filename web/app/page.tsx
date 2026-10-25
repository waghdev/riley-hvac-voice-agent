import { App } from '@/components/app/app';
import { TEST_SITE_KEY } from '@/lib/turnstile';

// Read at request time on the server, so the site key is configured in one place (Vercel's
// environment) rather than baked into the build. Local development falls back to Cloudflare's
// always-pass test key; in production a missing key renders a widget that can't pass, and the
// token endpoint refuses anyway.
export const dynamic = 'force-dynamic';

export default function Page() {
  const siteKey =
    process.env.TURNSTILE_SITE_KEY ||
    (process.env.NODE_ENV === 'development' ? TEST_SITE_KEY : 'missing-site-key');
  return <App turnstileSiteKey={siteKey} />;
}

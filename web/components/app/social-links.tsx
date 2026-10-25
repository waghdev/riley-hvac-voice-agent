import { GithubLogoIcon, LinkedinLogoIcon } from '@phosphor-icons/react/dist/ssr';
import { cn } from '@/lib/shadcn/utils';

export const AUTHOR = {
  name: 'Dev Wagh',
  github: 'https://github.com/waghdev',
  linkedin: 'https://www.linkedin.com/in/devendra-wagh',
};

const LINKS = [
  { href: AUTHOR.github, label: 'Dev Wagh on GitHub', Icon: GithubLogoIcon },
  { href: AUTHOR.linkedin, label: 'Dev Wagh on LinkedIn', Icon: LinkedinLogoIcon },
];

/** GitHub and LinkedIn icon links. */
export function SocialLinks({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center gap-1', className)}>
      {LINKS.map(({ href, label, Icon }) => (
        <a
          key={href}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={label}
          title={label}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring rounded-full p-2 transition-colors focus-visible:ring-2 focus-visible:outline-none"
        >
          <Icon size={20} weight="fill" />
        </a>
      ))}
    </div>
  );
}

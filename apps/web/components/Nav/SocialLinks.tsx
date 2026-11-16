import { ExternalLink } from '@/components/Icon';
import type { Translator } from '@/lib/i18n';
import { socialLinks } from '@/lib/social';
import styles from './SocialLinks.module.css';

/** LinkedIn, X (Twitter) and GitHub as text links (design.md 5.5). Empty variables hide a link. */
export function SocialLinks({ t, className }: { t: Translator; className?: string }) {
  const links = socialLinks();
  if (links.length === 0) return null;
  return (
    <ul className={[styles.links, className ?? ''].join(' ')}>
      {links.map((l) => (
        <li key={l.key}>
          <a href={l.href} target="_blank" rel="noopener noreferrer" className={styles.link} lang="en">
            {t(`social.${l.key}`)}
            <ExternalLink size={16} aria-hidden="true" />
            <span className="visually-hidden"> {t('social.newTab')}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

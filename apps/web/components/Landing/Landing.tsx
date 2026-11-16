import Link from 'next/link';
import type { ReactNode } from 'react';
import type { PublicDistrictRisk } from '@fasalalert/shared/api';
import {
  ArrowRight, BadgeCheck, BookOpen, CircleCheck, CloudRain, CloudSun, CropIcon, Database, IndianRupee, Languages, MapIcon, Mic,
  Phone, ShieldCheck, Sprout, ThermometerSnowflake, TriangleAlert, Truck,
} from '@/components/Icon';
import { SocialLinks } from '@/components/Nav/SocialLinks';
import { Wordmark } from '@/components/Nav/Wordmark';
import { RiskBadge } from '@/components/Risk/RiskBadge';
import { KISAN_CALL_CENTRE } from '@/lib/config';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { rankDistricts, type DisplayLevel } from '@/lib/risk';
import { loc } from '@/lib/view';
import styles from './Landing.module.css';

const CROPS = ['mango', 'pomegranate', 'grape', 'cotton', 'soybean', 'sugarcane'] as const;

export interface LandingBoard { districts: PublicDistrictRisk[]; generatedAt: string | null; live: boolean; timeIst: string | null }

/**
 * The landing page at `/` (docs/UX_QA_AUDIT.md FLOW-01): what FasalAlert does, for whom, how it decides,
 * what it cannot do, and one way in. Everything numeric on this page is live data from the public board;
 * the decision diagram has labels, not invented values.
 */
export function Landing({ t, locale, board, preview }: { t: Translator; locale: Locale; board: LandingBoard | null; preview: ReactNode }) {
  // The landing page has one way forward: sign in (a signed-in visitor is sent on to Home from there).
  const start = `/${locale}/signin`;
  const top = board ? rankDistricts(board.districts.map((d) => ({ ...d, level: d.level as DisplayLevel }))) : [];
  return (
    <>
      <main id="main" tabIndex={-1} className={styles.main}>
        <section className={styles.hero} aria-labelledby="hero-title">
          <div className={styles.heroText}>
            <p className={styles.eyebrow}><Sprout size={18} aria-hidden="true" /> {t('landing.eyebrow')}</p>
            <h1 id="hero-title" className={styles.h1}>{t('landing.title')}</h1>
            <p className={styles.lead}>{t('landing.lead')}</p>
            <div className={styles.ctas}>
              <Link href={start} className={styles.primary}>{t('landing.getStarted')}<ArrowRight size={20} aria-hidden="true" /></Link>
              <a href="#how" className={styles.secondary}>{t('landing.learnMore')}</a>
            </div>
            <ul className={styles.points}>
              <li><CircleCheck size={18} aria-hidden="true" /> {t('landing.point.phone')}</li>
              <li><CircleCheck size={18} aria-hidden="true" /> {t('landing.point.languages')}</li>
              <li><CircleCheck size={18} aria-hidden="true" /> {t('landing.point.sources')}</li>
            </ul>
          </div>
          <figure className={styles.flow} aria-labelledby="flow-cap">
            <figcaption id="flow-cap" className={styles.flowCap}>{t('landing.flow.caption')}</figcaption>
            <ol className={styles.inputs}>
              <li className={styles.node}><CloudSun size={22} aria-hidden="true" /><span><strong>{t('landing.flow.weather')}</strong><span>{t('landing.flow.weatherSub')}</span></span></li>
              <li className={styles.node}><Sprout size={22} aria-hidden="true" /><span><strong>{t('landing.flow.stage')}</strong><span>{t('landing.flow.stageSub')}</span></span></li>
              <li className={styles.node}><ThermometerSnowflake size={22} aria-hidden="true" /><span><strong>{t('landing.flow.limits')}</strong><span>{t('landing.flow.limitsSub')}</span></span></li>
            </ol>
            <div className={styles.arrow} aria-hidden="true"><span /></div>
            <div className={styles.output}>
              <p className={styles.outputTitle}><BadgeCheck size={20} aria-hidden="true" /> {t('landing.flow.output')}</p>
              <dl className={styles.outputRows}>
                <div><dt>{t('landing.flow.action')}</dt><dd>{t('landing.flow.actionSub')}</dd></div>
                <div><dt>{t('landing.flow.deadline')}</dt><dd>{t('landing.flow.deadlineSub')}</dd></div>
                <div><dt>{t('landing.flow.chance')}</dt><dd>{t('landing.flow.chanceSub')}</dd></div>
                <div><dt>{t('landing.flow.sources')}</dt><dd>{t('landing.flow.sourcesSub')}</dd></div>
              </dl>
            </div>
          </figure>
        </section>

        <section id="features" className={styles.section} aria-labelledby="features-title">
          <div className={styles.sectionHead}>
            <h2 id="features-title" className={styles.h2}>{t('landing.features.title')}</h2>
            <p className={styles.sub}>{t('landing.features.sub')}</p>
          </div>
          <ul className={styles.features}>
            <Feature icon={<BadgeCheck size={24} aria-hidden="true" />} title={t('landing.f.decision')} body={t('landing.f.decisionBody')} />
            <Feature icon={<ThermometerSnowflake size={24} aria-hidden="true" />} title={t('landing.f.frost')} body={t('landing.f.frostBody')} />
            <Feature icon={<CloudRain size={24} aria-hidden="true" />} title={t('landing.f.rain')} body={t('landing.f.rainBody')} />
            <Feature icon={<Truck size={24} aria-hidden="true" />} title={t('landing.f.transport')} body={t('landing.f.transportBody')} />
            <Feature icon={<IndianRupee size={24} aria-hidden="true" />} title={t('landing.f.market')} body={t('landing.f.marketBody')} />
            <Feature icon={<Mic size={24} aria-hidden="true" />} title={t('landing.f.ask')} body={t('landing.f.askBody')} />
          </ul>
        </section>

        <section id="how" className={styles.section} aria-labelledby="how-title">
          <div className={styles.sectionHead}>
            <h2 id="how-title" className={styles.h2}>{t('landing.how.title')}</h2>
          </div>
          <ol className={styles.steps}>
            {[1, 2, 3, 4].map((n) => (
              <li key={n} className={styles.step}>
                <span className={styles.stepNo} aria-hidden="true">{n}</span>
                <h3 className={styles.h3}>{t(`landing.how.s${n}`)}</h3>
                <p className={styles.muted}>{t(`landing.how.s${n}Body`)}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="crops" className={styles.section} aria-labelledby="crops-title">
          <div className={styles.sectionHead}>
            <h2 id="crops-title" className={styles.h2}>{t('landing.crops.title')}</h2>
            <p className={styles.sub}>{t('landing.crops.sub')}</p>
          </div>
          <ul className={styles.crops}>
            {CROPS.map((c) => (
              <li key={c} className={styles.crop}>
                <CropIcon crop={c} size={40} duotone />
                <span className={styles.cropName}>{t(`crop.${c}`)}</span>
                <span className={styles.muted}>{t(`crop.hint.${c}`)}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className={[styles.section, styles.split].join(' ')} aria-labelledby="voice-title">
          <div>
            <h2 id="voice-title" className={styles.h2}><Languages size={26} aria-hidden="true" className={styles.h2Icon} /> {t('landing.voice.title')}</h2>
            <p className={styles.sub}>{t('landing.voice.body')}</p>
            <ul className={styles.checks}>
              <li><CircleCheck size={18} aria-hidden="true" /> {t('landing.voice.p1')}</li>
              <li><CircleCheck size={18} aria-hidden="true" /> {t('landing.voice.p2')}</li>
              <li><CircleCheck size={18} aria-hidden="true" /> {t('landing.voice.p3')}</li>
            </ul>
            <p className={styles.note}>{t('landing.voice.note')}</p>
          </div>
          <div className={styles.examples} aria-label={t('landing.voice.examples')} role="group">
            <p className={styles.exampleLabel}>{t('landing.voice.examples')}</p>
            <p className={styles.example} lang="mr">माझ्या द्राक्ष बागेला दंवाचा धोका आहे का?</p>
            <p className={styles.example} lang="hi">क्या इस हफ़्ते भारी बारिश होगी?</p>
            <p className={styles.example} lang="en">What stage is my cotton at?</p>
          </div>
        </section>

        <section id="outlook" className={[styles.section, styles.split].join(' ')} aria-labelledby="outlook-title">
          <div>
            <h2 id="outlook-title" className={styles.h2}><MapIcon size={26} aria-hidden="true" className={styles.h2Icon} /> {t('landing.outlook.title')}</h2>
            <p className={styles.sub}>{t('landing.outlook.body')}</p>
            {board ? (
              <>
                <p className={styles.stamp}>{board.live ? t('board.live') : t('board.notLive')}{board.timeIst ? ` · ${t('board.updatedAt', { time: board.timeIst })}` : ''}</p>
                {top.length ? (
                  <ol className={styles.topList}>
                    {top.map((d) => (
                      <li key={d.code}><span className={styles.topName}>{loc(d.name, locale)}</span><RiskBadge level={d.level} kind={d.kind ?? undefined} size="sm" t={t} /></li>
                    ))}
                  </ol>
                ) : <p className={styles.muted}>{t('landing.outlook.none', { count: board.districts.length })}</p>}
              </>
            ) : <p className={styles.muted}>{t('landing.outlook.down')}</p>}
            <p className={styles.muted}>{t('landing.outlook.signInToOpen')}</p>
          </div>
          <div className={styles.preview}>{preview}</div>
        </section>

        <section id="trust" className={styles.section} aria-labelledby="trust-title">
          <div className={styles.sectionHead}>
            <h2 id="trust-title" className={styles.h2}><ShieldCheck size={26} aria-hidden="true" className={styles.h2Icon} /> {t('landing.trust.title')}</h2>
            <p className={styles.sub}>{t('landing.trust.sub')}</p>
          </div>
          <div className={styles.trustGrid}>
            <div className={styles.card}>
              <h3 className={styles.h3}><Database size={20} aria-hidden="true" /> {t('landing.trust.data')}</h3>
              <ul className={styles.plain}>
                <li>{t('landing.trust.d1')}</li>
                <li>{t('landing.trust.d2')}</li>
                <li>{t('landing.trust.d3')}</li>
                <li>{t('landing.trust.d4')}</li>
                <li>{t('landing.trust.d5')}</li>
              </ul>
            </div>
            <div className={styles.card}>
              <h3 className={styles.h3}><BookOpen size={20} aria-hidden="true" /> {t('landing.trust.method')}</h3>
              <ul className={styles.plain}>
                <li>{t('landing.trust.m1')}</li>
                <li>{t('landing.trust.m2')}</li>
                <li>{t('landing.trust.m3')}</li>
              </ul>
            </div>
            <div className={[styles.card, styles.limits].join(' ')}>
              <h3 className={styles.h3}><TriangleAlert size={20} aria-hidden="true" /> {t('landing.limits.title')}</h3>
              <ul className={styles.plain}>
                <li>{t('landing.limits.l1')}</li>
                <li>{t('landing.limits.l2')}</li>
                <li>{t('landing.limits.l3')}</li>
                <li>{t('landing.limits.l4')}</li>
                <li>{t('landing.limits.l5')}</li>
              </ul>
            </div>
          </div>
        </section>

        <section className={styles.band} aria-labelledby="band-title">
          <h2 id="band-title" className={styles.h2}>{t('landing.band.title')}</h2>
          <p>{t('landing.band.body')}</p>
          <Link href={start} className={styles.primaryLight}>{t('landing.getStarted')}<ArrowRight size={20} aria-hidden="true" /></Link>
        </section>
      </main>

      <footer id="about" className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <Wordmark alwaysWord />
            <p className={styles.muted}>{t('landing.footer.about')}</p>
          </div>
          <nav aria-label={t('landing.footer.nav')}>
            <ul className={styles.footerLinks}>
              <li><Link href={`/${locale}/signin`}>{t('landing.signIn')}</Link></li>
              <li><a href="#trust">{t('landing.trust.title')}</a></li>
              <li><a href={`tel:${KISAN_CALL_CENTRE.replace(/-/g, '')}`}><Phone size={16} aria-hidden="true" /> {t('landing.footer.kcc', { phone: KISAN_CALL_CENTRE })}</a></li>
            </ul>
          </nav>
          <div className={styles.footerMeta}>
            <SocialLinks t={t} />
            <p className={styles.muted}>{t('nav.credits')}</p>
            <p className={styles.muted}>{t('landing.footer.credits')}</p>
          </div>
        </div>
      </footer>
    </>
  );
}

function Feature({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <li className={styles.feature}>
      <span className={styles.featureIcon}>{icon}</span>
      <h3 className={styles.h3}>{title}</h3>
      <p className={styles.muted}>{body}</p>
    </li>
  );
}

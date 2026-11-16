'use client';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useId, useMemo, useRef, useState, useTransition, type ReactNode } from 'react';
import type { PublicDistrictDetail, PublicDistrictRisk, SourceRef } from '@fasalalert/shared/api';
import { ClockAlert, CropIcon, RefreshCw, Search, X } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { DistrictChoropleth } from '@/components/Map/DistrictChoropleth';
import { MapLegend } from '@/components/Map/MapLegend';
import { PageHeader } from '@/components/Nav/PageHeader';
import { RiskBadge } from '@/components/Risk/RiskBadge';
import { SourceLine } from '@/components/Risk/SourceLine';
import { TemperatureBand } from '@/components/Risk/TemperatureBand';
import { Banner } from '@/components/UI/Banner';
import { Skeleton } from '@/components/Feedback/Skeleton';
import { clientApi } from '@/lib/client-api';
import { filterDistricts, levelCounts, type DistrictSort, type LevelFilter } from '@/lib/districts';
import { formatDateShort, formatTemp, formatTime, formatWeekday } from '@/lib/format';
import { FORECAST_STALE_MS, isOlderThan, rankDistricts, type DisplayLevel } from '@/lib/risk';
import { cropLabel, fromSourceRef, levelLabel, loc, type ViewCtx } from '@/lib/view';
import styles from './RegionalOutlook.module.css';

export interface OutlookProps {
  mode: 'live' | 'cached' | 'down' | 'empty';
  generatedAt: string | null;
  stale: boolean;
  districts: PublicDistrictRisk[];
  sources: SourceRef[];
  geoAvailable: boolean;
  geoUrl: string;
  bbox: [number, number, number, number] | null;
  skeleton: ReactNode;
  fallback: ReactNode;
  initialDistrict: string | null;
  renderedAt: string;
}

const COLLAPSED = 10;
const LEVELS: DisplayLevel[] = ['critical', 'high', 'medium', 'low', 'none', 'nodata'];

/**
 * Regional outlook (/[locale]/map, docs/UX_QA_AUDIT.md MAP-01..05). Three independent regions: the map
 * (its own fixed box), the selected district's detail, and the searchable district list. The list never
 * changes the map's size: on desktop both sit in their own scroll areas, on phones the list flows below.
 */
export function RegionalOutlook(props: OutlookProps) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const id = useId();
  const [pending, startTransition] = useTransition();
  const [cooldown, setCooldown] = useState(false);
  const [selected, setSelected] = useState<string | null>(props.initialDistrict);
  const [detail, setDetail] = useState<{ code: string; data: PublicDistrictDetail | null; failed: boolean } | null>(() => (props.initialDistrict ? { code: props.initialDistrict, data: null, failed: false } : null));
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState<LevelFilter>('all');
  const [sort, setSort] = useState<DistrictSort>('severity');
  const [expanded, setExpanded] = useState(false);
  const [announce, setAnnounce] = useState('');
  const detailRef = useRef<HTMLElement>(null);
  const now = useMemo(() => new Date(props.renderedAt), [props.renderedAt]);
  const ctx: ViewCtx = { t, locale, now, unit: 'celsius' };

  const rows = useMemo(() => (props.mode === 'down' ? [] : props.districts), [props.mode, props.districts]);
  const byCode = useMemo(() => new Map(rows.map((r) => [r.code, r])), [rows]);
  const top = useMemo(() => rankDistricts(rows), [rows]);
  const rankOf = useMemo(() => new Map(top.map((r, i) => [r.code, i + 1])), [top]);
  const mapRows = useMemo(() => rows.map((r) => ({ code: r.code, level: r.level as DisplayLevel, name: loc(r.name, locale), rank: rankOf.get(r.code) })), [rows, locale, rankOf]);
  const counts = useMemo(() => levelCounts(rows.map((r) => ({ ...r, level: r.level as DisplayLevel }))), [rows]);
  const filtered = useMemo(() => filterDistricts(rows.map((r) => ({ ...r, level: r.level as DisplayLevel })), { query, level, sort, locale }), [rows, query, level, sort, locale]);
  const narrowed = query.trim() !== '' || level !== 'all';
  const visible = expanded || narrowed ? filtered : filtered.slice(0, COLLAPSED);

  const loadDetail = useCallback(async (code: string) => {
    const row = byCode.get(code);
    if (!row) return;
    const r = await clientApi<PublicDistrictDetail>(`public/districts/${row.district_id}`);
    setDetail((d) => (d?.code === code ? { code, data: r.ok ? r.data : null, failed: !r.ok } : d));
  }, [byCode]);

  useEffect(() => {
    const code = props.initialDistrict;
    const row = code ? byCode.get(code) : undefined;
    if (!code || !row) return;
    void clientApi<PublicDistrictDetail>(`public/districts/${row.district_id}`).then((r) => {
      setDetail((d) => (d?.code === code ? { code, data: r.ok ? r.data : null, failed: !r.ok } : d));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for a shared ?district= link
  }, []);

  const select = useCallback((code: string | null, from: 'map' | 'list') => {
    setSelected(code);
    const q = new URLSearchParams(window.location.search);
    if (code) q.set('district', code); else q.delete('district');
    const qs = q.toString();
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${qs ? `?${qs}` : ''}`);
    if (!code) { setDetail(null); return; }
    const row = byCode.get(code);
    if (row) {
      const name = loc(row.name, locale);
      const reason = loc(row.reason, locale);
      setAnnounce(reason ? t('board.announce', { name, level: levelLabel(t, row.level), reason }) : t('board.announceNoReason', { name, level: levelLabel(t, row.level) }));
    }
    setDetail({ code, data: null, failed: false });
    void loadDetail(code);
    // On phones the detail sits below the map: bring it into view when chosen from the list or the map.
    if (from === 'list' || window.matchMedia('(max-width: 1023px)').matches) {
      requestAnimationFrame(() => detailRef.current?.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }));
    }
  }, [byCode, loadDetail, locale, t]);

  const refresh = () => {
    if (cooldown || pending) return;
    setCooldown(true);
    setTimeout(() => setCooldown(false), 10_000); // 60/min per IP limit (PRD §12)
    startTransition(() => router.refresh());
  };

  const isStale = props.mode === 'live' && (props.stale || isOlderThan(props.generatedAt, FORECAST_STALE_MS, now));
  const live = props.mode === 'live' && !isStale;
  const timeIst = props.generatedAt ? formatTime(props.generatedAt, locale) : null;
  const sources = props.sources.map((s) => fromSourceRef(s));
  const selectedRow = selected ? byCode.get(selected) ?? null : null;

  return (
    <main id="main" tabIndex={-1} className={styles.page} data-rendered-at={props.renderedAt}>
      <div className={styles.head}>
        <PageHeader
          title={t('map.title')}
          description={t('map.description')}
          meta={(
            <span className={styles.stamp}>
              {live ? <span className={styles.liveDot} aria-hidden="true" /> : isStale ? <ClockAlert size={16} aria-hidden="true" /> : <span className={styles.deadDot} aria-hidden="true" />}
              <span data-stale={isStale || undefined}>
                {live ? t('board.live') : props.mode === 'live' ? t('map.stale') : t('board.notLive')}
                {timeIst ? ` · ${live ? t('board.updatedAt', { time: timeIst }) : t('board.lastUpdateAt', { time: timeIst })}` : ''}
              </span>
            </span>
          )}
          actions={(
            <>
              <button type="button" className={styles.refresh} onClick={refresh} disabled={cooldown} aria-busy={pending || undefined}>
                <RefreshCw size={20} aria-hidden="true" className={pending ? styles.spin : undefined} />
                <span>{pending ? t('board.updating') : t('board.refresh')}</span>
              </button>
            </>
          )}
        />
        {props.mode === 'cached' || props.mode === 'down' || props.mode === 'empty' ? (
          <Banner variant="danger" icon="cloud-off" action={<button type="button" className={styles.bannerBtn} onClick={refresh} disabled={cooldown}>{t('common.tryAgain')}</button>}>
            {props.mode === 'empty' ? t('board.emptyError') : props.mode === 'cached' && timeIst ? t('board.apiDown', { time: timeIst }) : t('board.apiDownNoCache')}
          </Banner>
        ) : null}
      </div>

      <div className={styles.layout} data-selected={selectedRow ? true : undefined}>
        <section className={styles.mapPane} aria-label={t('board.mapLabel')}>
          <div className={styles.mapBox} data-testid="map-box">
            <DistrictChoropleth
              rows={mapRows}
              selectedCode={selected}
              onSelect={(c) => select(c, 'map')}
              geoUrl={props.geoUrl}
              geoAvailable={props.geoAvailable}
              bbox={props.bbox}
              skeleton={props.skeleton}
              fallback={props.fallback}
              labels={{
                region: t('board.mapLabel'), zoomIn: t('board.zoomIn'), zoomOut: t('board.zoomOut'),
                critical: (name: string) => t('board.criticalMarker', { name }), webgl: t('board.webgl'), error: t('board.mapError'),
                geoMissing: rows.length ? t('board.geoMissing') : t('board.geoMissingNoData'), reset: t('map.resetView'),
              }}
            />
          </div>
          <div className={styles.mapFoot}>
            <MapLegend t={t} className={styles.legend} />
            <p className={styles.attribution}>
              <a href="https://www.geoboundaries.org/" target="_blank" rel="noopener noreferrer">{t('board.footer.boundaries')}</a> (ODbL) ·{' '}
              <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">{t('board.footer.weather')}</a> (CC BY 4.0) · {t('board.footer.imd')}
            </p>
          </div>
        </section>

        {selectedRow ? (
          <section ref={detailRef} className={styles.detailPane} aria-labelledby={`${id}-detail`} tabIndex={-1}>
            <div className={styles.detailHead}>
              <h2 id={`${id}-detail`} className={styles.detailTitle}>{loc(selectedRow.name, locale)}</h2>
              <button type="button" className={styles.close} aria-label={t('map.closeDetail')} onClick={() => select(null, 'list')}><X size={22} aria-hidden="true" /></button>
            </div>
            <DistrictDetail row={selectedRow} detail={detail?.code === selected ? detail : null} ctx={ctx} />
          </section>
        ) : (
          <aside className={styles.detailHint} aria-hidden="true">
            <p>{t('map.pickHint')}</p>
          </aside>
        )}

        <section className={styles.listPane} aria-labelledby={`${id}-list`}>
          <div className={styles.listHead}>
            <h2 id={`${id}-list`} className={styles.h2}>{t('map.listTitle')}</h2>
            {top.length ? (
              <p className={styles.muted}>{t('map.topSummary', { count: top.length })}</p>
            ) : rows.length ? <p className={styles.muted}>{t('board.noneRanked')}</p> : null}
            <div className={styles.controls}>
              <label className={styles.search}>
                <span className="visually-hidden">{t('map.search')}</span>
                <Search size={20} aria-hidden="true" />
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('map.search')} autoComplete="off" />
              </label>
              <div className={styles.selects}>
                <label className={styles.selectWrap}>
                  <span className={styles.selectLabel}>{t('map.filter')}</span>
                  <select value={level} onChange={(e) => setLevel(e.target.value as LevelFilter)}>
                    <option value="all">{t('map.filterAll', { count: rows.length })}</option>
                    <option value="atRisk">{t('map.filterAtRisk', { count: rows.length - counts.none - counts.nodata })}</option>
                    {LEVELS.map((l) => <option key={l} value={l}>{`${t(`risk.level.${l}`)} (${counts[l]})`}</option>)}
                  </select>
                </label>
                <label className={styles.selectWrap}>
                  <span className={styles.selectLabel}>{t('map.sort')}</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value as DistrictSort)}>
                    <option value="severity">{t('map.sortSeverity')}</option>
                    <option value="name">{t('map.sortName')}</option>
                  </select>
                </label>
              </div>
            </div>
            <p className={styles.count} aria-live="polite">{t('map.showing', { shown: visible.length, total: rows.length })}</p>
          </div>
          {rows.length === 0 ? (
            <p className={styles.muted}>{t('board.rankingsLater')}</p>
          ) : filtered.length === 0 ? (
            <div className={styles.empty}>
              <p>{t('map.noMatch')}</p>
              <button type="button" className={styles.textBtn} onClick={() => { setQuery(''); setLevel('all'); }}>{t('map.clearFilters')}</button>
            </div>
          ) : (
            <ul className={styles.list} id={`${id}-items`}>
              {visible.map((r) => (
                <li key={r.code}>
                  <button type="button" className={styles.row} data-level={r.level} aria-pressed={selected === r.code} onClick={() => select(selected === r.code ? null : r.code, 'list')}>
                    <span className={styles.rowTop}>
                      <span className={styles.rowName}>{loc(r.name, locale)}</span>
                      <RiskBadge level={r.level} kind={r.kind ?? undefined} size="sm" t={t} />
                    </span>
                    <span className={styles.rowReason}>{r.level === 'nodata' ? t('risk.level.nodata') : loc(r.reason, locale) || t('map.noReason')}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!narrowed && filtered.length > COLLAPSED ? (
            <button type="button" className={styles.toggle} aria-expanded={expanded} aria-controls={`${id}-items`} onClick={() => setExpanded(!expanded)}>
              {expanded ? t('map.showFewer') : t('map.showAll', { count: filtered.length })}
            </button>
          ) : null}
          {sources.length ? <div className={styles.sources}><SourceLine sources={sources} t={t} locale={locale} now={now} ist compact /></div> : null}
        </section>
      </div>
      <p className="visually-hidden" aria-live="polite">{announce}</p>
    </main>
  );
}

function DistrictDetail({ row, detail, ctx }: { row: PublicDistrictRisk; detail: { data: PublicDistrictDetail | null; failed: boolean } | null; ctx: ViewCtx }) {
  const { t, locale, now } = ctx;
  const d = detail?.data ?? null;
  const level = row.level as DisplayLevel;
  const heat = row.kind === 'heatwave';
  const value = heat ? (d?.tmax_c ?? row.tmax_c) : (d?.tmin_c ?? row.tmin_c);
  const at = heat ? (d?.tmax_at ?? row.tmax_at) : (d?.tmin_at ?? row.tmin_at);
  const threshold = d?.threshold_c ?? row.threshold_c;
  const hasBand = d && typeof d.band_low_c === 'number' && typeof d.band_high_c === 'number';
  return (
    <div className={styles.detailBody} data-level={level}>
      <div className={styles.spine}>
        <RiskBadge level={level} kind={row.kind ?? undefined} t={t} />
        {level === 'nodata' ? <p className={styles.reason}>{t('board.panel.noData')}</p> : row.reason ? <p className={styles.reason}>{loc(row.reason, locale)}</p> : null}
      </div>
      {typeof value === 'number' && at ? (
        <div className={styles.extreme}>
          <h3 className={styles.h3}>{heat ? t('board.panel.hottest') : t('board.panel.coldest')}</h3>
          <p className={styles.numeric}>{formatTemp(value, locale)}</p>
          <p className={styles.muted}>{t('board.panel.at', { time: formatTime(at, locale), date: `${formatWeekday(at, locale)} ${formatDateShort(at, locale, now)}` })}</p>
          {hasBand ? (
            <TemperatureBand kind={heat ? 'heat' : 'frost'} series={[]} event={{ at, valueC: value, lowC: d.band_low_c, highC: d.band_high_c }}
              thresholdC={threshold ?? null} thresholdLabel={t('tband.thresholdDefault')} level={level === 'nodata' ? 'none' : level} sources={[]} compact ctx={ctx} />
          ) : null}
        </div>
      ) : null}
      {detail && !detail.data && !detail.failed ? <Skeleton height={96} radius="md" /> : null}
      {detail?.failed ? <p className={styles.muted} role="status">{t('board.panel.error')}</p> : null}
      {d ? (
        <div className={styles.crops}>
          <h3 className={styles.h3}>{t('board.panel.crops')}</h3>
          {d.affected_crops.length ? (
            <ul className={styles.cropList}>
              {d.affected_crops.map((c, i) => (
                <li key={`${c.crop}-${i}`} className={styles.crop}>
                  <CropIcon crop={c.crop} size={24} />
                  <span className={styles.cropName}>{cropLabel(t, c.crop)}</span>
                  <span className={styles.muted}>{c.stage}</span>
                  <span>{t(c.kind === 'heatwave' ? 'board.panel.damageAbove' : 'board.panel.damageBelow', { value: formatTemp(c.threshold_c, locale) })}</span>
                </li>
              ))}
            </ul>
          ) : <p className={styles.muted}>{t('board.panel.noCrops')}</p>}
          <SourceLine sources={d.sources.map((s) => fromSourceRef(s))} t={t} locale={locale} now={now} ist compact />
          <p className={styles.muted}>{t('board.panel.thresholds')}</p>
        </div>
      ) : null}
    </div>
  );
}

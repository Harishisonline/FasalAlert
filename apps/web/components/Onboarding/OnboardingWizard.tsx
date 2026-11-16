'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { Crop, Field, FieldCreateBody, LocationItem, NearestVillage } from '@fasalalert/shared/api';
import { ArrowLeft, Calendar, CircleCheck, CropIcon, LocateFixed, MapPin, Ruler, Tag, X } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import type { LatLon } from '@/components/Map/FieldPicker';
import { LanguageSwitcher } from '@/components/Nav/LanguageSwitcher';
import { Banner } from '@/components/UI/Banner';
import { Button } from '@/components/UI/Button';
import { Combobox, type ComboOption } from '@/components/UI/Combobox';
import { Dialog } from '@/components/UI/Dialog';
import { SelectField, TextField } from '@/components/UI/Field';
import { clientApi, goToSignIn } from '@/lib/client-api';
import { areaToSqm, formatCoordinate, formatDateShort, formatWithUnit, istDateKey } from '@/lib/format';
import { cropLabel, loc } from '@/lib/view';
import { CropPicker } from './CropPicker';
import { MapPinDialog } from './MapPinDialog';
import styles from './OnboardingWizard.module.css';

type Step = 1 | 2 | 3 | 4;
type Load<T> = { state: 'idle' | 'loading' | 'ok' | 'error'; items: T[] };
type Source = 'village' | 'gps' | 'pin';
type CropTable = Record<Crop, { varieties: { key: string; name: { en: string; mr: string; hi: string } }[]; typicalSowing: string | null; seasonLabel: { en: string; mr: string; hi: string } | null; seasonHint: { en: string; mr: string; hi: string } | null }>;

const STEPS: Step[] = [1, 2, 3, 4];
/** A point is matched to a village only when the village centre is this close (km). */
const NEAR_KM = 10;
const MH = { s: 15.6, n: 22.1, w: 72.6, e: 80.9 };

/**
 * Onboarding and Add field in four steps: location, crop, farm details, review (docs/UX_QA_AUDIT.md ONB-01,
 * ONB-02). Location comes from searchable district, taluka and village lists or the phone's location; the map
 * opens only when the farmer asks to pin an exact spot. All answers stay in this component while moving between
 * steps, and a save can only be sent once.
 */
export function OnboardingWizard({ mode, districts, districtsFailed, fieldCount, areaUnit, crops }: {
  mode: 'first' | 'add'; districts: LocationItem[]; districtsFailed: boolean; fieldCount: number; areaUnit: 'hectare' | 'acre'; crops: CropTable;
}) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const id = useId();
  const [step, setStep] = useState<Step>(1);
  const [districtList, setDistrictList] = useState<Load<LocationItem>>({ state: districtsFailed ? 'error' : 'ok', items: districts });
  const [talukas, setTalukas] = useState<Load<LocationItem>>({ state: 'idle', items: [] });
  const [villages, setVillages] = useState<Load<LocationItem>>({ state: 'idle', items: [] });
  const [districtId, setDistrictId] = useState('');
  const [talukaId, setTalukaId] = useState('');
  const [villageId, setVillageId] = useState('');
  const [point, setPoint] = useState<{ p: LatLon; source: Exclude<Source, 'village'> } | null>(null);
  const [gps, setGps] = useState<{ state: 'idle' | 'locating' | 'done' | 'error'; message: string | null }>({ state: 'idle', message: null });
  const [mapOpen, setMapOpen] = useState(false);
  const [crop, setCrop] = useState<Crop | null>(null);
  const [variety, setVariety] = useState('');
  const [sowing, setSowing] = useState('');
  const [typical, setTypical] = useState(false);
  const [area, setArea] = useState('');
  const [unit, setUnit] = useState<'hectare' | 'acre'>(areaUnit);
  const [name, setName] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [leave, setLeave] = useState(false);
  const [announce, setAnnounce] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const today = istDateKey(new Date());
  const dirty = Boolean(districtId || point || crop || name || area);
  const exitHref = mode === 'add' ? `/${locale}/fields` : `/${locale}/home`;

  useEffect(() => {
    const onBefore = (e: BeforeUnloadEvent) => { if (dirty && !saving && !saved) e.preventDefault(); };
    window.addEventListener('beforeunload', onBefore);
    return () => window.removeEventListener('beforeunload', onBefore);
  }, [dirty, saving, saved]);

  const titles: Record<Step, string> = { 1: t('onb.s1.title'), 2: t('onb.s2.title'), 3: t('onb.s3.title'), 4: t('onb.s4.title') };
  const short: Record<Step, string> = { 1: t('onb.short.location'), 2: t('onb.short.crop'), 3: t('onb.short.details'), 4: t('onb.short.review') };
  const goStep = (s: Step) => {
    setStep(s);
    setAnnounce(t('onb.stepAnnounce', { n: s, title: titles[s] }));
    setTimeout(() => { heading.current?.focus(); window.scrollTo({ top: 0 }); }, 30);
  };

  /* ---------- location lists ---------- */
  const loadDistricts = async () => {
    setDistrictList({ state: 'loading', items: [] });
    const r = await clientApi<LocationItem[]>('locations/districts');
    setDistrictList(r.ok ? { state: 'ok', items: r.data } : { state: 'error', items: [] });
  };
  const loadTalukas = async (dId: string) => {
    setTalukas({ state: 'loading', items: [] });
    const r = await clientApi<LocationItem[]>('locations/talukas', { query: { district_id: dId } });
    setTalukas(r.ok ? { state: 'ok', items: r.data } : { state: 'error', items: [] });
    return r.ok;
  };
  const loadVillages = async (tId: string) => {
    setVillages({ state: 'loading', items: [] });
    const r = await clientApi<LocationItem[]>('locations/villages', { query: { taluka_id: tId } });
    setVillages(r.ok ? { state: 'ok', items: r.data } : { state: 'error', items: [] });
    return r.ok;
  };
  const chooseDistrict = (v: string) => {
    setDistrictId(v); setTalukaId(''); setVillageId(''); setVillages({ state: 'idle', items: [] }); setPoint(null); setErrors({});
    if (v) void loadTalukas(v);
  };
  const chooseTaluka = (v: string) => {
    setTalukaId(v); setVillageId(''); setPoint(null); setErrors({});
    if (v) void loadVillages(v);
  };
  const chooseVillage = (v: string) => { setVillageId(v); setPoint(null); setErrors({}); };

  /** Fill district, taluka and village from a point (phone location or map pin) when a village is close by. */
  const placeFromPoint = async (p: LatLon, source: 'gps' | 'pin') => {
    setPoint({ p, source });
    setErrors({});
    const r = await clientApi<NearestVillage>('locations/nearest', { query: { lat: p.lat.toFixed(5), lon: p.lon.toFixed(5) } });
    if (!r.ok || r.data.distance_km > NEAR_KM) return null;
    const near = r.data;
    setDistrictId(String(near.district.id));
    const [okT, okV] = await Promise.all([loadTalukas(String(near.district.id)), loadVillages(String(near.taluka.id))]);
    if (okT) setTalukaId(String(near.taluka.id));
    if (okV) setVillageId(String(near.village.id));
    return near;
  };

  const useMyLocation = () => {
    if (!('geolocation' in navigator)) { setGps({ state: 'error', message: t('onb.gps.unsupported') }); return; }
    setGps({ state: 'locating', message: null });
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const p = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        if (p.lat < MH.s || p.lat > MH.n || p.lon < MH.w || p.lon > MH.e) { setGps({ state: 'error', message: t('onb.gps.outside') }); return; }
        const near = await placeFromPoint(p, 'gps');
        setGps(near
          ? { state: 'done', message: t('onb.gps.found', { place: [loc(near.village.name, locale), loc(near.taluka.name, locale), loc(near.district.name, locale)].join(', ') }) }
          : { state: 'done', message: t('onb.gps.noVillage') });
      },
      (err) => setGps({ state: 'error', message: err.code === err.PERMISSION_DENIED ? t('onb.gps.denied') : t('onb.gps.failed') }),
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 },
    );
  };

  const district = districtList.items.find((x) => String(x.id) === districtId) ?? null;
  const taluka = talukas.items.find((x) => String(x.id) === talukaId) ?? null;
  const village = villages.items.find((v) => String(v.id) === villageId) ?? null;
  const villagePoint: LatLon | null = village && typeof village.lat === 'number' && typeof village.lon === 'number' ? { lat: village.lat, lon: village.lon } : null;
  const location: LatLon | null = point?.p ?? villagePoint;
  const source: Source | null = point ? point.source : villagePoint ? 'village' : null;
  const placeParts = [village, taluka, district].filter(Boolean).map((x) => loc(x!.name, locale));
  const coords = location ? t('onb.placeByCoords', { lat: formatCoordinate(location.lat, locale), lon: formatCoordinate(location.lon, locale) }) : '';
  const placeLabel = placeParts.length ? placeParts.join(', ') : coords;

  const opts = (items: LocationItem[]): ComboOption[] => items.map((v) => ({ value: String(v.id), label: loc(v.name, locale), search: `${v.name.en} ${v.name.mr} ${v.name.hi}`.normalize('NFC').toLocaleLowerCase() }));
  const districtOpts = useMemo(() => opts(districtList.items), [districtList.items, locale]); // eslint-disable-line react-hooks/exhaustive-deps
  const talukaOpts = useMemo(() => opts(talukas.items), [talukas.items, locale]); // eslint-disable-line react-hooks/exhaustive-deps
  const villageOpts = useMemo(() => opts(villages.items), [villages.items, locale]); // eslint-disable-line react-hooks/exhaustive-deps
  const villageEmpty = villages.state === 'ok' && villages.items.length === 0;

  /* ---------- crop ---------- */
  const defaultName = crop ? t('onb.defaultName', { crop: cropLabel(t, crop), n: fieldCount + 1 }) : '';
  const typicalDate = (() => {
    const md = crop ? crops[crop]?.typicalSowing : null;
    if (!md) return null;
    const year = Number(today.slice(0, 4));
    const candidate = `${year}-${md}`;
    return candidate <= today ? candidate : `${year - 1}-${md}`;
  })();
  const varietyName = crop ? crops[crop].varieties.find((v) => v.key === variety) : undefined;

  const next1 = () => {
    if (!location) { setErrors({ location: t('onb.needPlace') }); return; }
    setErrors({});
    goStep(2);
  };
  const next2 = () => {
    const e: Record<string, string> = {};
    if (!crop) e.crop = t('onb.chooseCrop');
    if (sowing && sowing > today) e.sowing_date = t('field.futureDate');
    setErrors(e);
    if (Object.keys(e).length === 0) goStep(3);
  };
  const next3 = () => {
    const e: Record<string, string> = {};
    if (area && !(Number(area) > 0)) e.area_sqm = t('onb.areaInvalid');
    setErrors(e);
    if (Object.keys(e).length === 0) goStep(4);
  };

  const save = async () => {
    if (!crop || !location || saving || saved) return;
    setSaving(true);
    setErrors({});
    const body: FieldCreateBody = {
      crop, lat: Number(location.lat.toFixed(6)), lon: Number(location.lon.toFixed(6)), name: (name.trim() || defaultName) || undefined,
      ...(variety ? { variety } : {}), ...(sowing ? { sowing_date: sowing } : {}),
      ...(districtId ? { district_id: Number(districtId) } : {}), ...(talukaId ? { taluka_id: Number(talukaId) } : {}),
      ...(villageId ? { village_id: Number(villageId) } : {}),
      ...(area && Number(area) > 0 ? { area_sqm: Math.round(areaToSqm(Number(area), unit)) } : {}),
    };
    const r = await clientApi<Field>('fields', { method: 'POST', body });
    if (!r.ok) {
      setSaving(false);
      if (r.status === 401) { goToSignIn(locale); return; }
      const f = String(r.error?.details?.field ?? '');
      const message = r.kind === 'network' ? t('common.noConnection') : r.error?.message || t('common.serverError');
      setErrors({ save: f ? t('onb.saveFailedField', { field: t(`onb.fieldName.${f}`) }) : t('onb.saveFailed', { message }) });
      return;
    }
    setSaved(true);
    setAnnounce(t('onb.saved'));
    // One full load: the page and the shell (side nav field list) both show the new field, rendered once.
    window.location.assign(mode === 'add' ? `/${locale}/fields?added=${r.data.id}` : `/${locale}/home`);
  };

  const onBack = () => {
    if (step > 1) { goStep((step - 1) as Step); return; }
    if (dirty) setLeave(true);
    else router.push(exitHref);
  };

  const sourceLabel = source === 'gps' ? t('onb.summary.gps') : source === 'pin' ? t('onb.summary.pin') : t('onb.summary.village');
  const summary = (
    <div className={styles.summary} data-empty={!location || undefined} aria-live="polite">
      <MapPin size={22} aria-hidden="true" />
      {location ? (
        <div className={styles.summaryText}>
          <p className={styles.summaryTitle}>{placeLabel}</p>
          <p className={styles.muted}>{sourceLabel}{placeParts.length ? ` · ${coords}` : ''}</p>
        </div>
      ) : <p className={styles.muted}>{t('onb.summary.none')}</p>}
      {point ? <button type="button" className={styles.iconBtn} aria-label={t('onb.clearPin')} onClick={() => { setPoint(null); setGps({ state: 'idle', message: null }); }}><X size={20} aria-hidden="true" /></button> : null}
    </div>
  );

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <button type="button" className={styles.back} onClick={onBack} aria-label={step > 1 ? t('onb.backTo', { title: short[(step - 1) as Step] }) : t('onb.exit')}>
          <ArrowLeft size={24} aria-hidden="true" />
        </button>
        <div className={styles.headText}>
          <p className={styles.headTitle}>{mode === 'add' ? t('onb.addTitle') : t('onb.firstTitle')}</p>
          <p className={styles.stepText}>{t('onb.step', { n: step })}</p>
        </div>
        <LanguageSwitcher signedIn />
      </header>
      <ol className={styles.progress} aria-label={t('onb.progress')}>
        {STEPS.map((s) => (
          <li key={s} data-state={s < step ? 'done' : s === step ? 'current' : 'todo'} aria-current={s === step ? 'step' : undefined}>
            <span className={styles.bar} aria-hidden="true" />
            <span className={styles.stepName}>{s < step ? <CircleCheck size={14} aria-hidden="true" /> : null}{short[s]}</span>
          </li>
        ))}
      </ol>
      <p className="visually-hidden" aria-live="polite">{announce}</p>
      <main id="main" className={styles.main}>
        <div className={styles.col}>
          <h1 ref={heading} tabIndex={-1} className={styles.h1}>{titles[step]}</h1>

          {step === 1 ? (
            <div className={styles.form}>
              <p className={styles.lead}>{t('onb.s1.sub')}</p>
              <div className={styles.gps}>
                <Button variant="secondary" icon={<LocateFixed size={20} aria-hidden="true" />} loading={gps.state === 'locating'} loadingLabel={t('onb.map.locating')} onClick={useMyLocation}>
                  {t('onb.gps.button')}
                </Button>
                {gps.message ? <p className={styles.info} data-tone={gps.state === 'error' ? 'error' : undefined} role="status">{gps.message}</p> : null}
              </div>
              <p className={styles.or}><span>{t('onb.or')}</span></p>
              <div className={styles.withRetry}>
                <Combobox id={`${id}-district`} label={t('onb.district')} value={districtId} options={districtOpts} onChange={chooseDistrict}
                  disabled={districtList.state !== 'ok'} placeholder={districtList.state === 'loading' ? t('onb.loadingDistricts') : districtList.state === 'error' ? t('onb.couldNotLoad') : t('onb.typeDistrict')}
                  emptyLabel={t('onb.noMatchesPlace')} moreLabel={(n) => t('onb.moreOptions', { count: n })} toggleLabel={t('onb.showOptions')} />
                {districtList.state === 'error' ? <Button variant="secondary" onClick={() => void loadDistricts()}>{t('common.tryAgain')}</Button> : null}
              </div>
              <div className={styles.withRetry}>
                <Combobox id={`${id}-taluka`} label={t('onb.taluka')} value={talukaId} options={talukaOpts} onChange={chooseTaluka}
                  disabled={!districtId || talukas.state !== 'ok'} placeholder={talukas.state === 'loading' ? t('onb.loadingTalukas') : talukas.state === 'error' ? t('onb.couldNotLoad') : districtId ? t('onb.typeTaluka') : t('onb.districtFirst')}
                  emptyLabel={t('onb.noMatchesPlace')} moreLabel={(n) => t('onb.moreOptions', { count: n })} toggleLabel={t('onb.showOptions')} />
                {talukas.state === 'error' ? <Button variant="secondary" onClick={() => void loadTalukas(districtId)}>{t('common.tryAgain')}</Button> : null}
              </div>
              <div className={styles.withRetry}>
                <Combobox id={`${id}-village`} label={t('onb.village')} value={villageId} options={villageOpts} onChange={chooseVillage}
                  disabled={!talukaId || villages.state !== 'ok' || villageEmpty} placeholder={villages.state === 'loading' ? t('onb.loadingVillages') : villages.state === 'error' ? t('onb.couldNotLoad') : talukaId ? t('onb.typeVillage') : t('onb.talukaFirst')}
                  emptyLabel={t('onb.noMatches')} moreLabel={(n) => t('onb.moreOptions', { count: n })} toggleLabel={t('onb.showOptions')}
                  help={villageOpts.length ? t('onb.villageCount', { count: villageOpts.length }) : undefined} />
                {villages.state === 'error' ? <Button variant="secondary" onClick={() => void loadVillages(talukaId)}>{t('common.tryAgain')}</Button> : null}
              </div>
              {villageEmpty ? <p className={styles.info}>{t('onb.noVillages')}</p> : null}
              {summary}
              <button type="button" className={styles.pinBtn} onClick={() => setMapOpen(true)}>
                <MapPin size={20} aria-hidden="true" /> {point?.source === 'pin' ? t('onb.pinChange') : t('onb.pinMap')}
              </button>
              {errors.location ? <p className={styles.error} role="alert">{errors.location}</p> : null}
              <div className={styles.actions}>
                <Button size="lg" fullWidth onClick={next1}>{t('onb.continue', { title: short[2] })}</Button>
              </div>
            </div>
          ) : null}

          {step === 2 ? (
            <div className={styles.form}>
              <p className={styles.lead}>{t('onb.s2.sub')}</p>
              <CropPicker value={crop} onChange={(c) => { setCrop(c); setVariety(''); if (typical) setSowing(''); setTypical(false); setErrors((x) => ({ ...x, crop: '' })); }} label={titles[2]} />
              {errors.crop ? <p className={styles.error} role="alert">{errors.crop}</p> : null}
              {crop ? (
                <>
                  {crops[crop].varieties.length ? (
                    <SelectField id={`${id}-variety`} label={t('onb.variety')} value={variety} onChange={(e) => setVariety(e.target.value)} help={t('onb.varietyHelp')}>
                      <option value="">{t('field.notSure')}</option>
                      {crops[crop].varieties.map((v) => <option key={v.key} value={v.key}>{loc(v.name, locale)}</option>)}
                    </SelectField>
                  ) : null}
                  <TextField id={`${id}-sowing`} type="date" max={today} label={crops[crop].seasonLabel ? loc(crops[crop].seasonLabel, locale) : t('onb.sowing')} value={sowing}
                    onChange={(e) => { setSowing(e.target.value); setTypical(false); setErrors((x) => ({ ...x, sowing_date: e.target.value > today ? t('field.futureDate') : '' })); }}
                    error={errors.sowing_date || undefined} help={typical ? t('onb.typicalUsed') : crops[crop].seasonHint ? loc(crops[crop].seasonHint, locale) : undefined} />
                  {typicalDate ? (
                    <label className={styles.check}>
                      <input type="checkbox" checked={typical} onChange={(e) => { setTypical(e.target.checked); setSowing(e.target.checked ? typicalDate : ''); }} />
                      <span>{t('onb.typical')}</span>
                    </label>
                  ) : null}
                  <p className={styles.note}>{t('onb.sowingWhy')}</p>
                </>
              ) : null}
              <div className={styles.actions}>
                <Button variant="secondary" size="lg" onClick={() => goStep(1)}>{t('nav.back')}</Button>
                <Button size="lg" onClick={next2}>{t('onb.continue', { title: short[3] })}</Button>
              </div>
            </div>
          ) : null}

          {step === 3 ? (
            <div className={styles.form}>
              <p className={styles.lead}>{t('onb.s3.sub')}</p>
              <TextField id={`${id}-name`} label={t('onb.nameOptional')} value={name} placeholder={defaultName} maxLength={60} onChange={(e) => setName(e.target.value)}
                help={t('onb.nameHelp', { name: defaultName })} />
              <div className={styles.areaRow}>
                <TextField id={`${id}-area`} label={t('onb.area')} inputMode="decimal" value={area} onChange={(e) => setArea(e.target.value.replace(/[^\d.]/g, ''))} error={errors.area_sqm} />
                <SelectField id={`${id}-unit`} label={t('onb.areaUnit')} value={unit} onChange={(e) => setUnit(e.target.value as 'hectare' | 'acre')}>
                  <option value="hectare">{t('units.ha')}</option>
                  <option value="acre">{t('units.acre')}</option>
                </SelectField>
              </div>
              <div className={styles.actions}>
                <Button variant="secondary" size="lg" onClick={() => goStep(2)}>{t('nav.back')}</Button>
                <Button size="lg" onClick={next3}>{name || area ? t('onb.continue', { title: short[4] }) : t('onb.skipToReview')}</Button>
              </div>
            </div>
          ) : null}

          {step === 4 && crop && location ? (
            <div className={styles.form}>
              <p className={styles.lead}>{t('onb.s4.sub')}</p>
              <dl className={styles.review}>
                <div>
                  <dt><MapPin size={20} aria-hidden="true" /> {t('onb.short.location')}</dt>
                  <dd>{placeLabel}<span className={styles.muted}>{sourceLabel}</span></dd>
                  <dd className={styles.edit}><Button variant="text" onClick={() => goStep(1)} aria-label={t('onb.editNamed', { title: short[1] })}>{t('onb.editStep')}</Button></dd>
                </div>
                <div>
                  <dt><CropIcon crop={crop} size={20} /> {t('onb.short.crop')}</dt>
                  <dd>{[cropLabel(t, crop), varietyName ? loc(varietyName.name, locale) : null].filter(Boolean).join(' · ')}</dd>
                  <dd className={styles.edit}><Button variant="text" onClick={() => goStep(2)} aria-label={t('onb.editNamed', { title: short[2] })}>{t('onb.editStep')}</Button></dd>
                </div>
                <div>
                  <dt><Calendar size={20} aria-hidden="true" /> {t('onb.sowing')}</dt>
                  <dd>{sowing ? t('onb.sown', { date: formatDateShort(sowing, locale) }) : t('onb.noSowing')}{!sowing ? <span className={styles.muted}>{t('onb.noSowingEffect')}</span> : null}</dd>
                  <dd className={styles.edit}><Button variant="text" onClick={() => goStep(2)} aria-label={t('onb.editNamed', { title: t('onb.sowing') })}>{t('onb.editStep')}</Button></dd>
                </div>
                <div>
                  <dt><Tag size={20} aria-hidden="true" /> {t('onb.name')}</dt>
                  <dd>{name.trim() || defaultName}</dd>
                  <dd className={styles.edit}><Button variant="text" onClick={() => goStep(3)} aria-label={t('onb.editNamed', { title: t('onb.name') })}>{t('onb.editStep')}</Button></dd>
                </div>
                <div>
                  <dt><Ruler size={20} aria-hidden="true" /> {t('onb.areaLabel')}</dt>
                  <dd>{area ? formatWithUnit(Number(area), unit === 'acre' ? t('units.acre') : t('units.ha'), locale, 1) : t('onb.noArea')}</dd>
                  <dd className={styles.edit}><Button variant="text" onClick={() => goStep(3)} aria-label={t('onb.editNamed', { title: t('onb.areaLabel') })}>{t('onb.editStep')}</Button></dd>
                </div>
              </dl>
              {errors.save ? <Banner variant="danger">{errors.save}</Banner> : null}
              {saved ? <Banner variant="success">{t('onb.saved')}</Banner> : null}
              <div className={styles.actions}>
                <Button variant="secondary" size="lg" onClick={() => goStep(3)} disabled={saving || saved}>{t('nav.back')}</Button>
                <Button size="lg" loading={saving || saved} loadingLabel={saved ? t('onb.opening') : t('common.saving')} onClick={() => void save()}>{t('onb.save')}</Button>
              </div>
            </div>
          ) : null}
        </div>
      </main>
      {mapOpen ? (
        <MapPinDialog open initial={location} onCancel={() => setMapOpen(false)}
          onConfirm={(p) => { setMapOpen(false); setGps({ state: 'idle', message: null }); void placeFromPoint(p, 'pin'); }} />
      ) : null}
      <Dialog open={leave} title={mode === 'add' ? t('onb.leaveTitle') : t('onb.leaveFirstTitle')} onCancel={() => setLeave(false)}
        actions={<><Button variant="secondary" onClick={() => { setLeave(false); router.push(exitHref); }}>{t('onb.leave')}</Button><Button onClick={() => setLeave(false)}>{t('onb.stay')}</Button></>}>
        <p>{mode === 'add' ? t('onb.leaveBody') : t('onb.leaveFirstBody')}</p>
      </Dialog>
    </div>
  );
}

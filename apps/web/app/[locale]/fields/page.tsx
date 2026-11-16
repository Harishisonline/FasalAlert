import type { Metadata } from 'next';
import { Suspense } from 'react';
import type { Abstention, Decision, Field } from '@fasalalert/shared/api';
import { EmptyState } from '@/components/Feedback/EmptyState';
import { RefreshWhilePending } from '@/components/Feedback/RefreshWhilePending';
import { RetryButton } from '@/components/Feedback/RetryButton';
import { RouteError } from '@/components/Feedback/RouteError';
import { FieldsClient } from '@/components/Fields/FieldsClient';
import { Plus, Wheat } from '@/components/Icon';
import { PageMain } from '@/components/Layout/Page';
import { PageHeader } from '@/components/Nav/PageHeader';
import { ButtonLink } from '@/components/UI/Button';
import { getDecisionsToday, getFields, redirectIfUnauthenticated } from '@/lib/api';
import { loadCropTable, varietyLabel } from '@/lib/crops';
import type { FieldCardData } from '@/lib/fields';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { cardModel, isAbstention } from '@/lib/risk';
import { cropLabel, loc } from '@/lib/view';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('fields.title') };
}

/** My Fields (docs/UX_QA_AUDIT.md FIELDS-01): every field the signed-in user owns, with no limit. */
export default async function FieldsPage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const locale = (await params).locale as Locale;
  const sp = await searchParams;
  const t = createTranslator(locale);
  const now = new Date();
  const [fields, crops] = await Promise.all([getFields(), loadCropTable()]);
  await redirectIfUnauthenticated(fields, locale);
  const add = <ButtonLink href={`/${locale}/fields/new`} icon={<Plus size={20} aria-hidden="true" />}>{t('nav.addField')}</ButtonLink>;
  const header = <PageHeader title={t('fields.title')} description={t('fields.description')} actions={fields.ok && fields.data.length ? add : undefined} />;

  if (!fields.ok) {
    return (
      <PageMain renderedAt={now.toISOString()}>
        {header}
        <RouteError variant="section" message={t('home.fieldsError')} code={fields.error?.trace_id} codeLabel={fields.error?.trace_id ? t('state.errorCode', { code: fields.error.trace_id }) : undefined} action={<RetryButton />} />
      </PageMain>
    );
  }
  if (fields.data.length === 0) {
    return (
      <PageMain renderedAt={now.toISOString()}>
        {header}
        <EmptyState variant="page" icon={<Wheat size={48} aria-hidden="true" />} title={t('fields.emptyTitle')} body={t('home.emptyFirst')}
          action={<ButtonLink href={`/${locale}/fields/new`} size="lg" icon={<Plus size={20} aria-hidden="true" />}>{t('home.addFirst')}</ButtonLink>} />
      </PageMain>
    );
  }
  const added = typeof sp.added === 'string' && /^\d+$/.test(sp.added) ? Number(sp.added) : null;
  const build = (decisions: Map<number, Decision | Abstention> | null): FieldCardData[] => fields.data.map((f: Field) => {
    const d = decisions?.get(f.id) ?? null;
    const model = cardModel(d, now);
    const status: FieldCardData['status'] = decisions === null ? 'loading' : !d ? 'pending' : isAbstention(d) ? (d.abstain_reason === 'data_stale' ? 'stale' : 'abstain') : 'decision';
    return {
      id: f.id, name: f.name, crop: f.crop, cropText: cropLabel(t, f.crop), variety: varietyLabel(crops, f.crop, f.variety, locale),
      location: f.location_label ? loc(f.location_label, locale) : null,
      stage: f.stage?.stage_label ? loc(f.stage.stage_label, locale) : null,
      level: status === 'decision' ? model.level : 'nodata', status,
      headline: d ? d.headline : null, decisionDate: d ? d.decision_date : null,
    };
  });
  // Today's status streams in: a new field's first decision can take a while to work out (docs/UX_QA_AUDIT.md HOME-02).
  return (
    <PageMain renderedAt={now.toISOString()}>
      {header}
      <Suspense fallback={<FieldsClient items={build(null)} addedId={added} renderedAt={now.toISOString()} />}>
        <FieldsWithStatus build={build} addedId={added} renderedAt={now.toISOString()} errorText={t('fields.decisionsError')} />
      </Suspense>
    </PageMain>
  );
}

async function FieldsWithStatus({ build, addedId, renderedAt, errorText }: { build: (d: Map<number, Decision | Abstention> | null) => FieldCardData[]; addedId: number | null; renderedAt: string; errorText: string }) {
  const decisions = await getDecisionsToday();
  const map = new Map<number, Decision | Abstention>((decisions.ok ? decisions.data : []).map((d) => [d.field_id, d]));
  return (
    <>
      {!decisions.ok ? <RouteError message={errorText} action={<RetryButton />} /> : null}
      <FieldsClient items={build(map)} addedId={addedId} renderedAt={renderedAt} />
      {decisions.ok && build(map).some((f) => f.status === 'pending') ? <RefreshWhilePending /> : null}
    </>
  );
}

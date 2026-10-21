import { cache } from 'react';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { AnalysisDetail } from '@/components/analyses/analysis-detail';
import { AnalysisLoadError } from '@/components/analyses/analysis-load-error';
import { parseAnalysisId } from '@/components/analyses/format';
import { fetchAnalysis } from '@/lib/api/analyses';
import { fetchCalendar } from '@/lib/api/calendar';

/** The stored analysis can be re-run elsewhere, so the page is always read live. */
export const dynamic = 'force-dynamic';

type Props = { params: Promise<{ id: string }> };

const STATIC_TITLE = 'Analysis';

/** One backend read per request, shared by the page and its metadata. */
const load = cache(fetchAnalysis);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = parseAnalysisId((await params).id);
  if (id === null) return { title: STATIC_TITLE };
  const result = await load(id);
  return {
    title: result.success ? `${result.data.symbol} ${result.data.tf} analysis` : STATIC_TITLE,
  };
}

export default async function AnalysisPage({ params }: Props) {
  const id = parseAnalysisId((await params).id);
  if (id === null) notFound();

  const result = await load(id);
  if (!result.success) {
    if (result.status === 404) notFound();
    return <AnalysisLoadError message={result.error} id={id} />;
  }
  const calendar = await fetchCalendar(result.data.symbol);
  return <AnalysisDetail analysis={result.data} calendar={calendar} />;
}

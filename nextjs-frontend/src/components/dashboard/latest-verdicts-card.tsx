import { DashboardCard } from './dashboard-card';
import { ErrorBanner } from './error-banner';
import { VerdictList, type VerdictItem } from './verdict-list';
import type { AnalysisOut, AnalysisPage } from '@/lib/api/analyses';
import { analysesErrorMessage } from '@/lib/api/analyses-messages';
import type { ApiResult } from '@/lib/api/server';

export const LATEST_VERDICTS_LIMIT = 10;

export function toVerdictItem(analysis: AnalysisOut): VerdictItem {
  const verdict = analysis.status === 'ok' ? analysis.verdict : null;
  return {
    id: analysis.id,
    symbol: analysis.symbol,
    tf: analysis.tf,
    createdAt: analysis.created_at,
    action: verdict?.action ?? null,
    confidence: verdict?.confidence ?? null,
    failed: analysis.status === 'failed',
  };
}

/** The latest stored verdicts, or the reason they could not be loaded. */
export function LatestVerdictsCard({ result }: { result: ApiResult<AnalysisPage> }) {
  return (
    <DashboardCard
      title="Latest verdicts"
      description={`The ${LATEST_VERDICTS_LIMIT} most recent analyses.`}
    >
      {result.success ? (
        <VerdictList items={result.data.items.slice(0, LATEST_VERDICTS_LIMIT).map(toVerdictItem)} />
      ) : (
        <ErrorBanner message={analysesErrorMessage(result)} />
      )}
    </DashboardCard>
  );
}

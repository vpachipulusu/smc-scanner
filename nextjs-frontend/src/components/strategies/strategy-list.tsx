import Link from 'next/link';
import { Lock } from 'lucide-react';

import { VerdictBadge } from '@/components/backtests/verdict-badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import type { StrategyOut } from '@/lib/api/strategies-write';
import { backtestHref } from '@/lib/backtests/routes';
import {
  VERDICT_LABELS,
  verdictFor,
  type StrategyVerdicts,
  type VerdictKey,
} from '@/lib/backtests/verdict';
import type { ConditionInfo } from '@/lib/strategies/catalogue';
import { describeCondition, describeScoring, describeTuning } from '@/lib/strategies/format';
import { StrategyActions } from './strategy-actions';

/**
 * The strategies on the list page: built-ins (read-only, marked with a badge) and then the custom
 * ones, each with its tuning, its required and scored conditions and its actions. A strategy's
 * latest backtest verdict links to its backtest page; without a known verdict there is no badge.
 */

type ConditionsProps = {
  title: string;
  refs: StrategyOut['require'];
  catalogue: readonly ConditionInfo[];
};

function Conditions({ title, refs, catalogue }: ConditionsProps) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      {refs.length === 0 ? (
        <p className="text-sm text-muted-foreground">None</p>
      ) : (
        <ul className="list-disc pl-5 text-sm">
          {refs.map((ref) => (
            <li key={ref.key}>{describeCondition(ref, catalogue)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

type StrategyCardProps = {
  strategy: StrategyOut;
  catalogue: readonly ConditionInfo[];
  verdict?: VerdictKey;
};

export function StrategyCard({ strategy, catalogue, verdict }: StrategyCardProps) {
  const headingId = `strategy-${strategy.slug}-title`;
  return (
    <Card aria-labelledby={headingId} role="article" className="flex flex-col">
      <CardHeader className="gap-1 pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle id={headingId} className="text-lg">
            {strategy.name}
          </CardTitle>
          {strategy.builtin && (
            <StatusPill variant="info" icon={Lock}>
              Built-in, read-only
            </StatusPill>
          )}
          {verdict && (
            <Link
              href={backtestHref(strategy.slug)}
              aria-label={`Backtest results of ${strategy.name}: ${VERDICT_LABELS[verdict]}`}
              className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <VerdictBadge verdict={verdict} />
            </Link>
          )}
        </div>
        <p className="font-mono text-xs text-muted-foreground">{strategy.slug}</p>
        {strategy.description && <CardDescription>{strategy.description}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <p className="text-sm">{describeTuning(strategy)}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Conditions title="Required" refs={strategy.require} catalogue={catalogue} />
          <Conditions
            title={describeScoring(strategy)}
            refs={strategy.score}
            catalogue={catalogue}
          />
        </div>
        <div className="mt-auto pt-2">
          <StrategyActions slug={strategy.slug} name={strategy.name} builtin={strategy.builtin} />
        </div>
      </CardContent>
    </Card>
  );
}

type StrategyListProps = {
  strategies: readonly StrategyOut[];
  catalogue: readonly ConditionInfo[];
  verdicts?: StrategyVerdicts;
};

export function StrategyList({ strategies, catalogue, verdicts = {} }: StrategyListProps) {
  const builtins = strategies.filter((strategy) => strategy.builtin);
  const custom = strategies.filter((strategy) => !strategy.builtin);
  return (
    <div className="space-y-8">
      <section aria-labelledby="custom-strategies-heading" className="space-y-3">
        <h2 id="custom-strategies-heading" className="text-xl font-semibold">
          Your strategies
        </h2>
        {custom.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="no-custom-strategies">
            No custom strategies yet. Create one, or duplicate a built-in below to start from it.
          </p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {custom.map((strategy) => (
              <StrategyCard
                key={strategy.slug}
                strategy={strategy}
                catalogue={catalogue}
                verdict={verdictFor(verdicts, strategy.slug)}
              />
            ))}
          </div>
        )}
      </section>
      <section aria-labelledby="builtin-strategies-heading" className="space-y-3">
        <h2 id="builtin-strategies-heading" className="text-xl font-semibold">
          Built-in strategies
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {builtins.map((strategy) => (
            <StrategyCard
              key={strategy.slug}
              strategy={strategy}
              catalogue={catalogue}
              verdict={verdictFor(verdicts, strategy.slug)}
            />
          ))}
        </div>
      </section>
    </div>
  );
}

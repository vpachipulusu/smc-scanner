'use client';

import { useState } from 'react';

/**
 * The two opt-in multi-timeframe switches shared by the scan form and the schedule form. The
 * alignment switch needs the first one (the API rejects it otherwise), so it stays disabled and
 * unchecked until context is on; a disabled checkbox is not submitted.
 */

export const MTF_LABEL = 'Include higher/lower timeframe context';
export const REQUIRE_HTF_LABEL = 'Require higher-timeframe alignment';
export const MTF_HINT =
  'Sends the next higher and lower timeframe to the AI with each hit, so token cost roughly triples.';
export const REQUIRE_HTF_HINT =
  'Hides hits the higher timeframe does not confirm. Needs the context option. Not part of the 0-4 score.';

const CHECKBOX_LABEL_CLASSES = 'flex min-h-11 items-center gap-2 text-sm';
const HINT_CLASSES = 'text-xs text-muted-foreground';

type MtfOptionsProps = {
  idPrefix: string;
  mtfName: string;
  requireName: string;
  defaultMtf: boolean;
  defaultRequire: boolean;
  /** Field error for the alignment switch, shown and linked to it. */
  requireError?: string;
};

export function MtfOptions({
  idPrefix,
  mtfName,
  requireName,
  defaultMtf,
  defaultRequire,
  requireError,
}: MtfOptionsProps) {
  const [mtf, setMtf] = useState(defaultMtf);
  const [require, setRequire] = useState(defaultRequire && defaultMtf);
  const mtfHintId = `${idPrefix}-mtf-hint`;
  const requireHintId = `${idPrefix}-require-htf-hint`;
  const requireErrorId = `${idPrefix}-require-htf-error`;

  return (
    <div className="space-y-1">
      <div>
        <label className={CHECKBOX_LABEL_CLASSES}>
          <input
            id={`${idPrefix}-mtf`}
            type="checkbox"
            name={mtfName}
            value="1"
            checked={mtf}
            onChange={(event) => {
              setMtf(event.target.checked);
              if (!event.target.checked) setRequire(false);
            }}
            aria-describedby={mtfHintId}
            className="size-4 rounded border-input"
          />
          {MTF_LABEL}
        </label>
        <p id={mtfHintId} className={HINT_CLASSES}>
          {MTF_HINT}
        </p>
      </div>
      <div>
        <label className={CHECKBOX_LABEL_CLASSES}>
          <input
            id={`${idPrefix}-require-htf`}
            type="checkbox"
            name={requireName}
            value="1"
            checked={mtf && require}
            disabled={!mtf}
            onChange={(event) => setRequire(event.target.checked)}
            aria-invalid={requireError ? true : undefined}
            aria-describedby={[requireHintId, requireError ? requireErrorId : null]
              .filter(Boolean)
              .join(' ')}
            className="size-4 rounded border-input"
          />
          {REQUIRE_HTF_LABEL}
        </label>
        <p id={requireHintId} className={HINT_CLASSES}>
          {REQUIRE_HTF_HINT}
        </p>
        {requireError && (
          <p id={requireErrorId} className="mt-1 text-xs text-crit-foreground">
            {requireError}
          </p>
        )}
      </div>
    </div>
  );
}

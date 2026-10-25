// @vitest-environment node
/** The strategy pages read live data, validate route input and show only the fixed error messages. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { BUILTIN, CATALOGUE, makeStrategy } from '../../helpers/strategies-page-fixtures';

const mocks = vi.hoisted(() => ({
  fetchStrategies: vi.fn(),
  fetchStrategy: vi.fn(),
  fetchConditionCatalogue: vi.fn(),
  notFound: vi.fn(),
}));
vi.mock('@/lib/api/strategies-write', () => ({
  fetchStrategies: mocks.fetchStrategies,
  fetchStrategy: mocks.fetchStrategy,
  fetchConditionCatalogue: mocks.fetchConditionCatalogue,
}));
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));
vi.mock('@/app/strategies/actions', () => ({
  saveStrategyAction: vi.fn(),
  deleteStrategyAction: vi.fn(),
}));

import EditStrategyPage from '@/app/strategies/[slug]/edit/page';
import StrategiesLoading from '@/app/strategies/loading';
import NewStrategyPage from '@/app/strategies/new/page';
import StrategiesPage from '@/app/strategies/page';
import {
  CONDITIONS_UNAVAILABLE_MESSAGE,
  STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
  STRATEGY_BUILTIN_MESSAGE,
  STRATEGY_NOT_FOUND_MESSAGE,
} from '@/lib/api/strategies-write-messages';

class NotFoundSignal extends Error {}

const ok = <T,>(data: T) => ({ success: true, data });
const fail = (error: string, status?: number) => ({ success: false, error, status });

const list = (saved?: string, deleted?: string) =>
  StrategiesPage({ searchParams: Promise.resolve({ saved, deleted }) });
const create = (from?: string | string[]) =>
  NewStrategyPage({ searchParams: Promise.resolve(from === undefined ? {} : { from }) });
const edit = (slug: string) => EditStrategyPage({ params: Promise.resolve({ slug }) });

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.notFound.mockImplementation(() => {
    throw new NotFoundSignal('NEXT_NOT_FOUND');
  });
  mocks.fetchStrategies.mockResolvedValue(ok([BUILTIN, makeStrategy()]));
  mocks.fetchStrategy.mockResolvedValue(ok(makeStrategy()));
  mocks.fetchConditionCatalogue.mockResolvedValue(ok(CATALOGUE));
});

describe('StrategiesPage', () => {
  it('lists built-in and custom strategies with a new-strategy link', async () => {
    const html = renderToStaticMarkup(await list());

    expect(html).toContain('Built-in, read-only');
    expect(html).toContain('My setup');
    expect(html).toContain('href="/strategies/new"');
    expect(html).toContain('href="/scan?strategy=my-setup"');
    expect(html).toContain('First touch only');
  });

  it('confirms a save for a known slug only', async () => {
    expect(renderToStaticMarkup(await list('my-setup'))).toContain('Saved “My setup”.');
    expect(renderToStaticMarkup(await list('Bad Slug'))).not.toContain('Saved');
    expect(renderToStaticMarkup(await list('unknown'))).not.toContain('Saved');
  });

  it('confirms a delete only once the strategy is gone', async () => {
    expect(renderToStaticMarkup(await list(undefined, 'old-one'))).toContain(
      'Deleted strategy old-one.'
    );
    expect(renderToStaticMarkup(await list(undefined, 'my-setup'))).not.toContain('Deleted');
    expect(renderToStaticMarkup(await list(undefined, '../x'))).not.toContain('Deleted');
  });

  it('shows the fixed error and a retry when the list fails', async () => {
    mocks.fetchStrategies.mockResolvedValue(fail(STRATEGIES_STORE_UNAVAILABLE_MESSAGE, 503));

    const html = renderToStaticMarkup(await list());

    expect(html).toContain(STRATEGIES_STORE_UNAVAILABLE_MESSAGE);
    expect(html).toContain('Retry');
    expect(html).not.toContain('href="/strategies/new"');
  });

  it('falls back to condition keys without the catalogue', async () => {
    mocks.fetchConditionCatalogue.mockResolvedValue(fail(CONDITIONS_UNAVAILABLE_MESSAGE));

    const html = renderToStaticMarkup(await list());

    expect(html).toContain('max_zone_age (bars 50)');
  });
});

describe('NewStrategyPage', () => {
  it('renders an empty create form', async () => {
    const html = renderToStaticMarkup(await create());

    expect(html).toContain('New strategy');
    expect(html).toContain('Create strategy');
    expect(html).toContain('name="slug"');
  });

  it('prefills a duplicate of a built-in with a free slug', async () => {
    const html = renderToStaticMarkup(await create('smc-default'));

    expect(html).toContain('Duplicate “SMC default”');
    expect(html).toContain('value="smc-default-copy"');
    expect(html).toContain('value="SMC default (copy)"');
  });

  it('warns when the source is gone or invalid', async () => {
    expect(renderToStaticMarkup(await create('gone'))).toContain(STRATEGY_NOT_FOUND_MESSAGE);
    expect(renderToStaticMarkup(await create(['a', 'b']))).toContain(STRATEGY_NOT_FOUND_MESSAGE);
  });

  it('shows the fixed error when data is missing', async () => {
    mocks.fetchConditionCatalogue.mockResolvedValue(fail(CONDITIONS_UNAVAILABLE_MESSAGE));
    expect(renderToStaticMarkup(await create())).toContain(CONDITIONS_UNAVAILABLE_MESSAGE);

    mocks.fetchStrategies.mockResolvedValue(fail(STRATEGIES_STORE_UNAVAILABLE_MESSAGE, 503));
    const html = renderToStaticMarkup(await create());
    expect(html).toContain(STRATEGIES_STORE_UNAVAILABLE_MESSAGE);
    expect(html).not.toContain('Create strategy');
  });
});

describe('EditStrategyPage', () => {
  it('renders the edit form for a custom strategy', async () => {
    const html = renderToStaticMarkup(await edit('my-setup'));

    expect(html).toContain('Edit “My setup”');
    expect(html).toContain('Save changes');
    expect(mocks.fetchStrategy).toHaveBeenCalledWith('my-setup');
  });

  it('is not found for a bad slug or a 404', async () => {
    await expect(edit('Bad Slug')).rejects.toThrow(NotFoundSignal);
    expect(mocks.fetchStrategy).not.toHaveBeenCalled();
    mocks.fetchStrategy.mockResolvedValue(fail(STRATEGY_NOT_FOUND_MESSAGE, 404));
    await expect(edit('gone')).rejects.toThrow(NotFoundSignal);
  });

  it('offers a duplicate instead of editing a built-in', async () => {
    mocks.fetchStrategy.mockResolvedValue(ok(BUILTIN));

    const html = renderToStaticMarkup(await edit('smc-default'));

    expect(html).toContain(STRATEGY_BUILTIN_MESSAGE);
    expect(html).toContain('href="/strategies/new?from=smc-default"');
    expect(html).not.toContain('Save changes');
  });

  it('notes conditions that are no longer in the catalogue', async () => {
    mocks.fetchStrategy.mockResolvedValue(
      ok(makeStrategy({ require: [{ key: 'retired', params: {} }] }))
    );

    expect(renderToStaticMarkup(await edit('my-setup'))).toContain('dropped on save: retired.');
  });

  it('shows the fixed error when data is missing', async () => {
    mocks.fetchStrategy.mockResolvedValue(fail(STRATEGIES_STORE_UNAVAILABLE_MESSAGE, 503));
    expect(renderToStaticMarkup(await edit('my-setup'))).toContain(
      STRATEGIES_STORE_UNAVAILABLE_MESSAGE
    );

    mocks.fetchStrategy.mockResolvedValue(ok(makeStrategy()));
    mocks.fetchConditionCatalogue.mockResolvedValue(fail(CONDITIONS_UNAVAILABLE_MESSAGE));
    expect(renderToStaticMarkup(await edit('my-setup'))).toContain(CONDITIONS_UNAVAILABLE_MESSAGE);
  });
});

describe('StrategiesLoading', () => {
  it('is a busy region with a status', () => {
    const html = renderToStaticMarkup(<StrategiesLoading />);

    expect(html).toContain('aria-busy="true"');
    expect(html).toContain('Loading strategies');
  });
});

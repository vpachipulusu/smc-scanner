// @vitest-environment node
/** The strategy server actions validate allow-listed fields, call the wrappers and map failures. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CATALOGUE, VALID_FORM, formOf, makeStrategy } from '../../helpers/strategy-fixtures';

const mocks = vi.hoisted(() => ({
  addStrategy: vi.fn(),
  editStrategy: vi.fn(),
  removeStrategy: vi.fn(),
  fetchConditionCatalogue: vi.fn(),
  revalidatePath: vi.fn(),
  redirect: vi.fn(),
  /** Real `redirect` throws; a flag on a plain wrapper avoids vitest 5's spy-throw failure. */
  redirectThrows: false,
  /** A plain function (not a spy): vitest 5 fails a test when a spy throws, even if it is caught. */
  thrower: null as (() => Promise<never>) | null,
}));
vi.mock('@/lib/api/strategies-write', () => ({
  addStrategy: (...a: unknown[]) => mocks.thrower?.() ?? mocks.addStrategy(...a),
  editStrategy: (...a: unknown[]) => mocks.thrower?.() ?? mocks.editStrategy(...a),
  removeStrategy: (...a: unknown[]) => mocks.thrower?.() ?? mocks.removeStrategy(...a),
  fetchConditionCatalogue: (...a: unknown[]) => mocks.fetchConditionCatalogue(...a),
}));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('next/navigation', () => ({
  redirect: (path: string) => {
    mocks.redirect(path);
    if (mocks.redirectThrows) throw new Error('NEXT_REDIRECT');
  },
}));

import { deleteStrategyAction, saveStrategyAction } from '@/app/strategies/actions';
import {
  CONDITIONS_UNAVAILABLE_MESSAGE,
  STRATEGIES_REQUEST_FAILED_MESSAGE,
  STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
  STRATEGY_BUILTIN_MESSAGE,
  STRATEGY_LIMIT_MESSAGE,
  STRATEGY_SLUG_TAKEN_MESSAGE,
} from '@/lib/api/strategies-write-messages';
import { IDLE_STRATEGY_FORM_STATE, IDLE_STRATEGY_ROW_STATE } from '@/lib/strategies/state';

const save = (patch: Record<string, string | readonly string[]> = {}) =>
  saveStrategyAction(IDLE_STRATEGY_FORM_STATE, formOf({ ...VALID_FORM, ...patch }));

beforeEach(() => {
  for (const mock of Object.values(mocks))
    if (typeof mock === 'function' && 'mockReset' in mock) mock.mockReset();
  mocks.thrower = null;
  mocks.redirectThrows = false;
  mocks.fetchConditionCatalogue.mockResolvedValue({ success: true, data: CATALOGUE });
});

describe('saveStrategyAction', () => {
  it('creates a strategy, revalidates and redirects to the list', async () => {
    mocks.addStrategy.mockResolvedValue({ success: true, data: makeStrategy() });
    mocks.redirectThrows = true;

    // redirect() throws NEXT_REDIRECT in production; it must propagate, not be swallowed.
    await expect(save()).rejects.toThrow('NEXT_REDIRECT');

    expect(mocks.addStrategy).toHaveBeenCalledWith(
      expect.objectContaining({
        slug: 'my-setup',
        min_score: 1,
        require: [{ key: 'fresh', params: {} }],
      })
    );
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/strategies');
    expect(mocks.redirect).toHaveBeenCalledWith('/strategies?saved=my-setup');
  });

  it('updates by the hidden slug without sending a slug in the body', async () => {
    mocks.editStrategy.mockResolvedValue({ success: true, data: makeStrategy() });

    await save({ mode: 'edit', slug: 'my-setup' });

    const [slug, body] = mocks.editStrategy.mock.calls[0];
    expect(slug).toBe('my-setup');
    expect(body).not.toHaveProperty('slug');
    expect(mocks.addStrategy).not.toHaveBeenCalled();
  });

  it('returns field errors without calling the API', async () => {
    const state = await save({ name: '', min_score: '5' });

    expect(state).toMatchObject({
      status: 'error',
      errors: { name: expect.any(String), min_score: expect.any(String) },
    });
    expect(mocks.addStrategy).not.toHaveBeenCalled();
  });

  it('refuses a bad or built-in slug on edit before anything else', async () => {
    expect(await save({ mode: 'edit', slug: 'Bad Slug' })).toMatchObject({
      message: 'That strategy slug is not valid.',
    });
    expect(await save({ mode: 'edit', slug: 'smc-default' })).toMatchObject({
      message: STRATEGY_BUILTIN_MESSAGE,
    });
    expect(mocks.fetchConditionCatalogue).not.toHaveBeenCalled();
  });

  it('keeps the typed values when the catalogue is unavailable', async () => {
    mocks.fetchConditionCatalogue.mockResolvedValue({
      success: false,
      error: CONDITIONS_UNAVAILABLE_MESSAGE,
    });

    const state = await save();

    expect(state).toMatchObject({
      status: 'error',
      message: CONDITIONS_UNAVAILABLE_MESSAGE,
      values: { name: 'My setup' },
    });
  });

  it('puts a taken slug on the slug field', async () => {
    mocks.addStrategy.mockResolvedValue({
      success: false,
      error: STRATEGY_SLUG_TAKEN_MESSAGE,
      status: 409,
    });

    expect(await save()).toMatchObject({
      status: 'error',
      errors: { slug: STRATEGY_SLUG_TAKEN_MESSAGE },
    });
  });

  it.each([
    [STRATEGY_LIMIT_MESSAGE, 409],
    [STRATEGY_BUILTIN_MESSAGE, 409],
    ['Too many strategy requests. Try again in 3 seconds.', 429],
    [STRATEGIES_STORE_UNAVAILABLE_MESSAGE, 503],
  ])('shows "%s" as the form message', async (error, status) => {
    mocks.addStrategy.mockResolvedValue({ success: false, error, status });

    const state = await save();

    expect(state).toMatchObject({
      status: 'error',
      message: error,
      errors: {},
      values: { slug: 'my-setup' },
    });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });

  it('turns a throwing wrapper into the generic message', async () => {
    mocks.thrower = () => Promise.reject(new Error('boom'));

    expect(await save()).toMatchObject({ message: STRATEGIES_REQUEST_FAILED_MESSAGE });
  });
});

describe('deleteStrategyAction', () => {
  const remove = (slug: string) => deleteStrategyAction(IDLE_STRATEGY_ROW_STATE, formOf({ slug }));

  it('deletes, revalidates and redirects to the list to announce it', async () => {
    mocks.removeStrategy.mockResolvedValue({ success: true, data: null });
    mocks.redirectThrows = true;

    await expect(remove('my-setup')).rejects.toThrow('NEXT_REDIRECT');

    expect(mocks.removeStrategy).toHaveBeenCalledWith('my-setup');
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/strategies');
    expect(mocks.redirect).toHaveBeenCalledWith('/strategies?deleted=my-setup');
  });

  it('treats a strategy that is already gone as deleted', async () => {
    mocks.removeStrategy.mockResolvedValue({ success: false, error: 'gone', status: 404 });

    await remove('my-setup');

    expect(mocks.redirect).toHaveBeenCalledWith('/strategies?deleted=my-setup');
  });

  it('refuses a bad slug and a built-in without calling the API', async () => {
    expect(await remove('../x')).toEqual({
      status: 'error',
      message: 'That strategy slug is not valid.',
    });
    expect(await remove('fresh-ob-trend')).toEqual({
      status: 'error',
      message: STRATEGY_BUILTIN_MESSAGE,
    });
    expect(mocks.removeStrategy).not.toHaveBeenCalled();
  });

  it('reports the wrapper message on failure', async () => {
    mocks.removeStrategy.mockResolvedValue({
      success: false,
      error: STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
    });

    expect(await remove('my-setup')).toEqual({
      status: 'error',
      message: STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
    });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });

  it('turns a throwing wrapper into the generic message', async () => {
    mocks.thrower = () => Promise.reject(new Error('boom'));

    expect(await remove('my-setup')).toEqual({
      status: 'error',
      message: STRATEGIES_REQUEST_FAILED_MESSAGE,
    });
  });
});

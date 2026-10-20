export const THEME_STORAGE_KEY = 'smc-theme';

export type Theme = 'light' | 'dark';

/**
 * Runs in <head> before first paint (inline in the root layout) so the page never flashes the
 * wrong theme. Storage may be blocked, so every read is guarded.
 */
export const themeInitScript = `(function(){try{var t=null;try{t=localStorage.getItem('${THEME_STORAGE_KEY}')}catch(e){}if(t!=='dark'&&t!=='light'){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.classList.toggle('dark',t==='dark');document.documentElement.dataset.theme=t}catch(e){}})();`;

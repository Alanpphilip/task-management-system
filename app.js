(() => {
  const root = document.documentElement;
  const themeButton = document.querySelector('[data-theme-toggle]');
  const themeIcon = document.querySelector('[data-theme-icon]');
  const storedTheme = localStorage.getItem('taskflow-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  function applyTheme(theme) {
    root.dataset.theme = theme;
    if (themeIcon) themeIcon.textContent = theme === 'dark' ? '☀' : '☾';
    if (themeButton) {
      const nextTheme = theme === 'dark' ? 'light' : 'dark';
      themeButton.setAttribute('aria-label', `Switch to ${nextTheme} mode`);
      themeButton.title = `Switch to ${nextTheme} mode`;
    }
  }

  applyTheme(storedTheme || (prefersDark ? 'dark' : 'light'));
  themeButton?.addEventListener('click', () => {
    const nextTheme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('taskflow-theme', nextTheme);
    applyTheme(nextTheme);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
    const active = document.activeElement;
    if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName)) return;
    const search = document.querySelector('.search-input');
    if (search) {
      event.preventDefault();
      search.focus();
    }
  });
})();

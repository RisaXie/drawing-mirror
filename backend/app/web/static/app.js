/**
 * Drawing Mirror — shared utilities
 * API client, state management (localStorage), navigation helpers
 */

const API = {
  base: '/api',

  async get(path) {
    const res = await fetch(this.base + path);
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
    return res.json();
  },

  async post(path, body) {
    const res = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
    return res.json();
  },
};

const State = {
  get userId() { return parseInt(localStorage.getItem('dm_user_id') || '0'); },
  set userId(v) { localStorage.setItem('dm_user_id', String(v)); },

  get username() { return localStorage.getItem('dm_username') || ''; },
  set username(v) { localStorage.setItem('dm_username', v); },
};

function navigate(page, params = {}) {
  const qs = new URLSearchParams(params).toString();
  window.location.href = qs ? `${page}?${qs}` : page;
}

function getParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}

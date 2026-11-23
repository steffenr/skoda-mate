// Sign-in page (/login). A file, not an inline script: the Content-Security-Policy allows no inline code.
const $ = (id) => document.getElementById(id);
$('f').onsubmit = async (ev) => {
  ev.preventDefault();
  const m = $('m');
  m.textContent = '';
  const r = await fetch('/api/login', { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email: $('e').value, password: $('p').value }) });
  if (r.ok) location.href = '/';
  else m.textContent = r.status == 429 ? 'Too many attempts. Try again in a few minutes.' : 'Wrong e-mail or password.';
};

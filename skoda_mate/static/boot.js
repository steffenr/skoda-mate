// Entry point of the dashboard page (a file, not an inline script: the Content-Security-Policy allows no inline code).
import { start } from './app.js';

start(document.getElementById('root'));

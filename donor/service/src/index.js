import { createServer } from './server.js';
import { PORT } from './config.js';

createServer().listen(PORT, '0.0.0.0', () => {
  console.log(`donor listening on 0.0.0.0:${PORT}`);
});

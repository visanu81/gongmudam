// Worker entry: the public demo runs in one Cloudflare container, not on a PC.
import {Container} from '@cloudflare/containers';
import {handle} from './worker.js';

export class GongmudamDemo extends Container {
  defaultPort = 8080;
  // Idle containers sleep; the next start restores a fresh synthetic demo.
  sleepAfter = '20m';

  constructor(ctx, env) {
    super(ctx, env);
    // The Upstage key stays a Worker secret and is never baked into the image.
    this.envVars = {UPSTAGE_API_KEY: env.UPSTAGE_API_KEY || ''};
  }
}

export default {
  fetch(request, env) {
    return handle(request, env, env.DEMO.getByName('public-demo'));
  },
};

// Worker entry: the public demo runs in one Cloudflare container, not on a PC.
import {Container} from '@cloudflare/containers';
import {handle} from './worker.js';
// Written by tools/stage_container.py during npm run deploy.
import release from '../work/container-stage/release.json';

// Same size as the former "basic" instance type; the app uses about 130 MiB.
const INSTANCE = {vcpu: 0.25, memoryMib: 1024, diskMb: 4096};

export class GongmudamDemo extends Container {
  defaultPort = 8080;
  // Idle containers sleep; the next start restores a fresh synthetic demo.
  sleepAfter = '20m';

  constructor(ctx, env) {
    super(ctx, env);
    // The Upstage key stays a Worker secret and is never baked into the image.
    this.envVars = {UPSTAGE_API_KEY: env.UPSTAGE_API_KEY || ''};
    // The durable_object scheduling policy needs the image and size at start;
    // the helper library does not pass them, so add them to every start call.
    const raw = ctx.container;
    this.container = new Proxy(raw, {
      get(target, name) {
        if (name === 'start') return (options = {}) => target.start({image: target.images.base, instance: INSTANCE, ...options});
        const value = target[name];
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
  }
}

export default {
  fetch(request, env) {
    // One instance per release: a running container keeps its old image until it sleeps,
    // so a new name makes the deploy take effect at once; the old instance sleeps unused.
    return handle(request, env, env.DEMO.getByName('public-demo-' + release.version));
  },
};

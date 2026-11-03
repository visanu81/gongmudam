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
    this.lastRequest = Date.now();
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

  // The library waits about 20s for the port when a request wakes the container.
  // A cold start restores the demo and loads the service, which can take longer;
  // the first visitor after a sleep then got "Failed to start container" (2026-11-02).
  async fetch(request) {
    this.lastRequest = Date.now();
    if (!this.container.running) {
      await this.startAndWaitForPorts(this.defaultPort, WAKE, undefined).catch(() => {});
    }
    return super.fetch(request);
  }

  // The container stayed up for hours with no visitors (2026-11-03). The library only
  // sleeps once its in-flight request count is zero, and a response body nobody reads
  // keeps that count up for good. No request here runs for 20 minutes, so a 20-minute
  // silence means the count is stale and the container may sleep.
  isActivityExpired() {
    if (Date.now() - this.lastRequest >= SLEEP_MS) {
      this.inflightRequests = 0;
      return true;
    }
    return super.isActivityExpired();
  }

  // One line per alarm (about every 3 minutes while running), read with wrangler tail.
  async alarm(props) {
    console.log(JSON.stringify({event: 'container-alarm', running: this.container.running,
      inflight: this.inflightRequests, idleSeconds: Math.round((Date.now() - this.lastRequest) / 1000)}));
    return super.alarm(props);
  }

  async onActivityExpired() {
    console.log(JSON.stringify({event: 'container-sleep', inflight: this.inflightRequests}));
    return super.onActivityExpired();
  }
}

const SLEEP_MS = 20 * 60_000;
const WAKE = {instanceGetTimeoutMS: 30_000, portReadyTimeoutMS: 120_000};

export default {
  fetch(request, env) {
    // One instance per release: a running container keeps its old image until it sleeps,
    // so a new name makes the deploy take effect at once; the old instance sleeps unused.
    return handle(request, env, env.DEMO.getByName('public-demo-' + release.version));
  },
};

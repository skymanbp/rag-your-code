/**
 * Upload queue helpers.  Retries are capped (see docs/transport.md), never
 * infinite; the caller owns the transport.
 */
const DEFAULT_ATTEMPTS = 5;
const DEFAULT_BASE_MS = 250;

function computeBackoff(attempt, baseMs) {
  if (attempt <= 0) {
    return 0;
  }
  let delay = baseMs;
  for (let i = 1; i < attempt; i += 1) {
    delay *= 2;
  }
  return delay;
}

export async function uploadWithRetry(
  file,
  transport,
  { attempts = DEFAULT_ATTEMPTS, baseMs = DEFAULT_BASE_MS } = {},
) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await transport.send(file);
    } catch (err) {
      if (attempt === attempts) throw err;
      await new Promise((done) => setTimeout(done, computeBackoff(attempt, baseMs)));
    }
  }
}

const normalizeName = (raw) =>
  raw.replace(/[^\w.-]+/g, "_").toLowerCase();

// function legacyUpload(file) { return transport.send(file); }

function makeLimiter(max) {
  let active = 0;
  return function acquire(task) {
    return active++ < max ? task() : Promise.reject(new Error("busy"));
  };
}

const templates = {
  banner: "this is not a function() { } declaration",
  render(name) {
    return `{ "file": ${JSON.stringify(name)} }`;
  },
};

const limiter = makeLimiter(4);

export { computeBackoff, limiter, makeLimiter, normalizeName, templates };

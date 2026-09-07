// Adafruit IO is used as a hosted MQTT broker. The Worker never opens an
// MQTT connection itself (Cloudflare Workers can't hold long-lived TCP
// sockets to arbitrary brokers) — it talks to Adafruit IO's REST API
// instead, which publishes to the same feed any MQTT subscriber reads.
const AIO_BASE = 'https://io.adafruit.com/api/v2';

function feedUrl(env, feed, suffix = '') {
  return `${AIO_BASE}/${env.AIO_USERNAME}/feeds/${feed}${suffix}`;
}

/**
 * Publish a server-command message. `target` is the lowercase game name,
 * or null for a PC-wide action (shutdown_pc).
 */
export async function publishCommand(env, { action, target = null, userId }) {
  const payload = {
    action,
    target,
    source: 'discord',
    user: userId,
    timestamp: new Date().toISOString(),
  };

  const res = await fetch(feedUrl(env, 'server-command', '/data'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-AIO-Key': env.AIO_KEY,
    },
    body: JSON.stringify({ value: JSON.stringify(payload) }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Adafruit IO publish failed (${res.status}): ${body}`);
  }

  return payload;
}

/**
 * Read the last retained value of server-status. Returns null if the feed
 * has never been published to (e.g. status-daemon has never run yet).
 */
export async function fetchStatus(env) {
  const res = await fetch(feedUrl(env, 'server-status', '/data/last'), {
    headers: { 'X-AIO-Key': env.AIO_KEY },
  });

  if (res.status === 404) return null;
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Adafruit IO status fetch failed (${res.status}): ${body}`);
  }

  const data = await res.json();
  if (!data || typeof data.value !== 'string') return null;

  try {
    return JSON.parse(data.value);
  } catch {
    return null;
  }
}

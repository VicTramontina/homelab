// Registers global slash commands with Discord. Run automatically by
// .github/workflows/deploy-worker.yml on every push to discord-bot/**, so
// COMMAND_DEFINITIONS changes (e.g. a new game) go live without a manual
// step. Can also be run locally against the same env vars if needed:
//
//   DISCORD_BOT_TOKEN=... DISCORD_APPLICATION_ID=... node scripts/register-commands.js
//
// Global command updates can take up to an hour to propagate.
import { COMMAND_DEFINITIONS } from '../src/commands.js';

const token = process.env.DISCORD_BOT_TOKEN;
const applicationId = process.env.DISCORD_APPLICATION_ID;

if (!token || !applicationId) {
  console.error('Missing DISCORD_BOT_TOKEN or DISCORD_APPLICATION_ID in the environment.');
  process.exit(1);
}

const url = `https://discord.com/api/v10/applications/${applicationId}/commands`;

const res = await fetch(url, {
  method: 'PUT',
  headers: {
    Authorization: `Bot ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify(COMMAND_DEFINITIONS),
});

if (!res.ok) {
  console.error(`Failed to register commands (${res.status}):`, await res.text());
  process.exit(1);
}

const registered = await res.json();
console.log(`Registered ${registered.length} global command(s):`, registered.map((c) => c.name).join(', '));

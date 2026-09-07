// Standalone script to register global slash commands with Discord.
// Run locally (not deployed with the Worker):
//
//   DISCORD_BOT_TOKEN=... DISCORD_APPLICATION_ID=... node scripts/register-commands.js
//
// Global command updates can take up to an hour to propagate; re-run this
// any time COMMAND_DEFINITIONS in src/commands.js changes.
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

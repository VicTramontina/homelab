import { verifyKey } from 'discord-interactions';
import { GAMES, isKnownGame } from './commands.js';
import { publishCommand, fetchStatus } from './mqtt.js';

const InteractionType = { PING: 1, APPLICATION_COMMAND: 2, MESSAGE_COMPONENT: 3 };
const InteractionResponseType = {
  PONG: 1,
  CHANNEL_MESSAGE_WITH_SOURCE: 4,
};

const COLOR_RUNNING = 0x57f287; // green
const COLOR_STOPPED = 0x99aab5; // gray
const COLOR_UNKNOWN = 0xfee75c; // yellow

function jsonResponse(body) {
  return new Response(JSON.stringify(body), {
    headers: { 'content-type': 'application/json' },
  });
}

function unixSeconds(isoString) {
  const ms = Date.parse(isoString);
  return Number.isNaN(ms) ? null : Math.floor(ms / 1000);
}

function formatTimestamp(isoString, style = 'R') {
  const ts = unixSeconds(isoString);
  return ts === null ? 'never' : `<t:${ts}:${style}>`;
}

function gameRow(gameKey, gameInfo, gameStatus) {
  const label = gameInfo.label;
  const state = gameStatus?.state ?? 'unknown';
  const players = gameStatus?.players ?? 0;
  const maxPlayers = gameStatus?.max_players ?? '?';
  const lastBackup = gameStatus?.last_backup ? formatTimestamp(gameStatus.last_backup) : 'never';

  return {
    name: `${state === 'running' ? '🟢' : state === 'stopped' ? '⚪' : '🟡'} ${label}`,
    value: `State: **${state}**\nPlayers: **${players}/${maxPlayers}**\nLast backup: ${lastBackup}`,
    inline: true,
  };
}

function buildStatusEmbed(status, gameFilter = null) {
  if (!status) {
    return {
      embeds: [
        {
          title: 'Homelab status',
          description: 'No status has been reported yet. The PC may be off, or status-daemon has never run.',
          color: COLOR_UNKNOWN,
        },
      ],
    };
  }

  const games = status.games ?? {};
  const gameKeys = gameFilter ? [gameFilter] : Object.keys(GAMES);

  const anyRunning = Object.values(games).some((g) => g.state === 'running');
  const color = status.pc_state === 'on' ? (anyRunning ? COLOR_RUNNING : COLOR_STOPPED) : COLOR_UNKNOWN;

  const embed = {
    title: gameFilter ? `${GAMES[gameFilter]?.label ?? gameFilter} status` : 'Homelab status',
    color,
    fields: gameKeys.map((key) => gameRow(key, GAMES[key] ?? { label: key }, games[key])),
    footer: { text: `PC: ${status.pc_state ?? 'unknown'}` },
    timestamp: status.timestamp,
  };

  const components = gameKeys
    .filter((key) => GAMES[key])
    .map((key) => {
      const running = games[key]?.state === 'running';
      return {
        type: 1,
        components: [
          {
            type: 2,
            style: running ? 4 : 3,
            label: running ? `Stop ${GAMES[key].label}` : `Start ${GAMES[key].label}`,
            custom_id: `${running ? 'stop_game' : 'start_game'}:${key}`,
          },
          {
            type: 2,
            style: 2,
            label: `Backup ${GAMES[key].label}`,
            custom_id: `backup_game:${key}`,
          },
        ],
      };
    });

  return { embeds: [embed], components };
}

const ACTION_VERBS = {
  start_game: 'Start requested',
  stop_game: 'Stop requested (backup will run first)',
  backup_game: 'Backup requested',
  shutdown_pc: 'Shutdown requested (backups will run first)',
};

async function runAction(env, action, target, userId) {
  await publishCommand(env, { action, target, userId });
  const gameLabel = target ? (GAMES[target]?.label ?? target) : 'the PC';
  return `${ACTION_VERBS[action] ?? action} for **${gameLabel}**.`;
}

async function handleApplicationCommand(env, interaction) {
  const name = interaction.data.name;
  const options = Object.fromEntries((interaction.data.options ?? []).map((o) => [o.name, o.value]));
  const userId = interaction.member?.user?.id ?? interaction.user?.id;

  if (name === 'start' || name === 'stop' || name === 'backup') {
    const game = options.game;
    if (!isKnownGame(game)) {
      return jsonResponse({
        type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
        data: { content: `Unknown game: ${game}` },
      });
    }
    const action = name === 'start' ? 'start_game' : name === 'stop' ? 'stop_game' : 'backup_game';
    const content = await runAction(env, action, game, userId);
    return jsonResponse({
      type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
      data: { content },
    });
  }

  if (name === 'status') {
    const game = options.game && isKnownGame(options.game) ? options.game : null;
    const status = await fetchStatus(env);
    return jsonResponse({
      type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
      data: buildStatusEmbed(status, game),
    });
  }

  return jsonResponse({
    type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
    data: { content: `Unhandled command: ${name}` },
  });
}

async function handleMessageComponent(env, interaction) {
  const customId = interaction.data.custom_id ?? '';
  const [action, target] = customId.split(':');
  const userId = interaction.member?.user?.id ?? interaction.user?.id;

  if (!ACTION_VERBS[action] || (target && !isKnownGame(target))) {
    return jsonResponse({
      type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
      data: { content: `Unrecognized action: ${customId}` },
    });
  }

  const content = await runAction(env, action, target || null, userId);
  return jsonResponse({
    type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
    data: { content },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('homelab discord-bot worker', { status: 200 });
    }

    const signature = request.headers.get('X-Signature-Ed25519');
    const timestamp = request.headers.get('X-Signature-Timestamp');
    const body = await request.text();

    const isValid =
      signature &&
      timestamp &&
      (await verifyKey(body, signature, timestamp, env.DISCORD_PUBLIC_KEY));

    if (!isValid) {
      return new Response('Invalid request signature', { status: 401 });
    }

    const interaction = JSON.parse(body);

    if (interaction.type === InteractionType.PING) {
      return jsonResponse({ type: InteractionResponseType.PONG });
    }

    if (interaction.type === InteractionType.APPLICATION_COMMAND) {
      return handleApplicationCommand(env, interaction);
    }

    if (interaction.type === InteractionType.MESSAGE_COMPONENT) {
      return handleMessageComponent(env, interaction);
    }

    return new Response('Unhandled interaction type', { status: 400 });
  },
};

// Game catalog and slash command definitions for the homelab Discord bot.
//
// Adding a new game only requires a new entry here (plus a Docker Compose
// service and an Ansible RCON port/pass var) — no command-handling logic
// in index.js needs to change.
export const GAMES = {
  humanityz: {
    label: 'HumanityZ',
    rconPort: 8888,
  },
};

export const GAME_CHOICES = Object.entries(GAMES).map(([value, game]) => ({
  name: game.label,
  value,
}));

export const COMMAND_DEFINITIONS = [
  {
    name: 'start',
    description: 'Wake the PC (if needed) and start a game server',
    options: [
      {
        type: 3, // STRING
        name: 'game',
        description: 'Which game to start',
        required: true,
        choices: GAME_CHOICES,
      },
    ],
  },
  {
    name: 'stop',
    description: 'Back up and stop a running game server',
    options: [
      {
        type: 3,
        name: 'game',
        description: 'Which game to stop',
        required: true,
        choices: GAME_CHOICES,
      },
    ],
  },
  {
    name: 'status',
    description: 'Show the homelab status (PC + all games, or one game)',
    options: [
      {
        type: 3,
        name: 'game',
        description: 'Show detail for a single game (optional)',
        required: false,
        choices: GAME_CHOICES,
      },
    ],
  },
  {
    name: 'backup',
    description: 'Trigger an on-demand backup of a game to R2',
    options: [
      {
        type: 3,
        name: 'game',
        description: 'Which game to back up',
        required: true,
        choices: GAME_CHOICES,
      },
    ],
  },
];

export function isKnownGame(name) {
  return Object.prototype.hasOwnProperty.call(GAMES, name);
}

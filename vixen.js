const Discord = require("discord.js");
 //V.I.X.E.N.
const client = new Discord.Client({
    intents: ["GUILDS", "GUILD_MESSAGES", "GUILD_MEMBERS", "MESSAGE_CONTENT"],
    partials: ["CHANNEL", "MESSAGE"]
});
 
const token = ("REDACTED-DISCORD-TOKEN")
client.commands = new Discord.Collection();

const commandFiles = readdirSync('./commands').filter(file => file.endsWith('.js'));

for (const file of commandFiles) {
  const command = require(`./commands/${file}`);
  client.commands.set(command.name, command);
}

client.on('ready', async () => {
  console.log(`Client has been initiated! ${client.user.username}`);
});

client.on('messageCreate', async message => {
  if (!message.content.startsWith(prefix)) return; // You can set a prefix here

  const args = message.content.slice(prefix.length).trim().split(/ +/g);
  const commandName = args.shift().toLowerCase();

  const command = client.commands.get(commandName);
  if (!command) return;

  try {
    command.execute(message, args);
  } catch (error) {
    console.error(error);
    message.reply('There was an error executing that command!');
  }
});

client.login(token);
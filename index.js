const Discord = require("discord.js");
 
const client = new Discord.Client({
    intents: ["GUILDS", "GUILD_MESSAGES", "GUILD_MEMBERS", "MESSAGE_CONTENT"],
    partials: ["CHANNEL", "MESSAGE"]
});
 
const token = ("OTMzNDk1MTI5NTM1MzA3ODE2.GLctK6.OPOS1MG4gtnVCIoZN1HV-l7sbiNdyW9PN4SDOU") // your bot token here
 
client.on('ready', async () => {
    console.log(`Client has been initiated! ${client.user.username}`)
});
 
client.on('messageCreate', async (message) => {
    const commands = {
      "test": "Test successful!",
      "what do you think about louis?": "he is a buzzlightyear in the aisle"
    };
  
    const command = message.content.toLowerCase();
    if (commands[command]) {
      message.reply(commands[command]);
      console.log("a command has been used.")
    }
  });
 
client.login(token);
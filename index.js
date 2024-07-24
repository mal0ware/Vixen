const Discord = require("discord.js");
 
const client = new Discord.Client({
    intents: ["GUILDS", "GUILD_MESSAGES", "GUILD_MEMBERS", "MESSAGE_CONTENT"],
    partials: ["CHANNEL", "MESSAGE"]
});
 
const token = ("REDACTED-DISCORD-TOKEN") // your bot token here
 
client.on('ready', async () => {
    console.log(`Client has been initiated! ${client.user.username}`)
});
 
client.on('messageCreate', async (message) => {
    if (message.content.toLowerCase() === "vixen.") {
        console.log("slur has been said.")
        message.reply("louis, its terminal");
    }
});
 
client.login(token);
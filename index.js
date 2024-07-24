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
    if (message.content.toLowerCase() === "test") {
        console.log("slur has been said.")
        message.reply("wsg my nigga");
    }
});
 
client.login(token);
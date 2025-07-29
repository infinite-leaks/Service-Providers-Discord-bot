🛠️ Setup Instructions
To get your Discord bot up and running, follow these steps:

Clone the Repository and Install Dependencies:

Bash
git clone https://github.com/hbkvxncent/discord-status-bot.git
cd discord-status-bot
pip install -r requirements.txt
Configure Your Environment:
Create a file named .env in your bot's root directory and add your Discord bot token and your Discord user ID (for owner-only commands):

BOT_TOKEN=YOUR_BOT_TOKEN_HERE
OWNER_ID=YOUR_DISCORD_USER_ID
Replace YOUR_BOT_TOKEN_HERE with your actual bot token from the Discord Developer Portal.
Replace YOUR_DISCORD_USER_ID with your Discord user ID. You can usually get this by enabling Developer Mode in Discord settings, right-clicking your profile, and selecting "Copy ID."

Run the Bot:

Bash
python bot.py
Invite the Bot to Your Server:
Invite your bot to your Discord server with the following essential permissions:

Send Messages

Manage Webhooks

Embed Links

Use Application Commands (for slash commands)

⚙️ Permissions Needed
For full functionality, your bot requires these permissions in the servers it joins:

Manage Webhooks: Essential for setting up and managing automatic status updates.

Send Messages: Allows the bot to send responses and notifications.

Embed Links: Enables the bot to send rich, formatted messages (e.g., status updates).

Use Application Commands: Permits users to interact with your bot using slash commands.

📌 Commands
All commands for this bot are accessible via Discord's slash ( / ) command interface.

🟢 General Users

/checkstatus – Instantly check the live service status of Vercel, Cloudflare, or Netlify.

🔒 Owner Only

The following commands are restricted to the bot's designated owner (configured in your .env file):

/sendmessage – Send a message to a specific channel.

/sendembed – Send a custom-formatted embed message to a channel.

/broadcast – Broadcast messages to all servers your bot is in.

/multisend – Send messages to a list of specific server IDs.

/botstats – View real-time statistics about your bot, including uptime, number of servers, and latency.

🔧 Webhook Setup (Requires "Manage Webhooks" Permission)
These commands allow you to configure automated service status posting to specific channels.

/setupwebhook – Configure auto-posting for a service status to a designated channel.

/removewebhook – Stop auto-posting for a previously configured service.

/togglewebhook – Enable or disable an existing webhook for status updates without removing its configuration.

/listwebhooks – Display all active webhook configurations within the current server.

💾 Data Storage
This bot utilizes an SQLite database (bot_data.db) to persistently store webhook configurations and other essential data per server.

Important: For production environments or version control, consider the following:

Backup: Regularly back up your bot_data.db file to prevent data loss.

Version Control: It's highly recommended to add bot_data.db to your .gitignore file to prevent it from being committed to your public repository.

Your .gitignore file should look like this:

.env
bot_data.db
🔐 Security
Maintaining the security of your bot is crucial:

Never Share Your .env File: Your .env file contains sensitive credentials like your BOT_TOKEN. Keep this file strictly private and never share it publicly or commit it to version control.

Bot Token Leaks: If your BOT_TOKEN is ever compromised or leaked, immediately regenerate it through the Discord Developer Portal. A compromised token can allow unauthorized access to your bot.

Validate User Permissions: When adding new features or commands, always implement robust permission checks to ensure only authorized users can execute sensitive actions.

🧑‍💻 Credits
Developed by hbkvxncent
Built with ❤️ using discord.py


# 📡 Discord Status Bot

A powerful Discord bot that monitors service statuses (Vercel, Cloudflare, Netlify), posts updates automatically via webhooks, and provides admin-only messaging & broadcasting tools.

## 🚀 Features

- 🔧 Slash command support for interaction
- 📢 Automatic incident posting to webhooks every 5 minutes
- 📊 Real-time service status checking (Vercel, Cloudflare, Netlify)
- 🔁 Broadcast messages to all servers
- 🔐 Owner-only utility commands (spam, embed send, stats)
- 💾 SQLite local database for webhook tracking
- ⚡ Ultra-fast or throttled message sending options

---

## 📦 Requirements

- Python 3.9+
- Discord bot token
- Basic permissions to manage webhooks in target channels

### Python Dependencies

Install them using pip:

```bash
pip install -r requirements.txt

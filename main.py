import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from agent_core import chat_with_bot

# Load environment variables
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    try:
        # If chat_with_bot is async, await it directly
        if asyncio.iscoroutinefunction(chat_with_bot):
            bot_response = await chat_with_bot(user_message)
        else:
            bot_response = chat_with_bot(user_message)
        await update.message.reply_text(bot_response)
    except Exception as e:
        await update.message.reply_text("⚠️ Error: " + str(e))

def main():
    if not TELEGRAM_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN not set in .env")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Rebo is running locally...")
    app.run_polling()

if __name__ == "__main__":
    main()
  

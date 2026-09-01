import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
import database
import parser
import ui_components
import binance_api
import logging

logging.basicConfig(level=logging.INFO)

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
SOURCE_CHANNELS = [int(c.strip()) for c in os.getenv('SOURCE_CHANNELS', '').split(',') if c.strip()]
TRADE_CHANNEL_ID = int(os.getenv('TRADE_CHANNEL_ID', '0'))
UPDATES_CHANNEL_ID = int(os.getenv('UPDATES_CHANNEL_ID', '0'))
ACTIVE_TRADES_CHANNEL_ID = int(os.getenv('ACTIVE_TRADES_CHANNEL_ID', '0'))
PUBLIC_TRADE_CHANNEL_ID = int(os.getenv('PUBLIC_TRADE_CHANNEL_ID', '0'))
SIGNAL_KEYWORD = os.getenv('SIGNAL_KEYWORD', '')

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

async def update_box(box_id, client):
    active_channel_id = int(os.getenv('ACTIVE_TRADES_CHANNEL_ID', '0'))
    active_channel = client.get_channel(active_channel_id)
    if not active_channel:
        return
        
    trades = database.get_trades_for_box(box_id)
    embed = ui_components.create_global_log_box(trades)
    
    box_info = database.get_box_message(box_id)
    msg_id = box_info['message_id'] if box_info else None
    
    if msg_id:
        try:
            msg = await active_channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed)
            return
        except discord.NotFound:
            pass # Message deleted, fall through to send a new one
        except Exception as e:
            logging.error(f"Error editing dashboard: {e}")
            return
            
    # Send new dashboard message
    try:
        msg = await active_channel.send(embed=embed)
        database.update_box_message(box_id, msg.id, active_channel.id)
    except Exception as e:
        logging.error(f"Error sending new dashboard: {e}")


@bot.event
async def on_trade_action(trade, action_msg, author_name):
    # Log to updates channel only if action_msg is provided
    updates_channel = bot.get_channel(UPDATES_CHANNEL_ID)
    logging.info(f"Updates channel found: {updates_channel is not None}, action_msg: {action_msg}")
    if updates_channel and action_msg:
        ping = trade.get('author_ping') or f"@{trade.get('author_name')}"
        log_text = f"{trade['direction']} {trade['pair']} : {action_msg} {ping}"
        await updates_channel.send(log_text)
        
    # Update box
    if trade and 'box_id' in trade and trade['box_id']:
        await update_box(trade['box_id'], bot)

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user.name}')
    database.init_db()
    if not price_check_loop.is_running():
        price_check_loop.start()

@bot.command()
async def reset_trades(ctx):
    # Only allow in testing or by admins if needed, for now open to anyone
    import sqlite3
    conn = sqlite3.connect(database.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trades")
    cursor.execute("DELETE FROM log_boxes")
    conn.commit()
    conn.close()
    database.clear_global_dashboard()
    database.set_setting('global_box_updates', '0')
    database.set_setting('global_box_start_trade_id', '0')
    await ctx.send("? All old test trades have been wiped from the database! The next trade will start completely fresh.")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    # Check if message is in one of the source channels
    if message.channel.id in SOURCE_CHANNELS:
        logging.info(f"Received message in source channel {message.channel.id}")
        # If a signal keyword is defined, skip messages that don't contain it
        if SIGNAL_KEYWORD and SIGNAL_KEYWORD.upper() not in message.content.upper():
            logging.info(f"Message ignored: did not contain keyword '{SIGNAL_KEYWORD}'")
            return

        trade_data = parser.parse_trade_signal(message.content)
        
        if trade_data:
            logging.info(f"New trade detected: {trade_data}")
            
            initial_status = 'ACTIVE' if '@M' in message.content.upper() else 'WAITING'
            
            # Fetch CMP for market orders
            if trade_data['entry'] == -1.0:
                cmp = await binance_api.get_current_price(trade_data['pair'])
                if cmp:
                    trade_data['entry'] = cmp
                else:
                    logging.error(f"Failed to fetch CMP for {trade_data['pair']}. Defaulting to 0.0")
                    trade_data['entry'] = 0.0
                    
            # Determine who to ping and the display name
            author_name = message.author.display_name
            author_ping = message.author.mention
            if message.role_mentions:
                author_name = message.role_mentions[0].name
                author_ping = message.role_mentions[0].mention
                
            trade_id = database.insert_trade(
                trade_data['pair'],
                trade_data['direction'],
                trade_data['entry'],
                trade_data['tp'],
                trade_data['sl'],
                author_name,
                author_ping=author_ping,
                status=initial_status
            )
            
            trade = database.get_trade(trade_id)
            
            trade_channel = bot.get_channel(TRADE_CHANNEL_ID)
            public_channel = bot.get_channel(PUBLIC_TRADE_CHANNEL_ID)
            
            logging.info(f"Trade Channel found: {trade_channel is not None}")
            logging.info(f"Public Channel found: {public_channel is not None}")
            
            if trade_channel:
                embed = ui_components.create_trade_embed(trade)
                view = ui_components.TradeView(trade_id)
                msg_content = f"Trade By {author_ping}"
                try:
                    sent_message = await trade_channel.send(content=msg_content, embed=embed, view=view)
                    
                    pub_msg_id = None
                    pub_ch_id = None
                    if public_channel:
                        try:
                            pub_msg = await public_channel.send(content=msg_content, embed=embed)
                            pub_msg_id = pub_msg.id
                            pub_ch_id = pub_msg.channel.id
                            logging.info(f"Sent public message: {pub_msg_id}")
                        except discord.Forbidden:
                            logging.error(f"Missing permissions to send messages to Public Trade channel: {PUBLIC_TRADE_CHANNEL_ID}")
                        except Exception as e:
                            logging.error(f"Error sending public message: {e}")

                    active_msg_id = None
                    active_ch_id = None
                    database.update_message_ids(trade_id, sent_message.id, sent_message.channel.id, pub_msg_id, pub_ch_id, active_msg_id, active_ch_id)
                    
                    # Map to a box
                    box_id = database.get_current_box_id(author_ping)
                    if box_id is None:
                        box_id = database.create_new_box_id(author_ping)
                    database.assign_trade_to_box(trade_id, box_id)
                    
                    # Update box
                    await update_box(box_id, bot)
                    
                    # Log to updates channel
                    action_msg = "Limit Entry Filled 🚀🚀" if initial_status == 'ACTIVE' else "Limit Placed ⏳"
                    bot.dispatch("trade_action", database.get_trade(trade_id), action_msg, author_name)
                except discord.Forbidden:
                    logging.error(f"Missing permissions to send messages to Trade channel: {TRADE_CHANNEL_ID}")
                except Exception as e:
                    logging.error(f"Error sending trade message: {e}")
            else:
                logging.error(f"Trade channel {TRADE_CHANNEL_ID} not found.")
        else:
            logging.info(f"Failed to parse trade signal from message: {message.content}")

    await bot.process_commands(message)

@tasks.loop(seconds=30)
async def price_check_loop():
    open_trades = database.get_open_trades() 
    for trade in open_trades:
        current_price = await binance_api.get_current_price(trade['pair'])
        if not current_price:
            continue
            
        direction = trade['direction']
        entry = trade['entry_price']
        tp = trade['tp_price']
        sl = trade['sl_price']
        status = trade['status']
        
        status_updated = False
        new_status = None
        action_msg = ""
        
        # Check limit entry if waiting
        if status == 'WAITING':
            if (direction == 'LONG' and current_price <= entry) or \
               (direction == 'SHORT' and current_price >= entry):
                new_status = 'ACTIVE'
                status_updated = True
                action_msg = f"Limit Entry Filled 🚀🚀"
                
        # Check TP/SL if active or BE
        elif status in ['ACTIVE', 'BE']:
            if direction == 'LONG':
                if current_price >= tp:
                    new_status = 'TP_HIT'
                    status_updated = True
                    action_msg = f"Take Profit Hit @ {current_price} ??"
                elif current_price <= sl:
                    new_status = 'SL_HIT'
                    status_updated = True
                    action_msg = f"Stop Loss Hit @ {current_price} ?"
            elif direction == 'SHORT':
                if current_price <= tp:
                    new_status = 'TP_HIT'
                    status_updated = True
                    action_msg = f"Take Profit Hit @ {current_price} ??"
                elif current_price >= sl:
                    new_status = 'SL_HIT'
                    status_updated = True
                    action_msg = f"Stop Loss Hit @ {current_price} ?"
                
        if status_updated:
            database.update_trade_status(trade['id'], new_status)
            updated_trade = database.get_trade(trade['id'])
            
            # Dispatch event to update logs and active list
            bot.dispatch("trade_action", updated_trade, action_msg, updated_trade['author_name'])
            
            # Update the original Discord message embed
            channel = bot.get_channel(updated_trade['channel_id'])
            if channel:
                try:
                    message = await channel.fetch_message(updated_trade['message_id'])
                    # If closed or hit stops, remove buttons. If active, keep buttons.
                    embed = ui_components.create_trade_embed(updated_trade)
                    if new_status in ['TP_HIT', 'SL_HIT']:
                        await message.edit(embed=embed, view=None)
                    else:
                        await message.edit(embed=embed)
                except discord.NotFound:
                    logging.warning(f"Message {updated_trade['message_id']} not found.")
                except Exception as e:
                    logging.error(f"Failed to update message: {e}")
                    
            # Update the public Discord message embed (never has buttons)
            if updated_trade.get('public_channel_id') and updated_trade.get('public_message_id'):
                pub_channel = bot.get_channel(updated_trade['public_channel_id'])
                if pub_channel:
                    try:
                        pub_msg = await pub_channel.fetch_message(updated_trade['public_message_id'])
                        embed = ui_components.create_trade_embed(updated_trade)
                        await pub_msg.edit(embed=embed)
                    except Exception as e:
                        pass

if __name__ == '__main__':
    if not TOKEN or TOKEN == 'your_discord_bot_token_here':
        print("Please configure your .env file with a valid DISCORD_TOKEN.")
    else:
        bot.run(TOKEN)

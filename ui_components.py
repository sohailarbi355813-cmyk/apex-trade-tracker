import discord
import database
import binance_api
import os

async def check_api_stops(trade_id, interaction: discord.Interaction):
    trade = database.get_trade(trade_id)
    if not trade or trade['status'] in ['CLOSED', 'TP_HIT', 'SL_HIT']: 
        return False
        
    current_price = await binance_api.get_current_price(trade['pair'])
    if not current_price: 
        return False
        
    direction = trade['direction']
    tp = trade['tp_price']
    sl = trade['sl_price']
    
    status_updated = False
    new_status = None
    action_msg = ""
    
    if direction == 'LONG':
        if current_price >= tp:
            new_status = 'TP_HIT'
            status_updated = True
        elif current_price <= sl:
            new_status = 'SL_HIT'
            status_updated = True
    elif direction == 'SHORT':
        if current_price <= tp:
            new_status = 'TP_HIT'
            status_updated = True
        elif current_price >= sl:
            new_status = 'SL_HIT'
            status_updated = True
            
    if status_updated:
        database.update_trade_status(trade_id, new_status)
        updated_trade = database.get_trade(trade_id)
        await update_message_embed(interaction.message, updated_trade, interaction.client)
        
        if new_status == 'TP_HIT':
            action_msg = f"Take Profit Hit @ {current_price} 🎯"
        else:
            action_msg = f"Stop Loss Hit @ {current_price} ❌"
            
        interaction.client.dispatch("trade_action", updated_trade, action_msg, interaction.user.display_name)
        await interaction.response.send_message(f"Action blocked: Trade already hit {new_status} at {current_price}!", ephemeral=True)
        return True
        
    return False


class UpdateModal(discord.ui.Modal):
    def __init__(self, trade_id, field_to_update, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trade_id = trade_id
        self.field_to_update = field_to_update
        
        self.new_price = discord.ui.TextInput(
            label=f'New {field_to_update.upper()} Price',
            style=discord.TextStyle.short,
            placeholder=f'Enter new {field_to_update.upper()} here...',
            required=True
        )
        self.add_item(self.new_price)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_value = float(self.new_price.value)
            
            # Use binance API to check if trade hit SL/TP before updating anything
            if await check_api_stops(self.trade_id, interaction):
                return
                
            action_msg = ""
            if self.field_to_update == 'tp':
                database.update_trade_tp(self.trade_id, new_value)
                action_msg = f"Updated TP -> {new_value} ⚙️"
            elif self.field_to_update == 'sl':
                database.update_trade_sl(self.trade_id, new_value)
                action_msg = f"StopLoss Updated to {new_value} ⚙️"
                
            updated_trade = database.get_trade(self.trade_id)
            await update_message_embed(interaction.message, updated_trade, interaction.client)
            
            # Dispatch event to update logs and active trades
            interaction.client.dispatch("trade_action", updated_trade, action_msg, interaction.user.display_name)
            
            await interaction.response.send_message(f"Successfully updated {self.field_to_update.upper()} to {new_value}.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid price format. Please enter a number.", ephemeral=True)

class TradeView(discord.ui.View):
    def __init__(self, trade_id):
        super().__init__(timeout=None)
        self.trade_id = trade_id

    # ROW 1
    @discord.ui.button(label="SL -> BE", style=discord.ButtonStyle.primary, row=0)
    async def set_be_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_api_stops(self.trade_id, interaction): return
        
        trade = database.get_trade(self.trade_id)
        if trade:
            database.update_trade_sl(self.trade_id, trade['entry_price'])
            database.update_trade_status(self.trade_id, 'BE')
            updated_trade = database.get_trade(self.trade_id)
            await update_message_embed(interaction.message, updated_trade, interaction.client)
            
            interaction.client.dispatch("trade_action", updated_trade, "⚖️ SL moved to BE", interaction.user.display_name)
            await interaction.response.send_message("Stop loss moved to break even.", ephemeral=True)
        else:
            await interaction.response.send_message("Trade not found.", ephemeral=True)

    @discord.ui.button(label="Update SL", style=discord.ButtonStyle.secondary, row=0)
    async def update_sl_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_api_stops(self.trade_id, interaction): return
        modal = UpdateModal(self.trade_id, 'sl', title="Update Stop Loss")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="TP Hit", style=discord.ButtonStyle.success, row=0)
    async def tp_hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        database.update_trade_status(self.trade_id, 'TP_HIT')
        updated_trade = database.get_trade(self.trade_id)
        await update_message_embed(interaction.message, updated_trade, interaction.client)
        
        interaction.client.dispatch("trade_action", updated_trade, "✅ Take Profit Hit (Manually)", interaction.user.display_name)
        await interaction.response.send_message("Marked as TP Hit manually.", ephemeral=True)

    @discord.ui.button(label="Update TP", style=discord.ButtonStyle.secondary, row=0)
    async def update_tp_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await check_api_stops(self.trade_id, interaction): return
        modal = UpdateModal(self.trade_id, 'tp', title="Update Take Profit")
        await interaction.response.send_modal(modal)

    # ROW 2
    @discord.ui.button(label="Close Trade", style=discord.ButtonStyle.danger, row=1)
    async def close_trade_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        database.update_trade_status(self.trade_id, 'CLOSED')
        updated_trade = database.get_trade(self.trade_id)
        await update_message_embed(interaction.message, updated_trade, interaction.client)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        
        # Don't log to updates channel
        interaction.client.dispatch("trade_action", updated_trade, "", interaction.user.display_name)
        
        # Log to Active Trades channel directly (removed, handled by dashboard logic in bot.py)
        await interaction.response.send_message("Trade cancelled and closed.", ephemeral=True)

    @discord.ui.button(label="Mark as Inactive", style=discord.ButtonStyle.secondary, row=1)
    async def mark_inactive_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        trade = database.get_trade(self.trade_id)
        if trade['status'] in ['WAITING', 'ACTIVE']:
            database.update_trade_status(self.trade_id, 'CANCELLED')
            updated_trade = database.get_trade(self.trade_id)
            await update_message_embed(interaction.message, updated_trade, interaction.client)
            
            # Send an empty action_msg so it doesn't log to Updates channel
            interaction.client.dispatch("trade_action", updated_trade, "", interaction.user.display_name)
            
            # (Dashboard update handled in bot.py)
            
            await interaction.response.send_message("Trade marked as Inactive (Cancelled).", ephemeral=True)
        else:
            await interaction.response.send_message("Trade is already closed or hit stops.", ephemeral=True)

async def update_message_embed(message: discord.Message, trade_data, bot=None):
    embed = create_trade_embed(trade_data)
    await message.edit(embed=embed)
    
    if bot and trade_data.get('public_message_id') and trade_data.get('public_channel_id'):
        pub_channel = bot.get_channel(trade_data['public_channel_id'])
        if pub_channel:
            try:
                pub_msg = await pub_channel.fetch_message(trade_data['public_message_id'])
                await pub_msg.edit(embed=embed) # No view/buttons!
            except Exception as e:
                pass

def create_trade_embed(trade_data):
    color = discord.Color.gold()
    if trade_data['status'] == 'CLOSED':
        color = discord.Color.dark_grey()
    elif trade_data['status'] == 'TP_HIT':
        color = discord.Color.green()
    elif trade_data['status'] == 'SL_HIT':
        color = discord.Color.red()
    elif trade_data['status'] == 'BE':
        color = discord.Color.blurple()
        
    embed = discord.Embed(color=color)
    if trade_data.get('author_name'):
        embed.set_author(name=trade_data['author_name'])
        
    try:
        risk = abs(trade_data['entry_price'] - trade_data['sl_price'])
        reward = abs(trade_data['tp_price'] - trade_data['entry_price'])
        rr = round(reward / risk, 2) if risk > 0 else 0.0
    except Exception:
        rr = "N/A"

    direction_emoji = "📈" if trade_data['direction'] == 'LONG' else "📉"
    
    description = (
        f"🟢{direction_emoji} **{trade_data['pair']} — {trade_data['direction']}**\n\n"
        f"💰 **Entry:** {trade_data['entry_price']}\n\n"
        f"🛡️ **SL:** {trade_data['sl_price']}\n\n"
        f"🎯 **TP:** {trade_data['tp_price']}\n\n"
        f"⚖️ ⚖️ **Reward @ TP:** {rr}\n\n"
    )
    
    if trade_data['status'] == 'WAITING':
        description += f"🕒 **Waiting for Trigger**\n\n"
        description += f"📊 **Status:** WAITING"
    elif trade_data['status'] == 'ACTIVE':
        description += f"🟢 **Trade Active**\n\n"
        description += f"📊 **Status:** ACTIVE"
    elif trade_data['status'] == 'BE':
        description += f"🔵 **Break Even**\n\n"
        description += f"📊 **Status:** BREAK EVEN"
    elif trade_data['status'] == 'TP_HIT':
        description += f"✅ **Take Profit Hit**\n\n"
        description += f"📊 **Status:** TP HIT"
    elif trade_data['status'] == 'SL_HIT':
        description += f"❌ **Stop Loss Hit**\n\n"
        description += f"📊 **Status:** SL HIT"
    elif trade_data['status'] == 'CLOSED':
        description += f"🛑 **Trade Closed**\n\n"
        description += f"📊 **Status:** CLOSED"
    elif trade_data['status'] == 'CANCELLED':
        description += f"🚫 **Trade Cancelled (Inactive)**\n\n"
        description += f"📊 **Status:** CANCELLED"

    embed.description = description
    return embed

def create_user_dashboard_embed(author_name, trades):
    embed = discord.Embed(color=discord.Color.dark_theme())
    embed.title = f"{author_name} — Active Trades"
    
    running_trades = [t for t in trades if t['status'] in ['ACTIVE', 'BE']]
    waiting_trades = [t for t in trades if t['status'] == 'WAITING']
    invalid_trades = [t for t in trades if t['status'] in ['CLOSED', 'CANCELLED', 'TP_HIT', 'SL_HIT']]
    
    desc = "🏃 **Running (Valid For Entry)**\n"
    if running_trades:
        for t in running_trades:
            desc += f"• **{t['direction']} {t['pair']}** | Entry: `{t['entry_price']}` | SL: `{t['sl_price']}` | TP: `{t['tp_price']}`\n\n"
    else:
        desc += "*No trades available*\n\n"
        
    desc += "🟢 **Valid Limits (Not Yet Filled)**\n"
    if waiting_trades:
        for t in waiting_trades:
            desc += f"• **{t['direction']} {t['pair']}** | Entry: `{t['entry_price']}` | SL: `{t['sl_price']}` | TP: `{t['tp_price']}`\n\n"
    else:
        desc += "*No trades available*\n\n"
        
    desc += "🔴 **Invalid (Running & Stops At Entry)**\n"
    if invalid_trades:
        # Only show the 5 most recent invalid trades
        for t in invalid_trades[:5]:
            desc += f"• **{t['direction']} {t['pair']}** | Entry: `{t['entry_price']}` | SL: `{t['sl_price']}` | TP: `{t['tp_price']}`\n\n"
    else:
        desc += "*No trades available*\n\n"
        
    embed.description = desc
    return embed


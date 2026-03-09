#!/usr/bin/env python3
import os
import json
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import anthropic

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8604374465:AAHYDUH3FuTati8LSq1ZhgRBjBLrSDZeO80")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

LEAGUE_RATES = {
    "argentina lpf": 0.33, "argentina primera b": 0.32,
    "morocco botola": 0.32, "algeria ligue pro": 0.31,
    "ethiopia premier": 0.30, "egypt premier": 0.30,
    "italy serie c": 0.30, "spain segunda": 0.30,
    "serbia prva liga": 0.29, "italy serie b": 0.29,
    "uruguay primera": 0.29, "colombia liga": 0.28,
    "tunisia ligue 1": 0.29, "greece super league": 0.27,
    "romania liga 2": 0.28, "rwanda premier": 0.28,
    "chile primera": 0.27, "other": 0.25
}

STORAGE_FILE = "drawiq_data.json"
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
def load_data():
    try:
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"bets": [], "users": {}}

def save_data(data):
    with open(STORAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def calculate_score(home, away, league, odds, stats):
    league_rate = LEAGUE_RATES.get(league.lower(), 0.25)
    
    if stats.get("isCupMatch"):
        return {
            "home": home, "away": away, "league": league, "odds": odds,
            "probability": 8, "verdict": "❌ CUP MATCH",
            "verdict_class": "low", "score": 0,
            "recommendation": "❌ REMOVE — Cup match. Teams must win!",
            "stats": stats, "factors": {}
        }
    
    score = 0
    score += min(league_rate / 0.33, 1) * 25
    score += (stats.get("h2hDraws", 2) / 5) * 25
    form_avg = (stats.get("homeDrawsLast10", 3) + stats.get("awayDrawsLast10", 3)) / 20
    score += min(form_avg * 60, 20)
    
    avg_goals = (stats.get("homeGoalsPerGame", 1.2) + stats.get("awayGoalsPerGame", 1.2)) / 2
    if avg_goals < 0.8: score += 15
    elif avg_goals < 1.0: score += 13
    elif avg_goals < 1.3: score += 11
    elif avg_goals < 1.6: score += 8
    elif avg_goals < 2.0: score += 5
    else: score += 2
    
    if 2.40 <= odds <= 3.20: score += 10
    elif 3.20 < odds <= 3.50: score += 6
    elif odds > 3.50: score += 3
    else: score += 5
    
    if stats.get("isDerby"): score = min(score + 5, 100)
    
    probability = min(round(score * 0.70 + league_rate * 14), 68)
    
    if probability >= 45:
        verdict = "✅ HIGH CONFIDENCE"
        verdict_class = "high"
        rec = "✅ BACK THE DRAW — Strong signals. Include in your slip!"
    elif probability >= 32:
        verdict = "⚠️ MODERATE"
        verdict_class = "mid"
        rec = "⚠️ CAUTION — Some signals but not strong enough."
    else:
        verdict = "❌ LOW CONFIDENCE"
        verdict_class = "low"
        rec = "❌ SKIP THIS MATCH — Remove from slip."
    
    return {
        "home": home, "away": away, "league": league, "odds": odds,
        "probability": probability, "verdict": verdict,
        "verdict_class": verdict_class, "score": round(score),
        "recommendation": rec, "stats": stats,
        "factors": {
            "league_rate": round(league_rate * 100),
            "h2h_draws": f"{stats.get('h2hDraws','?')}/5",
            "home_draws": stats.get("homeDrawsLast10", "?"),
            "away_draws": stats.get("awayDrawsLast10", "?"),
            "avg_goals": round(avg_goals, 1),
            "home_form": stats.get("homeLastFive", "N/A"),
            "away_form": stats.get("awayLastFive", "N/A"),
            "key_context": stats.get("keyContext", ""),
            "confidence": stats.get("dataConfidence", "medium")
        }
      }
  async def analyze_match_with_ai(home, away, league, odds):
    league_rate = LEAGUE_RATES.get(league.lower(), 0.25)
    
    if not ANTHROPIC_API_KEY:
        return calculate_score(home, away, league, odds, {
            "h2hDraws": 2, "homeDrawsLast10": 3, "awayDrawsLast10": 3,
            "homeGoalsPerGame": 1.2, "awayGoalsPerGame": 1.2,
            "homeLastFive": "N/A", "awayLastFive": "N/A",
            "isCupMatch": False, "isDerby": False,
            "keyContext": "Configure ANTHROPIC_API_KEY for full AI analysis.",
            "dataConfidence": "low"
        })
    
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""You are DrawIQ, a football draw prediction AI. Analyze this match.

MATCH: {home} vs {away}
LEAGUE: {league} (draw rate: {round(league_rate*100)}%)
DRAW ODDS: {odds}

Return ONLY a JSON object, no explanation:
{{
  "h2hDraws": <0-5>,
  "h2hTotal": 5,
  "homeDrawsLast10": <0-10>,
  "awayDrawsLast10": <0-10>,
  "homeGoalsPerGame": <decimal>,
  "awayGoalsPerGame": <decimal>,
  "homeLastFive": "<W-D-L-D-W>",
  "awayLastFive": "<W-D-L-D-W>",
  "isCupMatch": <true/false>,
  "isDerby": <true/false>,
  "keyContext": "<one sentence key factor>",
  "dataConfidence": "<high/medium/low>"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text
        import re
        match_json = re.search(r'\{[\s\S]*\}', raw)
        if match_json:
            stats = json.loads(match_json.group())
            return calculate_score(home, away, league, odds, stats)
    except Exception as e:
        logger.error(f"AI error: {e}")
    
    return calculate_score(home, away, league, odds, {
        "h2hDraws": 2, "homeDrawsLast10": 3, "awayDrawsLast10": 3,
        "homeGoalsPerGame": 1.2, "awayGoalsPerGame": 1.2,
        "homeLastFive": "N/A", "awayLastFive": "N/A",
        "isCupMatch": False, "isDerby": False,
        "keyContext": "Limited data.", "dataConfidence": "low"
    })

def format_result(result):
    p = result["probability"]
    emoji = "🟢" if result["verdict_class"] == "high" else "🟡" if result["verdict_class"] == "mid" else "🔴"
    bar_filled = round(p / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    f = result.get("factors", {})
    stats = result.get("stats", {})
    
    msg = f"""{emoji} *{result['home']} vs {result['away']}*
📋 {result['league']} | @{result['odds']}

*DRAW PROBABILITY: {p}%*
`{bar}`

*{result['verdict']}*

📊 *Factor Breakdown:*
• League Draw Rate: {f.get('league_rate','?')}%
• H2H Draws: {f.get('h2h_draws','?')} last 5
• Home Form: {f.get('home_form','N/A')}
• Away Form: {f.get('away_form','N/A')}
• Avg Goals/Game: {f.get('avg_goals','?')}
• Home Draws L10: {f.get('home_draws','?')}
• Away Draws L10: {f.get('away_draws','?')}
"""
    if stats.get("isDerby"):
        msg += "• 🔥 Derby match!\n"
    if f.get("key_context"):
        msg += f"\n💡 *Intel:* {f['key_context']}\n"
    msg += f"\n{result['recommendation']}"
    if f.get("confidence") == "low":
        msg += "\n\n⚠️ _Limited data — verify manually_"
    return msg
  async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    data = load_data()
    data["users"][str(chat_id)] = {"name": user.first_name, "joined": datetime.now().isoformat()}
    save_data(data)
    keyboard = [
        [InlineKeyboardButton("⚡ How to Analyze", callback_data="help_analyze")],
        [InlineKeyboardButton("📋 My Bets", callback_data="my_bets"),
         InlineKeyboardButton("📊 Stats", callback_data="my_stats")],
        [InlineKeyboardButton("📖 Rules", callback_data="rules")]
    ]
    await update.message.reply_text(
        f"👋 Welcome to *DrawIQ Bot*, {user.first_name}!\n\n"
        "🤖 Your AI-powered draw prediction assistant!\n\n"
        "*Commands:*\n"
        "/analyze - Analyze a match\n"
        "/picks - Draw betting advice\n"
        "/bet - Record a bet\n"
        "/result - Record result\n"
        "/mybets - Your bet history\n"
        "/stats - Win/loss stats\n"
        "/rules - Betting rules\n"
        "/help - Help guide\n\n"
        "Let's find some draws! ⚽",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *DrawIQ Help Guide*\n\n"
        "*Analyze a match:*\n"
        "`/analyze Home vs Away, League, Odds`\n\n"
        "*Example:*\n"
        "`/analyze Getafe vs Betis, La Liga, 2.98`\n\n"
        "*Record a bet:*\n"
        "`/bet Home vs Away, odds, stake`\n\n"
        "*Record result:*\n"
        "`/result Home vs Away, win/loss`\n\n"
        "⚽ Good luck!", parse_mode="Markdown"
    )

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚡ *Format:*\n`/analyze Home vs Away, League, Odds`\n\n"
            "*Example:*\n`/analyze Getafe vs Betis, La Liga, 2.98`",
            parse_mode="Markdown"
        )
        return
    text = " ".join(context.args)
    try:
        parts = text.split(",")
        league = parts[1].strip()
        odds = float(parts[2].strip())
        home = parts[0][:parts[0].lower().index(" vs ")].strip()
        away = parts[0][parts[0].lower().index(" vs ") + 4:].strip()
    except:
        await update.message.reply_text(
            "❌ Wrong format. Use:\n`/analyze Home vs Away, League, Odds`",
            parse_mode="Markdown"
        )
        return
    msg = await update.message.reply_text(
        f"🔍 Analyzing *{home} vs {away}*...\n⏳ Please wait...",
        parse_mode="Markdown"
    )
    result = await analyze_match_with_ai(home, away, league, odds)
    keyboard = [[InlineKeyboardButton("✅ Record Bet", callback_data=f"addbet"),
                 InlineKeyboardButton("🔄 New Analysis", callback_data="help_analyze")]]
    await msg.edit_text(format_result(result), parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard))

async def picks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏆 *Top Draw Leagues Today:*\n\n"
        "🇦🇷 Argentina LPF (~33%)\n"
        "🇲🇦 Morocco Botola (~32%)\n"
        "🇩🇿 Algeria Ligue Pro (~31%)\n"
        "🇮🇹 Italy Serie B/C (~29-30%)\n"
        "🇷🇸 Serbia Prva Liga (~29%)\n"
        "🇺🇾 Uruguay Primera (~29%)\n\n"
        "❌ *Always Avoid:*\n"
        "Cup/knockout matches!\n"
        "Odds above 3.50!\n"
        "U21/reserve teams!\n\n"
        "Send matches using:\n"
        "`/analyze Home vs Away, League, Odds`",
        parse_mode="Markdown"
    )

async def bet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📝 *Format:*\n`/bet Home vs Away, odds, stake`\n\n"
            "*Example:*\n`/bet Getafe vs Betis, 2.98, 100`",
            parse_mode="Markdown"
        )
        return
    text = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    try:
        parts = text.split(",")
        match = parts[0].strip()
        odds = float(parts[1].strip())
        stake = float(parts[2].strip())
        data = load_data()
        bet = {
            "id": len(data["bets"]) + 1,
            "user": chat_id, "match": match,
            "odds": odds, "stake": stake,
            "status": "pending",
            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "potential_win": round(odds * stake, 2)
        }
        data["bets"].append(bet)
        save_data(data)
        await update.message.reply_text(
            f"✅ *Bet Recorded!*\n\n⚽ {match}\n💰 Odds: {odds}\n"
            f"💵 Stake: ₦{stake}\n🎯 Potential Win: ₦{bet['potential_win']}\n\n"
            f"Good luck! 🍀",
            parse_mode="Markdown"
        )
    except:
        await update.message.reply_text("❌ Format: `/bet Home vs Away, odds, stake`", parse_mode="Markdown")

async def result_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📊 *Format:*\n`/result Match, win/loss`",
            parse_mode="Markdown"
        )
        return
    text = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    try:
        parts = text.rsplit(",", 1)
        match = parts[0].strip()
        outcome = parts[1].strip().lower()
        is_win = outcome in ["win", "won"]
        data = load_data()
        for bet in reversed(data["bets"]):
            if bet["user"] == chat_id and match.lower() in bet["match"].lower() and bet["status"] == "pending":
                bet["status"] = "won" if is_win else "lost"
                bet["profit"] = round(bet["potential_win"] - bet["stake"], 2) if is_win else -bet["stake"]
                save_data(data)
                emoji = "🎉" if is_win else "😓"
                profit_text = f"+₦{bet['profit']}" if is_win else f"-₦{bet['stake']}"
                await update.message.reply_text(
                    f"{emoji} *Result Recorded!*\n\n⚽ {match}\n"
                    f"{'✅ WON' if is_win else '❌ LOST'}\n💰 {profit_text}",
                    parse_mode="Markdown"
                )
                return
        await update.message.reply_text("❌ Bet not found. Record it first with /bet", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Format: `/result Match, win/loss`", parse_mode="Markdown")

async def mybets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    user_bets = [b for b in data["bets"] if b["user"] == chat_id]
    if not user_bets:
        await update.message.reply_text("📋 No bets yet! Use /bet to record one.", parse_mode="Markdown")
        return
    msg = "📋 *Your Recent Bets:*\n\n"
    for bet in user_bets[-10:][::-1]:
        status_emoji = "✅" if bet["status"] == "won" else "❌" if bet["status"] == "lost" else "⏳"
        msg += f"{status_emoji} {bet['match']} @{bet['odds']}\n"
        msg += f"   ₦{bet['stake']} → ₦{bet['potential_win']} | {bet['date']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    data = load_data()
    settled = [b for b in data["bets"] if b["user"] == chat_id and b["status"] in ["won", "lost"]]
    if not settled:
        await update.message.reply_text("📊 No settled bets yet!", parse_mode="Markdown")
        return
    wins = len([b for b in settled if b["status"] == "won"])
    losses = len(settled) - wins
    total_stake = sum(b["stake"] for b in settled)
    total_profit = sum(b.get("profit", 0) for b in settled)
    win_rate = round((wins / len(settled)) * 100)
    emoji = "📈" if total_profit > 0 else "📉"
    await update.message.reply_text(
        f"📊 *Your DrawIQ Statistics*\n\n"
        f"🎯 Total Bets: {len(settled)}\n✅ Wins: {wins}\n❌ Losses: {losses}\n"
        f"📈 Win Rate: {win_rate}%\n\n"
        f"💵 Total Staked: ₦{total_stake}\n{emoji} Net Profit: ₦{round(total_profit, 2)}\n\n"
        f"{'🔥 Keep it up!' if total_profit > 0 else '💪 Stay disciplined!'}",
        parse_mode="Markdown"
    )

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *DrawIQ Betting Rules*\n\n"
        "1️⃣ Only back HIGH confidence (45%+)\n"
        "2️⃣ Max 5 legs per slip\n"
        "3️⃣ No cup/knockout matches\n"
        "4️⃣ Best odds: 2.40 – 3.20\n"
        "5️⃣ H2H history is king\n"
        "6️⃣ Take good cashouts (20x+)\n"
        "7️⃣ Bet responsibly 🙏",
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "help_analyze":
        await query.message.reply_text(
            "⚡ *Format:*\n`/analyze Home vs Away, League, Odds`\n\n"
            "`/analyze Getafe vs Betis, La Liga, 2.98`",
            parse_mode="Markdown"
        )
    elif query.data == "my_bets":
        await mybets_command(update, context)
    elif query.data == "my_stats":
        await stats_command(update, context)
    elif query.data == "rules":
        await rules_command(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if "vs" in text and any(char.isdigit() for char in text):
        await update.message.reply_text(
            "💡 To analyze a match use:\n"
            "`/analyze Home vs Away, League, Odds`\n\n"
            "Example:\n`/analyze Getafe vs Betis, La Liga, 2.98`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Type /help to see all commands! ⚽", parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("picks", picks_command))
    app.add_handler(CommandHandler("bet", bet_command))
    app.add_handler(CommandHandler("result", result_command))
    app.add_handler(CommandHandler("mybets", mybets_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("DrawIQ Bot started! 🤖⚽")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

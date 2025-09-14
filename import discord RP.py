import os
import io
import time
import json
import random
import asyncio
import sqlite3
from zoneinfo import ZoneInfo
from typing import List, Optional, Tuple

from flask import Flask
import threading

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

from discord import ui, ButtonStyle, Embed
from datetime import datetime, timedelta

# Flask 웹서버 (Keep Alive용)
app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


LEAVE_CHANNEL_ID   = 1389576208269709422
WELCOME_CHANNEL_ID = 1389575857949114488
TICKET_CATEGORY_ID = 1396783155331207178
TICKET_ROLE_ID     = 1397767970461192302

LEAVE_IMAGE_URL = "https://cdn.discordapp.com/attachments/1400443921531928678/1414186240823263425/IMG_8823-removebg-preview.png?ex=68bea712&is=68bd5592&hm=ae9862e6f849b6c58f7305581a4e7c3902213e27fa70daab766ca2ff1aff5c26&"
WARNING_ROLE_NAME = "⚠️ 경고"

KST = ZoneInfo("Asia/Seoul")


# Database files
MAIN_DB_FILE = "bot_records.db"
MATH_DB_FILE = "math_scores.db"

def init_main_db():
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS typing_records (
        user_id TEXT PRIMARY KEY,
        best_time REAL
    )
    """)
   
    cur.execute("""
    CREATE TABLE IF NOT EXISTS warnings (
        user_id TEXT PRIMARY KEY,
        count INTEGER
    )
    """)
    conn.commit()
    conn.close()

def init_math_db():
    conn = sqlite3.connect(MATH_DB_FILE)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS user_scores (
        user_id TEXT PRIMARY KEY,
        score INTEGER,
        correct_count INTEGER,
        total_count INTEGER,
        max_consecutive INTEGER,
        consecutive INTEGER
    )
    ''')
    conn.commit()
    conn.close()


def get_warnings(user_id: str) -> int:
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT count FROM warnings WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def add_warning(user_id: str, amount: int = 1) -> int:
    new_count = get_warnings(user_id) + amount
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    cur.execute("REPLACE INTO warnings (user_id, count) VALUES (?,?)", (user_id, new_count))
    conn.commit()
    conn.close()
    return new_count

def remove_warning(user_id: str, amount: int = 1) -> int:
    new_count = max(0, get_warnings(user_id) - amount)
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    cur.execute("REPLACE INTO warnings (user_id, count) VALUES (?,?)", (user_id, new_count))
    conn.commit()
    conn.close()
    return new_count

def get_best_time(user_id: str) -> Optional[float]:
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT best_time FROM typing_records WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def update_best_time(user_id: str, new_time: float):
    best = get_best_time(user_id)
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    if best is None or new_time < best:
        cur.execute("REPLACE INTO typing_records (user_id, best_time) VALUES (?,?)", (user_id, new_time))
    conn.commit()
    conn.close()

def get_ranking(offset: int = 0, limit: int = 10) -> List[Tuple[str, float]]:
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT user_id, best_time FROM typing_records ORDER BY best_time ASC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def get_ranking_count() -> int:
    conn = sqlite3.connect(MAIN_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM typing_records")
    count = cur.fetchone()[0]
    conn.close()
    return count


# Math game functions
def get_math_score(user_id):
    conn = sqlite3.connect(MATH_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_scores WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(zip(['user_id','score','correct_count','total_count','max_consecutive','consecutive'], row))
    return {'user_id': user_id, 'score': 0, 'correct_count': 0, 'total_count': 0, 'max_consecutive': 0, 'consecutive': 0}

def update_math_score(user_id, earned, correct):
    data = get_math_score(user_id)
    data['total_count'] += 1
    if correct:
        data['score'] += earned
        data['correct_count'] += 1
        data['consecutive'] += 1
        if data['consecutive'] > data['max_consecutive']:
            data['max_consecutive'] = data['consecutive']
    else:
        data['consecutive'] = 0
    
    conn = sqlite3.connect(MATH_DB_FILE)
    cur = conn.cursor()
    cur.execute('''
    INSERT OR REPLACE INTO user_scores(user_id,score,correct_count,total_count,max_consecutive,consecutive)
    VALUES (?,?,?,?,?,?)
    ''', (user_id, data['score'], data['correct_count'], data['total_count'], data['max_consecutive'], data['consecutive']))
    conn.commit()
    conn.close()
    return data


# 활성 챌린지를 저장할 딕셔너리
active_challenges = {}

# 🎬 영상 파일 고정 설정 (관리자가 업로드해도 안바뀜)
VIDEO_FILE_PATH = "challenge_video.mp4"  # 항상 이 파일만 사용
VIDEO_TITLE = "고정 챌린지 영상"



@bot.event
async def on_member_join(member: discord.Member):
    embed = discord.Embed(
        title="👋 새로운 유저 입장!",
        description=f"{member.mention} 님이 서버에 들어왔습니다!",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="디스코드 가입일",
        value=member.created_at.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S"),
        inline=True,
    )
    embed.add_field(
        name="서버 가입일",
        value=(member.joined_at or discord.utils.utcnow()).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S"),
        inline=True,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url=LEAVE_IMAGE_URL)
    ch = bot.get_channel(WELCOME_CHANNEL_ID)
    if ch:
        await ch.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    ch = bot.get_channel(LEAVE_CHANNEL_ID)
    if ch:
        embed = discord.Embed(
            title="😢 유저 퇴장",
            description=f"{member.name} 님이 서버를 떠났습니다.",
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url=LEAVE_IMAGE_URL)
        await ch.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    # 활성 챌린지가 있는 채널에서 답변 확인
    if message.channel.id in active_challenges:
        challenge_data = active_challenges[message.channel.id]
        challenge = challenge_data['challenge']
        
        answered = await challenge.check_answer(message)
        if answered:
            return
    
    # 수학 문제 답변 확인
    if message.channel.id in active_math_problems:
        problem_data = active_math_problems[message.channel.id]
        if message.author.id == problem_data['user_id']:
            try:
                user_answer = int(message.content.strip())
                correct = user_answer == problem_data['problem']['answer']
                earned = problem_score(problem_data['problem']) if correct else 0
                data = update_math_score(str(message.author.id), earned, correct)
                grade = get_grade(data['score'])
                
                if correct:
                    await assign_role(message.author, grade)
                    embed = discord.Embed(title='🎉 정답!', color=discord.Color.green())
                    embed.add_field(name='정답', value=str(problem_data['problem']['answer']), inline=True)
                    embed.add_field(name='🏆 획득', value=f"+{earned}점", inline=True)
                    embed.add_field(name='📊 현재 점수', value=f"{data['score']}점", inline=True)
                    embed.add_field(name='⭐ 등급', value=grade, inline=True)
                    embed.add_field(name='🔥 연속 정답', value=data['consecutive'], inline=True)
                else:
                    embed = discord.Embed(title='❌ 오답!', color=discord.Color.red())
                    embed.add_field(name='정답', value=str(problem_data['problem']['answer']), inline=True)
                    embed.add_field(name='선택한 답', value=str(user_answer), inline=True)
                    embed.add_field(name='📊 현재 점수', value=f"{data['score']}점", inline=True)
                    embed.add_field(name='⭐ 등급', value=grade, inline=True)
                
                await message.channel.send(embed=embed)
                del active_math_problems[message.channel.id]
            except ValueError:
                pass
    
    await bot.process_commands(message)

@bot.hybrid_command(name="ping", description="봇의 핑(지연시간)을 확인합니다.")
async def ping(ctx: commands.Context):
    await ctx.send(f"🏓 Pong! {round(bot.latency * 1000)}ms")

@bot.hybrid_command(name="ban", description="유저를 서버에서 차단합니다.")
@commands.has_permissions(administrator=True)
async def ban(ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None):
    await member.ban(reason=reason)
    await ctx.send(f"{member.name} 님이 밴 되었습니다.")

@bot.hybrid_command(name="kick", description="유저를 서버에서 추방합니다.")
@commands.has_permissions(administrator=True)
async def kick(ctx: commands.Context, member: discord.Member, *, reason: Optional[str] = None):
    await member.kick(reason=reason)
    await ctx.send(f"{member.name} 님이 킥 되었습니다.")

@bot.tree.command(name="say", description="봇이 메시지를 보냅니다 (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def say(interaction: discord.Interaction, message: str, image_url: Optional[str] = None):
    if image_url:
        embed = discord.Embed(description=message)
        embed.set_image(url=image_url)
        await interaction.channel.send(embed=embed)
    else:
        await interaction.channel.send(message)
    await interaction.response.send_message("✅ 메시지를 보냈습니다!", ephemeral=True)

@bot.hybrid_command(name="ticket", description="티켓을 생성합니다.")
async def ticket(ctx: commands.Context):
    category = bot.get_channel(TICKET_CATEGORY_ID)
    if not category:
        return await ctx.send("❌ 티켓 카테고리를 찾을 수 없습니다.")
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        ctx.guild.get_role(TICKET_ROLE_ID): discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    channel = await ctx.guild.create_text_channel(
        name=f"ticket-{ctx.author.name}",
        category=category,
        overwrites=overwrites,
    )
    await ctx.send(f"✅ 티켓 생성됨: {channel.mention}")
    await channel.send(
        embed=discord.Embed(
            title="🎫 티켓 생성됨",
            description="궁금한 점을 자유롭게 질문해주세요!",
            color=discord.Color.blue(),
        )
    )

@bot.hybrid_command(name="dice", description="주사위를 굴립니다.")
async def dice(ctx: commands.Context, max_number: int = 6):
    await ctx.send(f"🎲 결과: **{random.randint(1, max_number)}** (1~{max_number})")

@bot.hybrid_command(name="coin", description="동전을 던집니다.")
async def coin(ctx: commands.Context):
    await ctx.send(f"🪙 결과: **{random.choice(['앞면','뒷면'])}**")


@bot.tree.command(name="warn-warn", description="유저에게 경고를 부여합니다 (5회 누적 시 자동 킥)")
@app_commands.describe(user="경고를 줄 유저", reason="사유 (선택)")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str = "사유 없음"):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ 관리자만 사용 가능합니다.", ephemeral=True)
    uid = str(user.id)
    count = add_warning(uid, 1)

    role = discord.utils.get(interaction.guild.roles, name=WARNING_ROLE_NAME)
    if not role:
        role = await interaction.guild.create_role(name=WARNING_ROLE_NAME, colour=discord.Colour.orange())

    if count >= 3 and role not in user.roles:
        await user.add_roles(role)
        await interaction.channel.send(f"⚠️ {user.mention} 경고 역할 부여됨.")

    if count >= 5:
        await user.kick(reason="경고 5회 누적")
        await interaction.channel.send(f"⛔ {user.mention} 경고 5회 누적으로 추방됨.")
    else:
        await interaction.response.send_message(f"⚠️ {user.mention} 경고 {count}회 (사유: {reason})")

@bot.tree.command(name="warn-remove", description="유저의 경고를 취소합니다")
@app_commands.describe(user="경고를 줄일 유저", amount="차감할 횟수 (기본 1)")
async def warn_remove(interaction: discord.Interaction, user: discord.Member, amount: int = 1):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ 관리자만 사용 가능합니다.", ephemeral=True)
    uid = str(user.id)
    count = remove_warning(uid, amount)
    await interaction.response.send_message(f"✅ {user.mention} 경고 {amount}회 취소됨 (현재 {count}회)")

@bot.tree.command(name="warnings", description="유저의 경고 수를 확인합니다")
@app_commands.describe(user="확인할 유저")
async def warnings_cmd(interaction: discord.Interaction, user: discord.Member):
    cnt = get_warnings(str(user.id))
    await interaction.response.send_message(f"📋 {user.mention} 경고: **{cnt}회**")

RPS_CHOICES = ("가위", "바위", "보")

def rps_winner(a: str, b: str) -> int:
    if a == b:
        return 0
    wins = {("가위", "보"), ("바위", "가위"), ("보", "바위")}
    return 1 if (a, b) in wins else -1

class ReplayButtons(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=60)
        self.p1 = p1
        self.p2 = p2

    @discord.ui.button(label="🔄 재대결", style=discord.ButtonStyle.success)
    async def replay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [self.p1, self.p2]:
            return await interaction.response.send_message("이 대결의 참가자가 아닙니다.", ephemeral=True)
        view = RPSButtons(self.p1, self.p2)
        msg = await interaction.channel.send(
            f"🎮 {self.p1.mention} vs {self.p2.mention} — 다시 한 번!", view=view
        )
        view.message = msg
        await interaction.response.defer()

    @discord.ui.button(label="🛑 종료", style=discord.ButtonStyle.danger)
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [self.p1, self.p2]:
            return await interaction.response.send_message("이 대결의 참가자가 아닙니다.", ephemeral=True)
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)

class RPSButtons(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member):
        super().__init__(timeout=60)
        self.p1 = p1
        self.p2 = p2
        self.choices = {}
        self.message: Optional[discord.Message] = None

    async def _choose(self, interaction: discord.Interaction, pick: str):
        if interaction.user not in [self.p1, self.p2]:
            return await interaction.response.send_message("이 대결 참가자가 아닙니다.", ephemeral=True)
        self.choices[interaction.user] = pick
        await interaction.response.send_message(f"선택 완료: **{pick}**", ephemeral=True)

        if len(self.choices) == 2:
            a = self.choices[self.p1]
            b = self.choices[self.p2]
            result = rps_winner(a, b)
            if result == 0:
                msg = f"🟡 {self.p1.display_name}({a}) vs {self.p2.display_name}({b}) → **무승부!**"
            elif result > 0:
                msg = f"🟡 {self.p1.display_name}({a}) vs {self.p2.display_name}({b}) → **{self.p1.display_name} 승리!**"
            else:
                msg = f"🟡 {self.p1.display_name}({a}) vs {self.p2.display_name}({b}) → **{self.p2.display_name} 승리!**"

            for c in self.children:
                c.disabled = True
            await self.message.edit(view=self)
            await self.message.channel.send(msg, view=ReplayButtons(self.p1, self.p2))

    @discord.ui.button(label="✌ 가위", style=discord.ButtonStyle.primary)
    async def s(self, i: discord.Interaction, b: discord.ui.Button):
        await self._choose(i, "가위")

    @discord.ui.button(label="✊ 바위", style=discord.ButtonStyle.primary)
    async def r(self, i: discord.Interaction, b: discord.ui.Button):
        await self._choose(i, "바위")

    @discord.ui.button(label="🖐 보", style=discord.ButtonStyle.primary)
    async def p(self, i: discord.Interaction, b: discord.ui.Button):
        await self._choose(i, "보")

class AcceptDeclineRPS(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent

    @discord.ui.button(label="✅ 수락", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            return await interaction.response.send_message("대결 대상만 수락할 수 있습니다.", ephemeral=True)
        view = RPSButtons(self.challenger, self.opponent)
        msg = await interaction.channel.send(
            f"🎮 {self.challenger.mention} vs {self.opponent.mention} — 선택하세요!", view=view
        )
        view.message = msg
        await interaction.response.edit_message(content="대결이 시작되었습니다!", view=None)

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            return await interaction.response.send_message("대결 대상만 거절할 수 있습니다.", ephemeral=True)
        await interaction.response.edit_message(content="대결이 거절되었습니다.", view=None)

@bot.tree.command(name="rock-paper-scissors", description="가위바위보 대결을 신청합니다.")
@app_commands.describe(user="대결을 신청할 유저")
async def rps(interaction: discord.Interaction, user: discord.Member):
    if user == interaction.user:
        return await interaction.response.send_message("자기 자신과는 대결할 수 없어요!", ephemeral=True)
    view = AcceptDeclineRPS(interaction.user, user)
    await interaction.response.send_message(
        f"🎮 {interaction.user.mention} → {user.mention} 가위바위보 대결 신청!", view=view
    )


# ================= 타자 게임 =================
TYPING_TEXTS = [
    "무궁화 삼천리 화려 강산 대한 사람, 대한으로 길이 보전하세.",
    "남산 위에 저 소나무, 철갑을 두른 듯 바람 서리 불변함은 우리 기상일세.",
    "가을 하늘 공활한데 높고 구름 없이 밝은 달은 우리 가슴 일편단심일세.",
    "이 기상과 이 맘으로 충성을 다하여 괴로우나 즐거우나 나라 사랑하세.",
    "빠르게 정확하게 입력하는 연습은 생각보다 재미있어요!",
    "하루에 한 번씩 도전하면 기록이 눈에 뜨게 좋아집니다."
]

def _pick_font() -> ImageFont.FreeTypeFont:
    candidates = [
        "C:\\Windows\\Fonts\\malgun.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, 32)
            except:
                pass
    return ImageFont.load_default()

def text_to_image(text: str) -> discord.File:
    font = _pick_font()
    w = max(800, 28 * len(text))
    img = Image.new("RGB", (min(w, 1600), 120), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), text, font=font, fill="black")
    bio = io.BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return discord.File(bio, filename="typing.png")

async def _typing_round_send(interaction: discord.Interaction, text: str):
    file = text_to_image(text)
    embed = discord.Embed(
        title="⌨️ 타자 속도 게임",
        description="🕔 28초 안에 아래 문장을 **정확히** 입력하세요!",
        color=discord.Color.blue(),
    )
    embed.set_image(url="attachment://typing.png")
    await interaction.followup.send(embed=embed, file=file)

async def _wait_correct_message(channel: discord.abc.Messageable, players: List[discord.Member], target: str):
    def check(m: discord.Message):
        return (m.author in players) and (m.channel == channel)
    t0 = time.time()
    try:
        msg = await bot.wait_for("message", timeout=28.0, check=check)
    except asyncio.TimeoutError:
        return None, None
    if msg.content == target:
        return msg.author, round(time.time() - t0, 2)
    return "wrong", None

class AcceptDeclineTyping(discord.ui.View):
    def __init__(self, challenger: discord.Member, opponent: discord.Member):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent

    @discord.ui.button(label="✅ 수락(대결 시작)", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            return await interaction.response.send_message("대결 대상만 수락할 수 있습니다.", ephemeral=True)
        await interaction.response.edit_message(content="대결을 시작합니다!", view=None)
        text = random.choice(TYPING_TEXTS)
        await interaction.followup.send("문장을 곧 전송합니다…")
        await _typing_round_send(interaction, text)
        winner, elapsed = await _wait_correct_message(interaction.channel, [self.challenger, self.opponent], text)
        if winner is None:
            return await interaction.followup.send("⏰ 시간 초과! 아무도 성공하지 못했습니다.")
        if winner == "wrong":
            return await interaction.followup.send("❌ 오답이 입력되었습니다. 다시 시도하세요.")
        uid = str(winner.id)
        best = get_best_time(uid)
        if best is None or elapsed < best:
            update_best_time(uid, elapsed)
            await interaction.followup.send(f"🎉 {winner.mention} 승리! **{elapsed}초** (개인 최고 기록 갱신)")
        else:
            await interaction.followup.send(f"✅ {winner.mention} 승리! **{elapsed}초** (개인 최고: {best}초)")

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            return await interaction.response.send_message("대결 대상만 거절할 수 있습니다.", ephemeral=True)
        await interaction.response.edit_message(content="대결이 거절되었습니다.", view=None)

@bot.tree.command(name="typinggame", description="타자게임: 혼자 또는 유저를 지목해 대결")
@app_commands.describe(opponent="대결할 유저 (생략 시 혼자 모드)")
async def typinggame(interaction: discord.Interaction, opponent: Optional[discord.Member] = None):
    await interaction.response.send_message("⌨️ 준비 중…", ephemeral=True)

    if opponent and opponent != interaction.user:
        view = AcceptDeclineTyping(interaction.user, opponent)
        await interaction.followup.send(
            f"⌨️ {interaction.user.mention} → {opponent.mention} 타자 대결 신청!", view=view
        )
        return

    # 혼자 모드
    text = random.choice(TYPING_TEXTS)
    await _typing_round_send(interaction, text)
    who, elapsed = await _wait_correct_message(interaction.channel, [interaction.user], text)
    if who is None:
        return await interaction.followup.send("⏰ 시간 초과! 다시 시도하세요.")
    if who == "wrong":
        return await interaction.followup.send("❌ 오답이에요. 다시 시도!")
    uid = str(interaction.user.id)
    best = get_best_time(uid)
    if best is None or elapsed < best:
        update_best_time(uid, elapsed)
        await interaction.followup.send(f"🎉 {interaction.user.mention} 성공! **{elapsed}초** (개인 최고 기록 갱신)")
    else:
        await interaction.followup.send(f"✅ {interaction.user.mention} 성공! **{elapsed}초** (개인 최고: {best}초)")


class RankPager(discord.ui.View):
    def __init__(self, page: int = 0, page_size: int = 10):
        super().__init__(timeout=120)
        self.page = page
        self.page_size = page_size
        self.total = get_ranking_count()

    def _make_embed(self):
        offset = self.page * self.page_size
        rows = get_ranking(offset=offset, limit=self.page_size)
        embed = discord.Embed(title="🏆 타자게임 랭킹", color=discord.Color.gold())
        if not rows:
            embed.description = "기록이 없습니다."
            return embed
        for idx, (uid, score) in enumerate(rows, start=offset + 1):
            name = f"<@{uid}>"
            embed.add_field(name=f"{idx}위", value=f"{name} : {score}초", inline=False)
        embed.set_footer(text=f"페이지 {self.page+1} / {max(1, (self.total + self.page_size - 1)//self.page_size)}")
        return embed

    async def send(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page <= 0:
            return await interaction.response.send_message("첫 페이지입니다.", ephemeral=True)
        self.page -= 1
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        max_page = max(0, (self.total - 1) // self.page_size)
        if self.page >= max_page:
            return await interaction.response.send_message("마지막 페이지입니다.", ephemeral=True)
        self.page += 1
        await interaction.response.edit_message(embed=self._make_embed(), view=self)

@bot.tree.command(name="typingrank", description="타자게임 랭킹 보기(페이지 이동 지원)")
async def typingrank(interaction: discord.Interaction):
    pager = RankPager(page=0, page_size=10)
    await pager.send(interaction)

@bot.hybrid_command(name="도움말-help", description="모든 명령어를 확인합니다.")
async def help_command(ctx: commands.Context):
    lines = [
        "/ping — 봇 지연시간 확인",
        "/ban — 유저 차단 (관리자)",
        "/kick — 유저 추방 (관리자)",
        "/say — 봇이 대신 말함 (관리자, 이미지 URL 지원)",
        "/ticket — 티켓 채널 생성",
        "/dice — 주사위 굴리기",
        "/coin — 동전 던지기",
        "/warn-warn — 경고 부여 (3회시 경고 역할 지급 5회시 추방)",
        "/warn-remove — 경고 차감",
        "/warnings — 경고 수 확인",
        "/rock-paper-scissors — 가위바위보 대결 신청 (버튼 UI)",
        "/typinggame — 타자게임 (혼자 또는 상대 지목 대결)",
        "/typingrank — 타자게임 랭킹",
        "/set-role-buttons — 역할 버튼 메뉴 생성 (관리자)",
        "/video-challenge — 비디오 챌린지를 실행합니다.",
        "/end-challenge — 관리자가 강제로 비디오 챌린지를 완료합니다.",
        "/challenge-status — 현재 비디오 챌린지를 확인합니다.",
        "/수학-난이도 — 수학 문제 난이도 설정",
        "/수학-문제 — 수학 문제 생성",
        "/수학-점수 — 수학 점수 확인",
        "/수학-통계 — 수학 문제 통계 확인",
        "/수학-랭킹 — 수학 서버 리더보드 확인"
    ]
    embed = discord.Embed(title="📖 도움말", color=discord.Color.blurple())
    for line in lines:
        cmd, desc = line.split(" — ", 1)
        embed.add_field(name=cmd, value=desc, inline=False)
    await ctx.send(embed=embed)

# ================= 역할 버튼 기능 =================
class RoleButton(discord.ui.View):
    def __init__(self, roles: list[Tuple[str, int]]):
        super().__init__(timeout=None)
        for label, role_id in roles:
            self.add_item(self.RoleBtn(label, role_id))

    class RoleBtn(discord.ui.Button):
        def __init__(self, label: str, role_id: int):
            super().__init__(label=label, style=discord.ButtonStyle.primary)
            self.role_id = role_id

        async def callback(self, interaction: discord.Interaction):
            role = interaction.guild.get_role(self.role_id)
            if not role:
                return await interaction.response.send_message("❌ 역할을 찾을 수 없습니다.", ephemeral=True)

            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                await interaction.response.send_message(f"❌ 역할 제거됨: {role.name}", ephemeral=True)
            else:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"✅ 역할 지급됨: {role.name}", ephemeral=True)


@bot.tree.command(name="set-role-buttons", description="버튼으로 역할 지급 메뉴 생성")
@app_commands.describe(
    title="메시지 제목",
    description="메시지 설명",
    role1="1번 버튼 (이름:역할ID)",
    role2="2번 버튼 (선택)",
    role3="3번 버튼 (선택)",
    role4="4번 버튼 (선택)",
    role5="5번 버튼 (선택)",
    role6="6번 버튼 (선택)",
    role7="7번 버튼 (선택)",
)
async def set_role_buttons(
    interaction: discord.Interaction,
    title: str,
    description: str,
    role1: str,
    role2: str = None,
    role3: str = None,
    role4: str = None,
    role5: str = None,
    role6: str = None,
    role7: str = None,
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ 관리자만 사용 가능합니다.", ephemeral=True)

    role_inputs = [role1, role2, role3, role4, role5, role6, role7]
    roles = []
    for r in role_inputs:
        if r:
            try:
                label, rid = r.split(":")
                rid = int(rid.strip())
                roles.append((label.strip(), rid))
            except:
                return await interaction.response.send_message("❌ 형식은 `버튼이름:역할ID` 로 입력해주세요.", ephemeral=True)

    if not roles:
        return await interaction.response.send_message("❌ 최소 1개 이상의 버튼을 입력해야 합니다.", ephemeral=True)

    embed = discord.Embed(title=title, description=description, color=discord.Color.green())
    view = RoleButton(roles)
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ 역할 버튼 메뉴가 생성되었습니다.", ephemeral=True)


# ================= 비디오 챌린지 =================
class ChallengeView(discord.ui.View):
    def __init__(self, user_id, channel_id):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.channel_id = channel_id
    
    @discord.ui.button(label='포기', style=discord.ButtonStyle.red, emoji='❌')
    async def give_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("본인만 포기할 수 있습니다.", ephemeral=True)
            return
        
        if self.channel_id in active_challenges:
            challenge_data = active_challenges[self.channel_id]
            challenge_data['status'] = 'given_up'
            
            if 'task' in challenge_data and not challenge_data['task'].done():
                challenge_data['task'].cancel()
        
        embed = discord.Embed(
            title="🔴 챌린지 포기",
            description=f"{interaction.user.mention}님이 챌린지를 포기했습니다.",
            color=0xff0000
        )
        
        await interaction.response.edit_message(embed=embed, view=None)
        
        if self.channel_id in active_challenges:
            del active_challenges[self.channel_id]


class VideoChallenge:
    def __init__(self, user_id, channel, video_file_path=None, completion_role_id=None):
        self.user_id = user_id
        self.channel = channel
        self.video_file_path = video_file_path or VIDEO_FILE_PATH
        self.video_title = VIDEO_TITLE
        self.completion_role_id = completion_role_id
        self.status = 'active'
        self.current_question = None
        self.question_start_time = None
        
    async def start_challenge(self):
        if not os.path.exists(self.video_file_path):
            embed = discord.Embed(
                title="❌ 파일 오류",
                description=f"영상 파일을 찾을 수 없습니다: {self.video_file_path}",
                color=0xff0000
            )
            await self.channel.send(embed=embed)
            return None
        
        file_size = os.path.getsize(self.video_file_path)
        if file_size > 8 * 1024 * 1024:
            embed = discord.Embed(
                title="❌ 파일 크기 초과",
                description=f"파일 크기가 8MB를 초과합니다.\n현재 크기: {file_size / (1024*1024):.1f}MB",
                color=0xff0000
            )
            await self.channel.send(embed=embed)
            return None
        
        embed = discord.Embed(
            title="🎬 비디오 챌린지 시작!",
            description=f"**참가자:** <@{self.user_id}>\n**비디오:** {self.video_title}\n\n3분마다 수학 문제가 출제됩니다.\n1분 이내에 답하지 못하면 자동 탈락됩니다!",
            color=0x00ff00
        )
        embed.add_field(name="📋 규칙", value="• 3분마다 수학 문제 출제\n• 1분 이내 답변 필수\n• 포기 버튼으로 언제든 종료 가능", inline=False)
        
        view = ChallengeView(self.user_id, self.channel.id)
        
        try:
            with open(self.video_file_path, 'rb') as f:
                file = discord.File(f, filename=os.path.basename(self.video_file_path))
                message = await self.channel.send(embed=embed, file=file, view=view)
        except Exception as e:
            embed = discord.Embed(
                title="❌ 파일 업로드 오류",
                description=f"파일 업로드 중 오류가 발생했습니다: {str(e)}",
                color=0xff0000
            )
            await self.channel.send(embed=embed)
            return None
        
        task = asyncio.create_task(self.question_loop())
        active_challenges[self.channel.id] = {
            'challenge': self,
            'message': message,
            'task': task,
            'status': 'active'
        }
        
        return task

    async def question_loop(self):
        try:
            while self.status == 'active':
                await asyncio.sleep(180)  # 3분
                if self.status != 'active':
                    break
                await self.ask_question()
                await asyncio.sleep(60)   # 1분 대기
                if self.current_question and self.status == 'active':
                    await self.fail_challenge("시간 초과로 탈락되었습니다.")
                    break
        except asyncio.CancelledError:
            pass
    
    async def ask_question(self):
        if self.status != 'active':
            return
        num1 = random.randint(1, 20)
        num2 = random.randint(1, 20)
        answer = num1 + num2
        self.current_question = {
            'question': f"{num1} + {num2} = ?",
            'answer': answer
        }
        self.question_start_time = datetime.now()
        embed = discord.Embed(
            title="🧮 수학 문제!",
            description=f"**문제:** {self.current_question['question']}\n\n<@{self.user_id}>님, 1분 이내에 답해주세요!",
            color=0xffff00
        )
        embed.add_field(name="⏰ 제한 시간", value="1분", inline=True)
        await self.channel.send(embed=embed)
    
    async def check_answer(self, message):
        if not self.current_question or self.status != 'active':
            return False
        if message.author.id != self.user_id:
            return False
        try:
            user_answer = int(message.content.strip())
            if user_answer == self.current_question['answer']:
                self.current_question = None
                embed = discord.Embed(
                    title="✅ 정답!",
                    description=f"{message.author.mention}님이 정답을 맞혔습니다!",
                    color=0x00ff00
                )
                await self.channel.send(embed=embed)
                return True
            else:
                await self.fail_challenge("오답으로 탈락되었습니다.")
                return True
        except ValueError:
            return False
    
    async def fail_challenge(self, reason):
        self.status = 'failed'
        embed = discord.Embed(
            title="❌ 챌린지 실패",
            description=f"<@{self.user_id}>님이 {reason}",
            color=0xff0000
        )
        await self.channel.send(embed=embed)
        if self.channel.id in active_challenges:
            del active_challenges[self.channel.id]
    
    async def complete_challenge(self):
        self.status = 'completed'
        embed = discord.Embed(
            title="🎉 챌린지 완료!",
            description=f"<@{self.user_id}>님이 비디오 챌린지를 완료했습니다!",
            color=0x00ff00
        )
        mention_text = ""
        if self.completion_role_id:
            mention_text = f"\n\n<@&{self.completion_role_id}> 챌린지가 완료되었습니다!"
        await self.channel.send(embed=embed)
        if mention_text:
            await self.channel.send(mention_text)
        if self.channel.id in active_challenges:
            del active_challenges[self.channel.id]


# ================= 비디오 챌린지 명령어 =================
@bot.tree.command(name="video-challenge", description="비디오 챌린지를 시작합니다")
@app_commands.describe(completion_role="완료 시 멘션할 역할 (선택사항)")
async def video_challenge(interaction: discord.Interaction, completion_role: discord.Role = None):
    if interaction.channel.id in active_challenges:
        embed = discord.Embed(
            title="⚠️ 이미 활성 챌린지가 있습니다",
            description="현재 채널에서 진행 중인 챌린지가 있습니다. 완료하거나 포기한 후 다시 시도해주세요.",
            color=0xff9900
        )
        await interaction.response.send_message(embed=embed)
        return
    completion_role_id = completion_role.id if completion_role else None
    challenge = VideoChallenge(interaction.user.id, interaction.channel, completion_role_id=completion_role_id)
    await interaction.response.send_message("챌린지를 시작합니다...")
    task = await challenge.start_challenge()
    if task is None:
        await interaction.edit_original_response(content="챌린지 시작에 실패했습니다.")

@bot.tree.command(name="end-challenge", description="현재 진행 중인 챌린지를 강제로 완료합니다 (관리자 전용)")
async def end_challenge(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        embed = discord.Embed(
            title="❌ 권한 부족",
            description="이 명령어는 관리자만 사용할 수 있습니다.",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.channel.id not in active_challenges:
        embed = discord.Embed(
            title="❌ 활성 챌린지 없음",
            description="현재 채널에서 진행 중인 챌린지가 없습니다.",
            color=0xff0000
        )
        await interaction.response.send_message(embed=embed)
        return
    challenge_data = active_challenges[interaction.channel.id]
    challenge = challenge_data['challenge']
    if 'task' in challenge_data and not challenge_data['task'].done():
        challenge_data['task'].cancel()
    await challenge.complete_challenge()
    embed = discord.Embed(
        title="✅ 챌린지 강제 완료",
        description="관리자에 의해 챌린지가 완료되었습니다.",
        color=0x00ff00
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="challenge-status", description="현재 챌린지 상태를 확인합니다")
async def challenge_status(interaction: discord.Interaction):
    if interaction.channel.id not in active_challenges:
        embed = discord.Embed(
            title="📊 챌린지 상태",
            description="현재 채널에서 진행 중인 챌린지가 없습니다.",
            color=0x999999
        )
        await interaction.response.send_message(embed=embed)
        return
    challenge_data = active_challenges[interaction.channel.id]
    challenge = challenge_data['challenge']
    embed = discord.Embed(
        title="📊 현재 챌린지 상태",
        color=0x0099ff
    )
    embed.add_field(name="참가자", value=f"<@{challenge.user_id}>", inline=True)
    embed.add_field(name="상태", value=challenge.status, inline=True)
    embed.add_field(name="비디오 파일", value=os.path.basename(challenge.video_file_path), inline=False)
    if challenge.current_question:
        time_left = 60 - (datetime.now() - challenge.question_start_time).seconds
        embed.add_field(name="현재 문제", value=challenge.current_question['question'], inline=True)
        embed.add_field(name="남은 시간", value=f"{max(0, time_left)}초", inline=True)
    await interaction.response.send_message(embed=embed)


# ================= 수학 게임 =================
# 등급
grades = [
    {'name':'🌱 수학 초보자','min':0,'max':49},
    {'name':'✏️ 수학 학습자','min':50,'max':99},
    {'name':'📚 수학 전문가','min':100,'max':249},
    {'name':'🥉 수학 마스터','min':250,'max':499},
    {'name':'🥈 수학 박사','min':500,'max':999},
    {'name':'🥇 수학 천재','min':1000,'max':999999}
]

# 난이도 저장
user_difficulty = {}

# 활성 문제
active_math_problems = {}

# 등급 계산
def get_grade(score):
    for g in grades:
        if g['min'] <= score <= g['max']:
            return g['name']
    return grades[0]['name']

# 문제 생성
def generate_problem(op_type, difficulty):
    if difficulty == '쉬움':
        limits = {'덧셈':20,'뺄셈':20,'곱셈':5,'나눗셈':12}
    elif difficulty == '중간':
        limits = {'덧셈':50,'뺄셈':50,'곱셈':10,'나눗셈':12}
    else:
        limits = {'덧셈':100,'뺄셈':100,'곱셈':12,'나눗셈':12}

    if op_type == '덧셈':
        a = random.randint(1, limits['덧셈'])
        b = random.randint(1, limits['덧셈'])
        ans = a + b
        symbol = '+'
    elif op_type == '뺄셈':
        a = random.randint(10, limits['뺄셈'])
        b = random.randint(0, a)
        ans = a - b
        symbol = '-'
    elif op_type == '곱셈':
        a = random.randint(1, limits['곱셈'])
        b = random.randint(1, limits['곱셈'])
        ans = a * b
        symbol = '×'
    else:  # 나눗셈
        b = random.randint(1, limits['나눗셈'])
        ans = random.randint(1, limits['나눗셈'])
        a = b * ans
        symbol = '÷'
    return {'num1':a, 'num2':b, 'answer':ans, 'symbol':symbol, 'operation':op_type}

# 문제 점수
def problem_score(problem):
    a, b = problem['num1'], problem['num2']
    op = problem['operation']
    if op in ['덧셈', '뺄셈']:
        return 10 if a <= 20 and b <= 20 else 20
    elif op == '곱셈':
        return 20 if a <= 10 and b <= 10 else 30
    else:
        return 30

# 역할 부여
async def assign_role(member, grade_name):
    guild = member.guild
    role = discord.utils.get(guild.roles, name=grade_name)
    if not role:
        role = await guild.create_role(name=grade_name, color=discord.Color.random(), reason='수학 등급 역할 생성')
    grade_names = [g['name'] for g in grades]
    for r in member.roles:
        if r.name in grade_names:
            await member.remove_roles(r)
    await member.add_roles(role)

@bot.tree.command(name='수학-난이도', description='수학 문제 난이도 설정')
@app_commands.describe(난이도='쉬움, 중간, 어려움')
async def math_difficulty(interaction: discord.Interaction, 난이도: str):
    if 난이도 not in ['쉬움', '중간', '어려움']:
        await interaction.response.send_message('❌ 유효한 난이도: 쉬움, 중간, 어려움', ephemeral=True)
        return
    user_difficulty[interaction.user.id] = 난이도
    await interaction.response.send_message(f'✅ 난이도가 **{난이도}** 으로 설정되었습니다!', ephemeral=True)

@bot.tree.command(name='수학-점수', description='수학 점수 확인')
async def math_score(interaction: discord.Interaction):
    data = get_math_score(str(interaction.user.id))
    grade = get_grade(data['score'])
    embed = discord.Embed(title='📊 내 점수', color=discord.Color.green())
    embed.add_field(name='점수', value=str(data['score']), inline=True)
    embed.add_field(name='등급', value=grade, inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='수학-통계', description='수학 문제 통계 확인')
async def math_stats(interaction: discord.Interaction):
    data = get_math_score(str(interaction.user.id))
    correct_rate = round(data['correct_count']/data['total_count']*100, 2) if data['total_count'] > 0 else 0
    embed = discord.Embed(title='📈 나의 통계', color=discord.Color.blue())
    embed.add_field(name='총 문제 수', value=data['total_count'], inline=True)
    embed.add_field(name='정답 수', value=data['correct_count'], inline=True)
    embed.add_field(name='정답률', value=f'{correct_rate}%', inline=True)
    embed.add_field(name='최고 연속 정답', value=data['max_consecutive'], inline=True)
    embed.add_field(name='현재 점수', value=data['score'], inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='수학-랭킹', description='수학 서버 리더보드 확인')
async def math_ranking(interaction: discord.Interaction):
    conn = sqlite3.connect(MATH_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_scores ORDER BY score DESC LIMIT 10")
    rows = cur.fetchall()
    conn.close()
    text = ''
    for i, r in enumerate(rows):
        text += f"{i+1}. <@{r[0]}> - {r[1]}점\n"
    embed = discord.Embed(title='🏆 서버 리더보드', description=text, color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='수학-문제', description='수학 문제 생성')
@app_commands.describe(연산='덧셈, 뺄셈, 곱셈, 나눗셈')
async def math_problem(interaction: discord.Interaction, 연산: str):
    if 연산 not in ['덧셈', '뺄셈', '곱셈', '나눗셈']:
        await interaction.response.send_message('❌ 올바른 연산을 선택해주세요', ephemeral=True)
        return
    
    if interaction.channel.id in active_math_problems:
        await interaction.response.send_message('❌ 이미 진행 중인 문제가 있습니다. 답을 입력하거나 시간이 지나면 새 문제를 낼 수 있습니다.', ephemeral=True)
        return
    
    diff = user_difficulty.get(interaction.user.id, '중간')
    p = generate_problem(연산, diff)

    embed = discord.Embed(
        title='🔢 수학 문제!', 
        description=f"**문제: {p['num1']} {p['symbol']} {p['num2']} = ?**", 
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"{interaction.user.name}님의 {p['operation']} 문제 (30초 제한)")
    
    active_math_problems[interaction.channel.id] = {
        'problem': p,
        'user_id': interaction.user.id,
        'timeout': None
    }

    # 타이머
    async def timeout_task():
        await asyncio.sleep(30)
        if interaction.channel.id in active_math_problems:
            del active_math_problems[interaction.channel.id]
            data = get_math_score(str(interaction.user.id))
            grade = get_grade(data['score'])
            await interaction.followup.send(f"⏰ 시간 초과! 정답: {p['answer']}\n현재 점수: {data['score']}\n등급: {grade}")

    asyncio.create_task(timeout_task())
    await interaction.response.send_message(embed=embed)

# ================= 기본 설정 =================
intents = discord.Intents.default()
intents.message_content = True

FISH_DB_FILE = "fishing_bot.db"  # SQLite DB 파일

# ================= 유저 데이터 =================
def init_user_table():
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            coins INTEGER,
            jji INTEGER,
            last_attendance TEXT
        )
    """)
    conn.commit()
    conn.close()

init_user_table()

def get_user_data(user_id: str):
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT coins, jji, last_attendance FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if row:
        coins, jji, last_attendance = row
    else:
        coins, jji, last_attendance = 0, 0, None
        cur.execute("INSERT INTO users (user_id, coins, jji, last_attendance) VALUES (?,?,?,?)", (user_id, coins, jji, None))
    conn.commit()
    conn.close()
    return {"coins": coins, "jji": jji, "last_attendance": last_attendance}

def update_user(user_id: str, coins: int, jji: int, last_attendance=None):
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users (user_id, coins, jji, last_attendance) VALUES (?,?,?,?)",
                (user_id, coins, jji, last_attendance))
    conn.commit()
    conn.close()

# ================= 출석 체크 =================
@bot.command()
async def 출석(ctx):
    uid = str(ctx.author.id)
    user = get_user_data(uid)
    today = datetime.now().date()
    if user["last_attendance"]:
        last = datetime.fromisoformat(user["last_attendance"]).date()
        if last == today:
            return await ctx.send(f"{ctx.author.mention}, 오늘은 이미 출석을 했습니다!")

    reward = 250
    update_user(uid, coins=user["coins"]+reward, jji=user["jji"], last_attendance=str(datetime.now()))
    await ctx.send(f"✅ {ctx.author.mention}, 출석 완료! {reward} 코인을 획득했습니다.")

# ================= 상점/인벤토리 =================
shop_items = {
    "나무 검": {"가격": 500, "능력치": 10},
    "돌 검": {"가격": 1000, "능력치": 20},
    "철 검": {"가격": 1500, "능력치": 30},
    "금 검": {"가격": 2000, "능력치": 40},
}

def add_item_to_inventory(user_id: str, item: str):
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item TEXT)")
    cur.execute("INSERT INTO inventory(user_id, item) VALUES (?,?)", (user_id, item))
    conn.commit()
    conn.close()

def get_inventory(user_id: str):
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item TEXT)")
    cur.execute("SELECT item FROM inventory WHERE user_id=?", (user_id,))
    items = [row[0] for row in cur.fetchall()]
    conn.close()
    return items

def get_power(user_id: str):
    items = get_inventory(user_id)
    total = 0
    for it in items:
        if it in shop_items:
            total += shop_items[it]["능력치"]
    return total

@bot.command()
async def 전평시상점(ctx):
    embed = Embed(title="🛒 상점", description="`!전평시 구매 <아이템>` 으로 구매 가능!", color=0xFFD700)
    for item, info in shop_items.items():
        embed.add_field(name=item, value=f"가격: {info['가격']}코인 | 전투력 +{info['능력치']}", inline=False)
    await ctx.send(embed=embed)

# ================= 낚시 =================
@bot.command()
async def 전평시낚시(ctx):
    uid = str(ctx.author.id)
    user = get_user_data(uid)
    reward = random.randint(20, 50)
    update_user(uid, coins=user["coins"]+reward, jji=user["jji"], last_attendance=user["last_attendance"])
    await ctx.send(f"🎣 {ctx.author.mention}, 낚시 성공! {reward} 코인을 획득했습니다.")

# ================= 던전 설정 =================
dungeons = {
    "초보던전": {"req": 0, "multiplier": 1.0, "drops": ["나무 검"], "drop_rate": 0.10, "target_need": 15, "time_limit": 25},
    "슬라임던전": {"req": 20, "multiplier": 1.5, "drops": ["나무 검", "돌 검"], "drop_rate": 0.20, "target_need": 20, "time_limit": 22},
    "중수던전": {"req": 50, "multiplier": 2.0, "drops": ["돌 검", "철 검"], "drop_rate": 0.30, "target_need": 30, "time_limit": 20},
    "중고수던전": {"req": 100, "multiplier": 3.0, "drops": ["철 검", "금 검"], "drop_rate": 0.40, "target_need": 35, "time_limit": 18},
    "고수던전": {"req": 200, "multiplier": 5.0, "drops": ["금 검"], "drop_rate": 0.50, "target_need": 40, "time_limit": 15}
}

# ================= 던전 랭킹 DB =================
def init_dungeon_stats():
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dungeon_stats (
            user_id TEXT,
            dungeon_name TEXT,
            clears INTEGER,
            fails INTEGER,
            coins INTEGER,
            PRIMARY KEY (user_id, dungeon_name)
        )
    """)
    try:
        cur.execute("ALTER TABLE dungeon_stats ADD COLUMN coins INTEGER DEFAULT 0")
    except:
        pass
    conn.commit()
    conn.close()

init_dungeon_stats()

def update_dungeon_result(user_id:str, dungeon_name:str, success:bool, coins:int=0):
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT clears, fails, coins FROM dungeon_stats WHERE user_id=? AND dungeon_name=?", (user_id, dungeon_name))
    row = cur.fetchone()
    if row:
        clears, fails, old_coins = row
        if success:
            clears += 1
            old_coins += coins
        else:
            fails += 1
        cur.execute("UPDATE dungeon_stats SET clears=?, fails=?, coins=? WHERE user_id=? AND dungeon_name=?",
                    (clears, fails, old_coins, user_id, dungeon_name))
    else:
        cur.execute("INSERT INTO dungeon_stats (user_id, dungeon_name, clears, fails, coins) VALUES (?,?,?,?,?)",
                    (user_id, dungeon_name, 1 if success else 0, 0 if success else 1, coins if success else 0))
    conn.commit()
    conn.close()

# ================= 던전 에임 테스트 =================
AIM_GRID_SIZE = 5

class AimButton(ui.Button):
    def __init__(self, index:int, view_ref:"AimGridView"):
        super().__init__(label="\u200b", style=ButtonStyle.secondary, row=index // AIM_GRID_SIZE)
        self.index = index
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view_ref.user_id:
            return await interaction.response.send_message("이 게임 참가자만 버튼을 누를 수 있어요.", ephemeral=True)
        if self.view_ref.finished:
            return
        if self.index == self.view_ref.target_index:
            self.view_ref.correct_count += 1
            self.view_ref.next_target()
            embed = Embed(title=f"🎯 던전: {self.view_ref.dungeon_name}",
                          description=f"정답 {self.view_ref.correct_count}/{self.view_ref.target_need}", color=0x00cc66)
            await interaction.response.edit_message(embed=embed, view=self.view_ref)
            if self.view_ref.correct_count >= self.view_ref.target_need:
                await self.view_ref.on_success(interaction)
        else:
            await self.view_ref.on_failure(interaction, "오답!")

class AimGridView(ui.View):
    def __init__(self, user_id:int, dungeon_name:str):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.dungeon_name = dungeon_name
        self.correct_count = 0
        self.finished = False
        self.message = None
        dungeon = dungeons[dungeon_name]
        self.target_need = dungeon["target_need"]
        self.end_time = asyncio.get_event_loop().time() + dungeon["time_limit"]
        for i in range(AIM_GRID_SIZE * AIM_GRID_SIZE):
            self.add_item(AimButton(i, self))
        self.next_target()

    def next_target(self):
        self.target_index = random.randrange(AIM_GRID_SIZE * AIM_GRID_SIZE)
        for child in self.children:
            if isinstance(child, AimButton):
                if child.index == self.target_index:
                    child.style = ButtonStyle.success
                    child.label = "◈"
                else:
                    child.style = ButtonStyle.secondary
                    child.label = "\u200b"

    async def start_timer(self, ctx):
        remain = self.end_time - asyncio.get_event_loop().time()
        while remain > 0 and not self.finished:
            await asyncio.sleep(1)
            remain = self.end_time - asyncio.get_event_loop().time()
        if not self.finished:
            await self.on_failure_context(ctx.channel, "시간 초과!")

    async def on_success(self, interaction: discord.Interaction):
        self.finished = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(embed=Embed(title="✅ 던전 클리어!", color=0x00ff66), view=self)
        await handle_dungeon_success(str(self.user_id), self.dungeon_name, interaction.channel, interaction.user)

    async def on_failure(self, interaction: discord.Interaction, reason:str):
        self.finished = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(content=f"❌ 던전 실패: {reason}", view=None)
        update_dungeon_result(str(self.user_id), self.dungeon_name, False, 0)

    async def on_failure_context(self, channel, reason:str):
        if self.finished:
            return
        self.finished = True
        for c in self.children:
            c.disabled = True
        await channel.send(f"❌ 던전 실패: {reason}")
        update_dungeon_result(str(self.user_id), self.dungeon_name, False, 0)

async def handle_dungeon_success(user_id:str, dungeon_name:str, channel, user_member:discord.Member):
    dungeon = dungeons[dungeon_name]
    base_reward = random.randint(50, 100)
    total = int(base_reward * dungeon["multiplier"])
    u = get_user_data(user_id)
    update_user(user_id, coins=u["coins"]+total, jji=u["jji"], last_attendance=u["last_attendance"])
    drop_item = None
    if random.random() < dungeon["drop_rate"]:
        drop_item = random.choice(dungeon["drops"])
        add_item_to_inventory(user_id, drop_item)
    update_dungeon_result(user_id, dungeon_name, True, total)
    desc = f"{user_member.mention} {dungeon_name} 클리어!\n💰 {total}코인 획득"
    if drop_item:
        desc += f"\n🎁 드랍 아이템: {drop_item}"
    await channel.send(embed=Embed(title="던전 보상", description=desc, color=0x00ff88))

# ================= 던전 명령어 =================
@bot.command()
async def 전평시(ctx, arg1=None, arg2=None):
    uid = str(ctx.author.id)
    if arg1 == "구매" and arg2:
        user = get_user_data(uid)
        if arg2 not in shop_items:
            return await ctx.send("그런 아이템은 없어!")
        price = shop_items[arg2]["가격"]
        if user["coins"] < price:
            return await ctx.send("코인이 부족합니다!")
        update_user(uid, coins=user["coins"]-price, jji=user["jji"], last_attendance=user["last_attendance"])
        add_item_to_inventory(uid, arg2)
        return await ctx.send(f"{ctx.author.mention} → {arg2} 구매 완료!")
    elif arg1 == "인벤토리":
        items = get_inventory(uid)
        text = ", ".join(items) if items else "없음"
        embed = Embed(title=f"{ctx.author.name}님의 인벤토리", color=0x00ccff)
        embed.add_field(name="보유 아이템", value=text, inline=False)
        embed.add_field(name="총 전투력", value=str(get_power(uid)))
        return await ctx.send(embed=embed)
    elif arg1 == "던전가기" and arg2:
        if arg2 not in dungeons:
            return await ctx.send("그런 던전은 없어요!")
        power = get_power(uid)
        req = dungeons[arg2]["req"]
        if power < req:
            return await ctx.send(f"⚔️ 전투력이 부족합니다! 필요 {req}, 현재 {power}")
        dungeon = dungeons[arg2]
        embed = Embed(title=f"{arg2} 입장!", description=f"정답 {dungeon['target_need']}회 / 제한 {dungeon['time_limit']}초", color=0x3366ff)
        view = AimGridView(ctx.author.id, arg2)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        asyncio.create_task(view.start_timer(ctx))
        return

# ================= 랭킹 명령어 =================
@bot.command()
async def 전평시던전랭킹(ctx, dungeon_name:str=None, 기준:str="클리어"):
    if dungeon_name is None:
        return await ctx.send("사용법: `!전평시던전랭킹 <던전이름|전체> [클리어|코인]`")
    order_by = "clears" if 기준 == "클리어" else "coins"
    uid = str(ctx.author.id)
    if dungeon_name == "전체":
        conn = sqlite3.connect(FISH_DB_FILE)
        cur = conn.cursor()
        cur.execute(f"""
            SELECT user_id, SUM(clears), SUM(fails), SUM(coins)
            FROM dungeon_stats
            GROUP BY user_id
            ORDER BY SUM({order_by}) DESC
        """)
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return await ctx.send("기록이 없습니다.")
        embed = Embed(title=f"전체 던전 랭킹 ({기준}순)", color=0xff9900)
        for i, (user_id, clears, fails, coins) in enumerate(rows[:10], start=1):
            user = await bot.fetch_user(int(user_id))
            embed.add_field(name=f"{i}위 - {user.name}",
                            value=f"클리어 {clears} | 실패 {fails} | 코인 {coins}", inline=False)
        for i, (user_id, clears, fails, coins) in enumerate(rows, start=1):
            if user_id == uid:
                embed.add_field(name=f"👉 내 순위 ({ctx.author.name})",
                                value=f"{i}위 | 클리어 {clears} | 실패 {fails} | 코인 {coins}", inline=False)
                break
        return await ctx.send(embed=embed)
    if dungeon_name not in dungeons:
        return await ctx.send("존재하지 않는 던전이에요.")
    conn = sqlite3.connect(FISH_DB_FILE)
    cur = conn.cursor()
    cur.execute(f"SELECT user_id, clears, fails, coins FROM dungeon_stats WHERE dungeon_name=? ORDER BY {order_by} DESC", (dungeon_name,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        return await ctx.send("기록이 없습니다.")
    embed = Embed(title=f"{dungeon_name} 랭킹 ({기준}순)", color=0xffcc00)
    for i, (user_id, clears, fails, coins) in enumerate(rows[:10], start=1):
        user = await bot.fetch_user(int(user_id))
        embed.add_field(name=f"{i}위 - {user.name}",
                        value=f"클리어 {clears} | 실패 {fails} | 코인 {coins}", inline=False)
    for i, (user_id, clears, fails, coins) in enumerate(rows, start=1):
        if user_id == uid:
            embed.add_field(name=f"👉 내 순위 ({ctx.author.name})",
                            value=f"{i}위 | 클리어 {clears} | 실패 {fails} | 코인 {coins}", inline=False)
            break
    await ctx.send(embed=embed)


# ---- 실행 ---
@bot.event
async def on_ready():
    print(f"✅ 로그인 완료: {bot.user}")
    init_main_db()
    init_math_db()
    try:
        synced = await bot.tree.sync()
        print(f"🔄 {len(synced)}개의 슬래시 명령어 동기화됨")
    except Exception as e:
        print(f"⚠️ 동기화 실패: {e}")

keep_alive()  # 추가
bot.run(os.getenv('BOT_TOKEN'))  # 토큰 부분을 환경변수로
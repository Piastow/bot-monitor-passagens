import discord
from discord.ext import commands, tasks
import asyncio
import aiohttp
import json
import os
from collections import defaultdict
import statistics
from datetime import datetime, timedelta

# ==========================================
# CONFIGURACOES
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CANAL_ALERTAS_ID = int(os.getenv("CANAL_ALERTAS_ID", "0"))
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")

AMADEUS_TOKEN = None
AMADEUS_TOKEN_EXPIRY = None

# Rotas dinamicas (podem ser adicionadas/removidas)
ROTAS = [
    {"origem": "GRU", "destino": "SSA", "nome": "Sao Paulo → Salvador"},
    {"origem": "GRU", "destino": "FOR", "nome": "Sao Paulo → Fortaleza"},
    {"origem": "GRU", "destino": "REC", "nome": "Sao Paulo → Recife"},
    {"origem": "GRU", "destino": "NAT", "nome": "Sao Paulo → Natal"},
    {"origem": "GRU", "destino": "MCZ", "nome": "Sao Paulo → Maceio"},
    {"origem": "GRU", "destino": "JFK", "nome": "Sao Paulo → Nova York"},
    {"origem": "GRU", "destino": "MIA", "nome": "Sao Paulo → Miami"},
    {"origem": "GRU", "destino": "LAX", "nome": "Sao Paulo → Los Angeles"},
    {"origem": "GRU", "destino": "LIS", "nome": "Sao Paulo → Lisboa"},
    {"origem": "GRU", "destino": "MAD", "nome": "Sao Paulo → Madrid"},
    {"origem": "GRU", "destino": "CDG", "nome": "Sao Paulo → Paris"},
    {"origem": "GRU", "destino": "LHR", "nome": "Sao Paulo → Londres"},
]

# Configuracoes
DIAS_APRENDIZADO = 0  # Ja passou dos 7 dias!
PERCENTUAL_DESCONTO = 35
PERCENTUAL_ANOMALIA = 50
INTERVALO_BASE = 6  # Intervalo base em horas
MODO_TESTE = False

# Sistema dinamico de intervalos
MODO_ATUAL = "NORMAL"  # NORMAL, ATIVO, CACADOR, ULTRA

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

historico_precos = defaultdict(list)
alertas_personalizados = defaultdict(list)
DATA_FILE = "historico_precos.json"
ALERTAS_FILE = "alertas_personalizados.json"

def carregar_dados():
    global historico_precos, alertas_personalizados
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            historico_precos = defaultdict(list, {k: v for k, v in data.items()})
    if os.path.exists(ALERTAS_FILE):
        with open(ALERTAS_FILE, 'r') as f:
            data = json.load(f)
            alertas_personalizados = defaultdict(list, {k: v for k, v in data.items()})

def salvar_dados():
    with open(DATA_FILE, 'w') as f:
        json.dump(dict(historico_precos), f)
    with open(ALERTAS_FILE, 'w') as f:
        json.dump(dict(alertas_personalizados), f)

# ==========================================
# AMADEUS API
# ==========================================
async def obter_token_amadeus():
    global AMADEUS_TOKEN, AMADEUS_TOKEN_EXPIRY
    if AMADEUS_TOKEN and AMADEUS_TOKEN_EXPIRY and datetime.now() < AMADEUS_TOKEN_EXPIRY:
        return AMADEUS_TOKEN
    
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, 
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "client_id": AMADEUS_API_KEY, "client_secret": AMADEUS_API_SECRET}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    AMADEUS_TOKEN = result['access_token']
                    AMADEUS_TOKEN_EXPIRY = datetime.now() + timedelta(seconds=result['expires_in'] - 60)
                    return AMADEUS_TOKEN
    except Exception as e:
        print(f"❌ Erro auth: {e}")
    return None

async def buscar_preco(origem, destino):
    token = await obter_token_amadeus()
    if not token:
        return None
    
    data_partida = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url,
                headers={"Authorization": f"Bearer {token}"},
                params={"originLocationCode": origem, "destinationLocationCode": destino,
                       "departureDate": data_partida, "adults": 1, "currencyCode": "BRL", "max": 1}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get('data') and len(result['data']) > 0:
                        return float(result['data'][0]['price']['total'])
    except Exception as e:
        print(f"❌ Erro busca: {e}")
    return None

# ==========================================
# ESTATISTICAS E SCORE
# ==========================================
def calcular_estatisticas(rota_id):
    precos = [p['preco'] for p in historico_precos[rota_id]]
    if len(precos) < 2:
        return None, None, None, None
    return statistics.mean(precos), statistics.stdev(precos), min(precos), max(precos)

def calcular_score(preco_atual, media, minimo, maximo):
    if not media or maximo == minimo:
        return 5
    score = 10 - ((preco_atual - minimo) / (maximo - minimo) * 10)
    return max(0, min(10, score))

def calcular_tendencia(rota_id):
    hist = historico_precos[rota_id]
    if len(hist) < 5:
        return "ESTAVEL", 0
    
    ultimos_5 = [p['preco'] for p in hist[-5:]]
    primeiros = statistics.mean(ultimos_5[:3])
    recentes = statistics.mean(ultimos_5[2:])
    
    variacao = ((recentes - primeiros) / primeiros) * 100
    
    if variacao < -5:
        return "CAINDO", variacao
    elif variacao > 5:
        return "SUBINDO", variacao
    return "ESTAVEL", variacao

def determinar_urgencia(score, tendencia):
    if score >= 9:
        return "🔥 COMPRE AGORA! Preco minimo historico!"
    elif score >= 8:
        if tendencia == "SUBINDO":
            return "⚡ COMPRE HOJE! Preco excelente e subindo!"
        return "⚡ COMPRE HOJE! Preco excelente!"
    elif score >= 7:
        return "✅ Boa oportunidade. Vale comprar."
    elif score >= 6:
        if tendencia == "CAINDO":
            return "⏰ Preco OK mas CAINDO. Aguarde mais um pouco."
        return "⏰ Preco OK. Pode esperar."
    elif score >= 5:
        return "📊 Preco na media. Aguarde melhores."
    return "❌ Preco ALTO. NAO compre agora!"

def determinar_tipo_alerta(preco_atual, media, score):
    if not media:
        return None
    percentual = ((media - preco_atual) / media) * 100
    
    if percentual >= PERCENTUAL_ANOMALIA or score >= 9:
        return "critico"
    elif percentual >= PERCENTUAL_DESCONTO or score >= 8:
        return "excelente"
    elif percentual >= 20 or score >= 7:
        return "bom"
    return None

# ==========================================
# SISTEMA DINAMICO DE INTERVALOS
# ==========================================
def determinar_intervalo():
    global MODO_ATUAL
    
    # Analisa todas as rotas pra ver se tem algo interessante
    quedas_grandes = 0
    
    for rota in ROTAS:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        hist = historico_precos[rota_id]
        
        if len(hist) < 3:
            continue
        
        media, _, _, _ = calcular_estatisticas(rota_id)
        if not media:
            continue
        
        ultimo_preco = hist[-1]['preco']
        percentual = ((media - ultimo_preco) / media) * 100
        
        if percentual >= 40:
            MODO_ATUAL = "ULTRA"
            return 0.25  # 15 minutos
        elif percentual >= 25:
            quedas_grandes += 1
    
    if quedas_grandes >= 2:
        MODO_ATUAL = "CACADOR"
        return 0.5  # 30 minutos
    elif quedas_grandes >= 1:
        MODO_ATUAL = "ATIVO"
        return 2  # 2 horas
    
    MODO_ATUAL = "NORMAL"
    return INTERVALO_BASE

# ==========================================
# ALERTAS
# ==========================================
async def enviar_alerta(canal, rota, preco, media, minimo, maximo, score, tipo, tendencia, var_tendencia):
    percentual = ((media - preco) / media) * 100
    urgencia = determinar_urgencia(score, tendencia)
    
    config = {
        "critico": {
            "cor": discord.Color.red(),
            "emoji": "🚨",
            "titulo": "ERRO DE PRECO DETECTADO!",
            "desc": "POSSIVEL BUG! Compre IMEDIATAMENTE!"
        },
        "excelente": {
            "cor": discord.Color.gold(),
            "emoji": "⚡",
            "titulo": "PROMOCAO EXCELENTE!",
            "desc": "Preco muito bom! Recomendado comprar HOJE!"
        },
        "bom": {
            "cor": discord.Color.green(),
            "emoji": "🎉",
            "titulo": "BOA PROMOCAO!",
            "desc": "Preco abaixo da media. Vale considerar."
        }
    }
    
    cfg = config[tipo]
    embed = discord.Embed(title=f"{cfg['emoji']} {cfg['titulo']}", color=cfg['cor'], timestamp=datetime.now())
    embed.description = cfg['desc']
    
    embed.add_field(name="✈️ Rota", value=rota['nome'], inline=False)
    embed.add_field(name="💰 Preco Atual", value=f"**R$ {preco:,.2f}**", inline=True)
    embed.add_field(name="📊 Media Hist.", value=f"R$ {media:,.2f}", inline=True)
    embed.add_field(name="📉 Desconto", value=f"**{percentual:.1f}%**", inline=True)
    embed.add_field(name="🏆 Score", value=f"**{score:.1f}/10**", inline=True)
    embed.add_field(name="💎 Min. Hist.", value=f"R$ {minimo:,.2f}", inline=True)
    embed.add_field(name="📈 Max. Hist.", value=f"R$ {maximo:,.2f}", inline=True)
    
    # Tendencia
    emoji_tend = "📉" if tendencia == "CAINDO" else "📈" if tendencia == "SUBINDO" else "➡️"
    embed.add_field(name=f"{emoji_tend} Tendencia", value=f"{tendencia} ({var_tendencia:+.1f}%)", inline=True)
    
    embed.add_field(name="⏰ Urgencia", value=urgencia, inline=False)
    embed.add_field(name="🔗 Comprar", value=f"[Google Flights](https://www.google.com/flights?q=flights+from+{rota['origem']}+to+{rota['destino']})", inline=False)
    
    embed.set_footer(text=f"Monitor Profissional • Modo: {MODO_ATUAL} • {rota['origem']}→{rota['destino']}")
    
    await canal.send(embed=embed)
    
    # Checa alertas personalizados
    await checar_alertas_personalizados(canal, rota, preco)

async def checar_alertas_personalizados(canal, rota, preco):
    rota_id = f"{rota['origem']}-{rota['destino']}"
    
    for user_id, alertas in alertas_personalizados.items():
        for alerta in alertas:
            if alerta['rota'] == rota_id and preco <= alerta['preco_max']:
                try:
                    user = await bot.fetch_user(int(user_id))
                    embed = discord.Embed(
                        title="🔔 SEU ALERTA PERSONALIZADO!",
                        description=f"O preco de {rota['nome']} atingiu seu alerta!",
                        color=discord.Color.blue()
                    )
                    embed.add_field(name="Preco Atual", value=f"R$ {preco:,.2f}")
                    embed.add_field(name="Seu Alerta", value=f"R$ {alerta['preco_max']:,.2f}")
                    await user.send(embed=embed)
                except:
                    pass

# ==========================================
# RELATORIO DIARIO
# ==========================================
@tasks.loop(hours=24)
async def relatorio_diario():
    now = datetime.now()
    if now.hour != 20:  # Espera ate 20h
        return
    
    canal = bot.get_channel(CANAL_ALERTAS_ID)
    if not canal:
        return
    
    # Coleta dados
    promocoes = []
    tendencias_alta = []
    tendencias_baixa = []
    
    for rota in ROTAS:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        hist = historico_precos[rota_id]
        
        if not hist or len(hist) < 5:
            continue
        
        media, _, minimo, maximo = calcular_estatisticas(rota_id)
        if not media:
            continue
        
        ultimo = hist[-1]['preco']
        score = calcular_score(ultimo, media, minimo, maximo)
        percentual = ((media - ultimo) / media) * 100
        tendencia, var = calcular_tendencia(rota_id)
        
        if percentual > 15:
            promocoes.append({
                'rota': rota,
                'preco': ultimo,
                'percentual': percentual,
                'score': score
            })
        
        if tendencia == "SUBINDO" and var > 5:
            tendencias_alta.append({'rota': rota, 'var': var})
        elif tendencia == "CAINDO" and var < -5:
            tendencias_baixa.append({'rota': rota, 'var': var})
    
    # Monta relatorio
    embed = discord.Embed(
        title="📊 RELATÓRIO DIÁRIO",
        description=f"🗓️ {now.strftime('%d de %B de %Y')}",
        color=discord.Color.blue(),
        timestamp=now
    )
    
    # Top 5 promocoes
    if promocoes:
        promocoes.sort(key=lambda x: x['score'], reverse=True)
        top5 = promocoes[:5]
        
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        promo_text = ""
        for i, p in enumerate(top5):
            promo_text += f"{medals[i]} **{p['rota']['nome']}**\n"
            promo_text += f"   R$ {p['preco']:,.2f} ({p['percentual']:.1f}% OFF) | Score: {p['score']:.1f}/10\n"
        
        embed.add_field(name="🔥 TOP 5 PROMOCOES", value=promo_text, inline=False)
    
    # Tendencias
    if tendencias_baixa or tendencias_alta:
        tend_text = ""
        if tendencias_baixa:
            tend_text += "📉 **CAINDO** (aguarde!):\n"
            for t in tendencias_baixa[:3]:
                tend_text += f"   • {t['rota']['nome']} ({t['var']:.1f}%)\n"
        if tendencias_alta:
            tend_text += "\n📈 **SUBINDO** (nao compre!):\n"
            for t in tendencias_alta[:3]:
                tend_text += f"   • {t['rota']['nome']} (+{t['var']:.1f}%)\n"
        
        embed.add_field(name="📈 TENDENCIAS", value=tend_text, inline=False)
    
    # Estatisticas
    total_checagens = sum(len(historico_precos[f"{r['origem']}-{r['destino']}"]) for r in ROTAS)
    embed.add_field(name="📊 Estatisticas", value=f"Checagens hoje: ~{total_checagens//len(ROTAS)}\nRotas: {len(ROTAS)}\nModo: {MODO_ATUAL}", inline=False)
    
    # Dica
    embed.add_field(name="💡 DICA DO DIA", value="Terças e quartas costumam ser 10-15% mais baratas!\nPróxima terça: configure seus alertas!", inline=False)
    
    embed.set_footer(text="Próximo relatório: amanhã às 20h")
    
    await canal.send(embed=embed)

# ==========================================
# EVENTOS
# ==========================================
@bot.event
async def on_ready():
    print(f'✅ Bot conectado: {bot.user}')
    print(f'📊 Rotas: {len(ROTAS)}')
    print(f'🔥 Sistema dinamico ativo')
    print(f'📚 Fase de aprendizado: CONCLUIDA')
    carregar_dados()
    monitorar_precos.start()
    relatorio_diario.start()

@tasks.loop(hours=INTERVALO_BASE)
async def monitorar_precos():
    # Determina intervalo dinamico
    novo_intervalo = determinar_intervalo()
    if novo_intervalo != monitorar_precos.hours:
        monitorar_precos.change_interval(hours=novo_intervalo)
        print(f"⚡ Modo alterado: {MODO_ATUAL} (intervalo: {novo_intervalo}h)")
    
    print(f"\n🔍 Checagem [{MODO_ATUAL}] - {datetime.now().strftime('%d/%m %H:%M')}")
    
    canal = bot.get_channel(CANAL_ALERTAS_ID)
    if not canal:
        return
    
    for rota in ROTAS:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        preco = await buscar_preco(rota['origem'], rota['destino'])
        
        if not preco:
            continue
        
        historico_precos[rota_id].append({'preco': preco, 'data': datetime.now().isoformat()})
        
        media, _, minimo, maximo = calcular_estatisticas(rota_id)
        if not media:
            print(f"📚 {rota['nome']}: R$ {preco:.2f} (coletando dados...)")
            continue
        
        score = calcular_score(preco, media, minimo, maximo)
        tendencia, var_tend = calcular_tendencia(rota_id)
        tipo = determinar_tipo_alerta(preco, media, score)
        
        if tipo or MODO_TESTE:
            print(f"🔔 ALERTA! {rota['nome']}: R$ {preco:.2f} (score: {score:.1f}/10)")
            await enviar_alerta(canal, rota, preco, media, minimo, maximo, score, tipo or "bom", tendencia, var_tend)
        else:
            print(f"✓ {rota['nome']}: R$ {preco:.2f} | Score: {score:.1f}/10 | {tendencia}")
        
        await asyncio.sleep(2)
    
    salvar_dados()

# ==========================================
# COMANDOS
# ==========================================
@bot.command(name='adicionar')
async def adicionar_rota(ctx, origem: str, destino: str, *, nome: str = None):
    origem, destino = origem.upper(), destino.upper()
    
    if any(r['origem'] == origem and r['destino'] == destino for r in ROTAS):
        await ctx.send(f"❌ Rota {origem}→{destino} ja existe!")
        return
    
    if not nome:
        nome = f"{origem} → {destino}"
    
    ROTAS.append({"origem": origem, "destino": destino, "nome": nome})
    await ctx.send(f"✅ Rota adicionada: {nome}")

@bot.command(name='remover')
async def remover_rota(ctx, origem: str, destino: str):
    origem, destino = origem.upper(), destino.upper()
    
    for i, r in enumerate(ROTAS):
        if r['origem'] == origem and r['destino'] == destino:
            ROTAS.pop(i)
            await ctx.send(f"✅ Rota removida: {r['nome']}")
            return
    
    await ctx.send(f"❌ Rota {origem}→{destino} nao encontrada!")

@bot.command(name='alerta')
async def criar_alerta(ctx, origem: str, destino: str, preco_max: float):
    origem, destino = origem.upper(), destino.upper()
    rota_id = f"{origem}-{destino}"
    user_id = str(ctx.author.id)
    
    if user_id not in alertas_personalizados:
        alertas_personalizados[user_id] = []
    
    alertas_personalizados[user_id].append({
        'rota': rota_id,
        'preco_max': preco_max
    })
    
    salvar_dados()
    await ctx.send(f"✅ Alerta criado! Voce sera notificado quando {origem}→{destino} ficar abaixo de R$ {preco_max:,.2f}")

@bot.command(name='deal')
async def deal_comando(ctx, origem: str, destino: str):
    origem, destino = origem.upper(), destino.upper()
    rota_id = f"{origem}-{destino}"
    
    hist = historico_precos[rota_id]
    if not hist or len(hist) < 5:
        await ctx.send("❌ Dados insuficientes para analise!")
        return
    
    media, _, minimo, maximo = calcular_estatisticas(rota_id)
    ultimo = hist[-1]['preco']
    score = calcular_score(ultimo, media, minimo, maximo)
    tendencia, var = calcular_tendencia(rota_id)
    urgencia = determinar_urgencia(score, tendencia)
    
    embed = discord.Embed(title=f"💎 ANALISE: {origem} → {destino}", color=discord.Color.purple())
    embed.add_field(name="💰 Preco Atual", value=f"R$ {ultimo:,.2f}", inline=True)
    embed.add_field(name="📊 Media", value=f"R$ {media:,.2f}", inline=True)
    embed.add_field(name="🏆 Score", value=f"**{score:.1f}/10**", inline=True)
    embed.add_field(name="💎 Min. Historico", value=f"R$ {minimo:,.2f}", inline=True)
    embed.add_field(name="📈 Max. Historico", value=f"R$ {maximo:,.2f}", inline=True)
    
    emoji_tend = "📉" if tendencia == "CAINDO" else "📈" if tendencia == "SUBINDO" else "➡️"
    embed.add_field(name=f"{emoji_tend} Tendencia", value=f"{tendencia} ({var:+.1f}%)", inline=True)
    embed.add_field(name="⏰ Recomendacao", value=urgencia, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='teste')
async def modo_teste(ctx, acao: str):
    global MODO_TESTE, DIAS_APRENDIZADO
    
    if acao.lower() == "on":
        MODO_TESTE = True
        DIAS_APRENDIZADO = 0
        await ctx.send("✅ Modo teste ATIVADO! Alertas imediatos habilitados.")
    elif acao.lower() == "off":
        MODO_TESTE = False
        await ctx.send("✅ Modo teste DESATIVADO. Voltando ao normal.")

if __name__ == "__main__":
    print("🚀 Bot Final Completo...")
    bot.run(DISCORD_TOKEN)

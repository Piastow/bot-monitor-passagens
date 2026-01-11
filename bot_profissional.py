import discord
from discord.ext import commands, tasks
import asyncio
import aiohttp
import json
import os
from collections import defaultdict
import statistics
from datetime import datetime, timedelta
import base64

# ==========================================
# CONFIGURACOES
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "seu-token-aqui")
CANAL_ALERTAS_ID = int(os.getenv("CANAL_ALERTAS_ID", "0"))

# Amadeus API
AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY", "y4fp5EpWG5Ck4qrhQPTOfRHQlR7xUcV7")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET", "489sijSGJqrYWe9o")
AMADEUS_TOKEN = None
AMADEUS_TOKEN_EXPIRY = None

# Rotas para monitorar
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

# Configuracoes de alerta
DIAS_APRENDIZADO = 7
PERCENTUAL_DESCONTO = 35
PERCENTUAL_ANOMALIA = 50
INTERVALO_CHECAGEM = 6

# ==========================================
# SETUP DO BOT
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

historico_precos = defaultdict(list)
DATA_FILE = "historico_precos.json"

def carregar_historico():
    global historico_precos
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            historico_precos = defaultdict(list, {k: v for k, v in data.items()})
        print(f"✅ Historico carregado: {len(historico_precos)} rotas")

def salvar_historico():
    with open(DATA_FILE, 'w') as f:
        json.dump(dict(historico_precos), f, indent=2)

# ==========================================
# AMADEUS API - AUTENTICACAO
# ==========================================
async def obter_token_amadeus():
    global AMADEUS_TOKEN, AMADEUS_TOKEN_EXPIRY
    
    # Verifica se token ainda e valido
    if AMADEUS_TOKEN and AMADEUS_TOKEN_EXPIRY and datetime.now() < AMADEUS_TOKEN_EXPIRY:
        return AMADEUS_TOKEN
    
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_API_KEY,
        "client_secret": AMADEUS_API_SECRET
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    AMADEUS_TOKEN = result['access_token']
                    expires_in = result['expires_in']
                    AMADEUS_TOKEN_EXPIRY = datetime.now() + timedelta(seconds=expires_in - 60)
                    print("✅ Token Amadeus obtido com sucesso")
                    return AMADEUS_TOKEN
                else:
                    print(f"❌ Erro ao obter token: {response.status}")
                    return None
    except Exception as e:
        print(f"❌ Erro na autenticacao Amadeus: {e}")
        return None

# ==========================================
# AMADEUS API - BUSCAR PRECOS
# ==========================================
async def buscar_preco_amadeus(origem, destino):
    token = await obter_token_amadeus()
    if not token:
        return None
    
    # Data de partida (30 dias a frente)
    data_partida = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    params = {
        "originLocationCode": origem,
        "destinationLocationCode": destino,
        "departureDate": data_partida,
        "adults": 1,
        "currencyCode": "BRL",
        "max": 1
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get('data') and len(result['data']) > 0:
                        preco = float(result['data'][0]['price']['total'])
                        print(f"✅ Preco real obtido: {origem}→{destino} = R$ {preco:.2f}")
                        return preco
                    else:
                        print(f"⚠️ Nenhum voo encontrado: {origem}→{destino}")
                        return None
                else:
                    print(f"❌ Erro na API: {response.status}")
                    return None
    except Exception as e:
        print(f"❌ Erro ao buscar preco: {e}")
        return None

# ==========================================
# CALCULO DE ESTATISTICAS E SCORE
# ==========================================
def calcular_estatisticas(rota_id):
    precos = [p['preco'] for p in historico_precos[rota_id]]
    if len(precos) < 2:
        return None, None, None, None
    
    media = statistics.mean(precos)
    desvio = statistics.stdev(precos) if len(precos) > 1 else 0
    minimo = min(precos)
    maximo = max(precos)
    
    return media, desvio, minimo, maximo

def calcular_score(preco_atual, media, minimo, maximo):
    """
    Calcula score de 0-10 baseado em quao bom e o preco
    10 = preco minimo historico
    0 = preco maximo historico
    """
    if not media or maximo == minimo:
        return 5
    
    # Normaliza o preco entre 0 e 10
    score = 10 - ((preco_atual - minimo) / (maximo - minimo) * 10)
    return max(0, min(10, score))

def determinar_urgencia(score, percentual_diferenca):
    """Determina urgencia de compra"""
    if score >= 9:
        return "COMPRE AGORA! Preco historico minimo!"
    elif score >= 8:
        return "COMPRE HOJE! Preco excelente!"
    elif score >= 7:
        return "Boa oportunidade. Considere comprar."
    elif score >= 6:
        return "Preco OK. Pode aguardar um pouco."
    elif score >= 5:
        return "Preco na media. Aguarde."
    else:
        return "Preco alto. NAO compre agora."

def determinar_tipo_alerta(preco_atual, media, score):
    if not media or media == 0:
        return None
    
    percentual_diferenca = ((media - preco_atual) / media) * 100
    
    if percentual_diferenca >= PERCENTUAL_ANOMALIA or score >= 9:
        return "erro_preco"  # Possivel erro = OPORTUNIDADE MAXIMA
    elif percentual_diferenca >= PERCENTUAL_DESCONTO or score >= 8:
        return "promocao_excelente"
    elif percentual_diferenca >= 20 or score >= 7:
        return "promocao_boa"
    else:
        return None

# ==========================================
# ALERTAS MELHORADOS
# ==========================================
async def enviar_alerta(canal, rota, preco_atual, media, minimo, maximo, score, tipo):
    percentual = ((media - preco_atual) / media) * 100
    urgencia = determinar_urgencia(score, percentual)
    
    if tipo == "erro_preco":
        cor = discord.Color.red()
        emoji = "🚨"
        titulo = "ERRO DE PRECO DETECTADO!"
        descricao = "COMPRE IMEDIATAMENTE! Preco anormal!"
    elif tipo == "promocao_excelente":
        cor = discord.Color.gold()
        emoji = "⚡"
        titulo = "PROMOCAO EXCELENTE!"
        descricao = "Preco muito bom! Recomendado comprar!"
    else:
        cor = discord.Color.green()
        emoji = "🎉"
        titulo = "BOA PROMOCAO ENCONTRADA"
        descricao = "Preco abaixo da media"
    
    embed = discord.Embed(title=f"{emoji} {titulo}", color=cor, timestamp=datetime.now())
    embed.add_field(name="✈️ Rota", value=rota['nome'], inline=False)
    embed.add_field(name="💰 Preco Atual", value=f"**R$ {preco_atual:,.2f}**", inline=True)
    embed.add_field(name="📊 Media Historica", value=f"R$ {media:,.2f}", inline=True)
    embed.add_field(name="📉 Desconto", value=f"**{percentual:.1f}%**", inline=True)
    embed.add_field(name="🏆 Score", value=f"**{score:.1f}/10**", inline=True)
    embed.add_field(name="💎 Menor Preco", value=f"R$ {minimo:,.2f}", inline=True)
    embed.add_field(name="📈 Maior Preco", value=f"R$ {maximo:,.2f}", inline=True)
    embed.add_field(name="⏰ Urgencia", value=urgencia, inline=False)
    embed.add_field(name="🔗 Como comprar", value=f"[Google Flights](https://www.google.com/flights?q=flights+from+{rota['origem']}+to+{rota['destino']})", inline=False)
    embed.set_footer(text=f"Bot Monitor Profissional • {rota['origem']}→{rota['destino']}")
    
    await canal.send(embed=embed)

# ==========================================
# EVENTOS DO BOT
# ==========================================
@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    print(f'📊 Monitorando {len(ROTAS)} rotas')
    print(f'🔑 Amadeus API configurada')
    carregar_historico()
    monitorar_precos.start()

@tasks.loop(hours=INTERVALO_CHECAGEM)
async def monitorar_precos():
    print(f"\n🔍 Iniciando verificacao de precos - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    canal = bot.get_channel(CANAL_ALERTAS_ID)
    if not canal:
        print("❌ Canal de alertas nao encontrado!")
        return
    
    for rota in ROTAS:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        
        # Busca preco REAL da Amadeus
        preco = await buscar_preco_amadeus(rota['origem'], rota['destino'])
        
        if preco is None:
            print(f"⚠️ Pulando {rota['nome']} (sem dados)")
            continue
        
        # Registra no historico
        historico_precos[rota_id].append({
            'preco': preco,
            'data': datetime.now().isoformat()
        })
        
        # Calcula estatisticas
        media, desvio, minimo, maximo = calcular_estatisticas(rota_id)
        
        # Verifica periodo de aprendizado
        dias_de_dados = len(historico_precos[rota_id]) / (24 / INTERVALO_CHECAGEM)
        
        if dias_de_dados < DIAS_APRENDIZADO:
            print(f"📚 {rota['nome']}: R$ {preco:.2f} (aprendendo... {dias_de_dados:.1f}/{DIAS_APRENDIZADO} dias)")
            continue
        
        # Calcula score e verifica alertas
        score = calcular_score(preco, media, minimo, maximo)
        tipo_alerta = determinar_tipo_alerta(preco, media, score)
        
        if tipo_alerta:
            print(f"🔔 ALERTA! {rota['nome']}: R$ {preco:.2f} (score: {score:.1f}/10)")
            await enviar_alerta(canal, rota, preco, media, minimo, maximo, score, tipo_alerta)
        else:
            print(f"✓ {rota['nome']}: R$ {preco:.2f} (score: {score:.1f}/10)")
        
        await asyncio.sleep(3)  # Evita rate limit
    
    salvar_historico()
    print(f"💾 Historico salvo\n")

# ==========================================
# COMANDOS
# ==========================================
@bot.command(name='status')
async def status_comando(ctx):
    embed = discord.Embed(title="📊 Status do Monitor Profissional", color=discord.Color.blue())
    
    total_rotas = len(ROTAS)
    rotas_com_dados = len([r for r in ROTAS if f"{r['origem']}-{r['destino']}" in historico_precos])
    
    embed.add_field(name="✈️ Rotas Monitoradas", value=str(total_rotas), inline=True)
    embed.add_field(name="📊 Rotas com Dados", value=str(rotas_com_dados), inline=True)
    embed.add_field(name="⏰ Intervalo", value=f"{INTERVALO_CHECAGEM}h", inline=True)
    
    # Mostra ultimas 5 rotas
    for rota in ROTAS[:5]:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        historico = historico_precos[rota_id]
        
        if historico:
            ultimo_preco = historico[-1]['preco']
            media, _, minimo, _ = calcular_estatisticas(rota_id)
            score = calcular_score(ultimo_preco, media, minimo, historico[-1]['preco']) if media else 5
            
            status = f"💰 R$ {ultimo_preco:.2f}\n🏆 Score: {score:.1f}/10"
            if media:
                status += f"\n📊 Media: R$ {media:.2f}"
            
            embed.add_field(name=f"✈️ {rota['nome']}", value=status, inline=False)
    
    embed.set_footer(text="Use !listar para ver todas as rotas")
    await ctx.send(embed=embed)

@bot.command(name='listar')
async def listar_comando(ctx):
    embed = discord.Embed(title="✈️ Todas as Rotas Monitoradas", color=discord.Color.blue())
    
    for rota in ROTAS:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        historico = historico_precos[rota_id]
        
        if historico:
            ultimo_preco = historico[-1]['preco']
            media, _, minimo, maximo = calcular_estatisticas(rota_id)
            score = calcular_score(ultimo_preco, media, minimo, maximo) if media else 5
            
            status = f"💰 **R$ {ultimo_preco:.2f}** | 🏆 {score:.1f}/10"
            embed.add_field(name=rota['nome'], value=status, inline=False)
        else:
            embed.add_field(name=rota['nome'], value="⏳ Aguardando dados...", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='melhor')
async def melhor_comando(ctx, destino: str):
    destino = destino.upper()
    rotas_destino = [r for r in ROTAS if r['destino'] == destino]
    
    if not rotas_destino:
        await ctx.send(f"❌ Destino {destino} nao encontrado!")
        return
    
    embed = discord.Embed(title=f"💎 Melhor Preco para {destino}", color=discord.Color.gold())
    
    for rota in rotas_destino:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        historico = historico_precos[rota_id]
        
        if historico:
            precos = [p['preco'] for p in historico]
            minimo = min(precos)
            atual = historico[-1]['preco']
            media = statistics.mean(precos)
            
            info = f"💎 Menor: **R$ {minimo:.2f}**\n💰 Atual: R$ {atual:.2f}\n📊 Media: R$ {media:.2f}"
            embed.add_field(name=rota['nome'], value=info, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='top5')
async def top5_comando(ctx):
    promocoes = []
    
    for rota in ROTAS:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        historico = historico_precos[rota_id]
        
        if historico and len(historico) >= 5:
            preco_atual = historico[-1]['preco']
            media, _, minimo, maximo = calcular_estatisticas(rota_id)
            if media:
                score = calcular_score(preco_atual, media, minimo, maximo)
                percentual = ((media - preco_atual) / media) * 100
                
                if percentual > 0:
                    promocoes.append({
                        'rota': rota,
                        'preco': preco_atual,
                        'percentual': percentual,
                        'score': score
                    })
    
    promocoes.sort(key=lambda x: x['score'], reverse=True)
    top5 = promocoes[:5]
    
    if not top5:
        await ctx.send("❌ Nenhuma promocao disponivel no momento!")
        return
    
    embed = discord.Embed(title="🔥 TOP 5 MELHORES PROMOCOES", color=discord.Color.gold())
    
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    
    for i, p in enumerate(top5):
        info = f"{medals[i]} **R$ {p['preco']:.2f}** | 📉 {p['percentual']:.1f}% OFF | 🏆 {p['score']:.1f}/10"
        embed.add_field(name=p['rota']['nome'], value=info, inline=False)
    
    await ctx.send(embed=embed)

if __name__ == "__main__":
    print("🚀 Iniciando Bot Monitor PROFISSIONAL...")
    print(f"⏰ Intervalo de checagem: {INTERVALO_CHECAGEM} horas")
    print(f"📚 Periodo de aprendizado: {DIAS_APRENDIZADO} dias")
    print(f"🔑 Amadeus API ativa")
    bot.run(DISCORD_TOKEN)

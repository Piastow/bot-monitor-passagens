import os
import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
from collections import defaultdict
import statistics
from datetime import datetime
import random

# ==========================================
# COLE SEU TOKEN AQUI (igual ao teste_token.py)
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "seu-token-aqui")

# ID do canal (copie do Discord com botao direito → Copiar ID)
CANAL_ALERTAS_ID = int(os.getenv("CANAL_ALERTAS_ID", "0"))

# ==========================================
# ROTAS PARA MONITORAR
# ==========================================
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
DIAS_APRENDIZADO = 7
PERCENTUAL_DESCONTO = 35
PERCENTUAL_ANOMALIA = 50
INTERVALO_CHECAGEM = 6

# ==========================================
# CODIGO DO BOT (NAO PRECISA MEXER)
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

async def buscar_preco(origem, destino):
    # Precos simulados para teste
    precos_base = {
        ("GRU", "SSA"): 800,
        ("GRU", "FOR"): 850,
        ("GRU", "REC"): 900,
        ("GRU", "NAT"): 950,
        ("GRU", "MCZ"): 920,
        ("GRU", "JFK"): 4500,
        ("GRU", "MIA"): 3200,
        ("GRU", "LAX"): 5000,
        ("GRU", "LIS"): 3800,
        ("GRU", "MAD"): 3900,
        ("GRU", "CDG"): 4200,
        ("GRU", "LHR"): 4500,
    }
    
    base = precos_base.get((origem, destino), 1000)
    variacao = random.uniform(-0.2, 0.3)
    preco = base * (1 + variacao)
    
    if random.random() < 0.05:
        preco *= 0.6
    
    return round(preco, 2)

def calcular_estatisticas(rota_id):
    precos = [p['preco'] for p in historico_precos[rota_id]]
    if len(precos) < 2:
        return None, None
    media = statistics.mean(precos)
    desvio = statistics.stdev(precos) if len(precos) > 1 else 0
    return media, desvio

def determinar_tipo_alerta(preco_atual, media):
    if not media or media == 0:
        return None
    percentual_diferenca = ((media - preco_atual) / media) * 100
    if percentual_diferenca >= PERCENTUAL_ANOMALIA:
        return "anomalia"
    elif percentual_diferenca >= PERCENTUAL_DESCONTO:
        return "promocao"
    else:
        return None

async def enviar_alerta(canal, rota, preco_atual, media, tipo):
    if tipo == "promocao":
        cor = discord.Color.green()
        emoji = "🎉"
        titulo = "PROMOCAO ENCONTRADA!"
        descricao = "Preco muito abaixo da media!"
    else:
        cor = discord.Color.red()
        emoji = "⚠️"
        titulo = "POSSIVEL ERRO DE PRECO"
        descricao = "Preco anormalmente baixo - confira se nao e erro!"
    
    percentual = ((media - preco_atual) / media) * 100
    
    embed = discord.Embed(title=f"{emoji} {titulo}", color=cor)
    embed.add_field(name="Rota", value=rota['nome'], inline=False)
    embed.add_field(name="Preco Atual", value=f"R$ {preco_atual:,.2f}", inline=True)
    embed.add_field(name="Media Historica", value=f"R$ {media:,.2f}", inline=True)
    embed.add_field(name="Desconto", value=f"{percentual:.1f}%", inline=True)
    embed.add_field(name="Status", value=descricao, inline=False)
    embed.timestamp = datetime.now()
    embed.set_footer(text=f"Bot Monitor de Passagens")
    
    await canal.send(embed=embed)

@bot.event
async def on_ready():
    print(f'✅ Bot conectado como {bot.user}')
    print(f'📊 Monitorando {len(ROTAS)} rotas')
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
        preco = await buscar_preco(rota['origem'], rota['destino'])
        
        if preco is None:
            continue
        
        historico_precos[rota_id].append({
            'preco': preco,
            'data': datetime.now().isoformat()
        })
        
        media, desvio = calcular_estatisticas(rota_id)
        dias_de_dados = len(historico_precos[rota_id]) / (24 / INTERVALO_CHECAGEM)
        
        if dias_de_dados < DIAS_APRENDIZADO:
            print(f"📚 {rota['nome']}: R$ {preco:.2f} (aprendendo... {dias_de_dados:.1f}/{DIAS_APRENDIZADO} dias)")
            continue
        
        tipo_alerta = determinar_tipo_alerta(preco, media)
        
        if tipo_alerta:
            print(f"🔔 ALERTA! {rota['nome']}: R$ {preco:.2f} (media: R$ {media:.2f})")
            await enviar_alerta(canal, rota, preco, media, tipo_alerta)
        else:
            print(f"✓ {rota['nome']}: R$ {preco:.2f} (media: R$ {media:.2f})")
        
        await asyncio.sleep(2)
    
    salvar_historico()
    print(f"💾 Historico salvo\n")

@bot.command(name='status')
async def status_comando(ctx):
    embed = discord.Embed(title="📊 Status do Monitor", color=discord.Color.blue())
    
    for rota in ROTAS[:5]:
        rota_id = f"{rota['origem']}-{rota['destino']}"
        historico = historico_precos[rota_id]
        
        if historico:
            ultimo_preco = historico[-1]['preco']
            media, _ = calcular_estatisticas(rota_id)
            dias = len(historico) / (24 / INTERVALO_CHECAGEM)
            
            status = f"R$ {ultimo_preco:.2f}"
            if media:
                status += f" (media: R$ {media:.2f})"
            status += f"\n{len(historico)} registros ({dias:.1f} dias)"
            
            embed.add_field(name=rota['nome'], value=status, inline=False)
    
    embed.set_footer(text=f"Monitorando {len(ROTAS)} rotas")
    await ctx.send(embed=embed)

@bot.command(name='historico')
async def historico_comando(ctx, origem: str = "GRU", destino: str = "SSA"):
    rota_id = f"{origem.upper()}-{destino.upper()}"
    historico = historico_precos[rota_id]
    
    if not historico:
        await ctx.send(f"❌ Nenhum dado encontrado para {origem}→{destino}")
        return
    
    precos = [p['preco'] for p in historico[-10:]]
    media, desvio = calcular_estatisticas(rota_id)
    
    embed = discord.Embed(title=f"📈 Historico: {origem}→{destino}", color=discord.Color.blue())
    embed.add_field(name="Ultimos precos", value="\n".join([f"R$ {p:.2f}" for p in precos]), inline=True)
    
    if media:
        embed.add_field(name="Estatisticas", value=f"Media: R$ {media:.2f}\nDesvio: R$ {desvio:.2f}", inline=True)
    
    embed.add_field(name="Total de registros", value=f"{len(historico)}", inline=False)
    await ctx.send(embed=embed)

if __name__ == "__main__":
    print("🚀 Iniciando Bot Monitor de Passagens...")
    print(f"⏰ Intervalo de checagem: {INTERVALO_CHECAGEM} horas")
    print(f"📚 Periodo de aprendizado: {DIAS_APRENDIZADO} dias")

    bot.run(DISCORD_TOKEN)

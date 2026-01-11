import os

# Pega o token das variáveis de ambiente
token = os.getenv("DISCORD_TOKEN", "NAO_ENCONTRADO")
canal_id = os.getenv("CANAL_ALERTAS_ID", "NAO_ENCONTRADO")

print("=" * 50)
print("VERIFICAÇÃO DE VARIÁVEIS DE AMBIENTE")
print("=" * 50)

# Token
print(f"\n📋 DISCORD_TOKEN:")
if token == "NAO_ENCONTRADO":
    print("❌ VARIÁVEL NÃO ENCONTRADA!")
else:
    # Mostra primeiros 20 e últimos 10 caracteres
    if len(token) > 30:
        censored = f"{token[:20]}...{token[-10:]}"
        print(f"✅ Token encontrado: {censored}")
        print(f"📏 Tamanho: {len(token)} caracteres")
        
        # Verifica estrutura (deve ter 3 partes separadas por ponto)
        partes = token.split('.')
        print(f"🔢 Partes (separadas por '.'): {len(partes)}")
        
        if len(partes) == 3:
            print(f"   Parte 1: {len(partes[0])} caracteres")
            print(f"   Parte 2: {len(partes[1])} caracteres")
            print(f"   Parte 3: {len(partes[2])} caracteres")
            print("✅ Estrutura correta (3 partes)")
        else:
            print("❌ ERRO: Token deve ter 3 partes separadas por ponto!")
    else:
        print(f"❌ Token muito curto: {len(token)} caracteres")
        print("   Token válido deve ter 70-80 caracteres")

# Canal ID
print(f"\n📺 CANAL_ALERTAS_ID:")
if canal_id == "NAO_ENCONTRADO":
    print("❌ VARIÁVEL NÃO ENCONTRADA!")
else:
    print(f"✅ Canal ID: {canal_id}")
    try:
        int(canal_id)
        print("✅ ID é numérico (correto)")
    except:
        print("❌ ERRO: ID deve ser apenas números!")

print("\n" + "=" * 50)
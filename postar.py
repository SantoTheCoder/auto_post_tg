#postar.py

import json
import os
import random
import re
import asyncio
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from PIL import Image
import tempfile
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Função para carregar configurações do arquivo config.json
def carregar_config(config_path='config.json'):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Converter target_id para inteiro (sem aspas)
            config['target_id'] = int(config['target_id'])
            # Verificar se 'scheduled_times' é uma lista
            if not isinstance(config.get('scheduled_times', []), list):
                print("Erro: 'scheduled_times' deve ser uma lista de horários no formato 'HH:MM'.")
                exit(1)
            # Verificar se 'posts_per_day' corresponde ao número de 'scheduled_times'
            if config.get('posts_per_day') != len(config.get('scheduled_times', [])):
                print("Erro: 'posts_per_day' deve corresponder ao número de horários em 'scheduled_times'.")
                exit(1)
            # Verificar se 'variation_minutes' é um inteiro
            if not isinstance(config.get('variation_minutes'), int):
                print("Erro: 'variation_minutes' deve ser um número inteiro.")
                exit(1)
            return config
    except FileNotFoundError:
        print(f"Erro: O arquivo {config_path} não foi encontrado.")
        exit(1)
    except json.JSONDecodeError:
        print(f"Erro: O arquivo {config_path} não está em formato JSON válido.")
        exit(1)
    except ValueError:
        print(f"Erro: 'target_id' deve ser um número inteiro.")
        exit(1)

# Função para ler e parsear os posts do arquivo posts.txt
def carregar_posts(posts_path='posts.txt'):
    try:
        with open(posts_path, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        # Expressão regular para capturar o texto entre -- INICIO e -- FIM
        padrao = r'-- INICIO\s*(.*?)\s*-- FIM'
        posts = re.findall(padrao, conteudo, re.DOTALL)
        return [post.strip() for post in posts]
    except FileNotFoundError:
        print(f"Erro: O arquivo {posts_path} não foi encontrado.")
        exit(1)

# Função para listar as imagens na pasta 'imagens' com as extensões válidas
def listar_imagens(pasta='imagens'):
    extensoes_validas = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg', '.heic')
    try:
        imagens = [os.path.join(pasta, img) for img in os.listdir(pasta) if img.lower().endswith(extensoes_validas)]
        if not imagens:
            print(f"Erro: Nenhuma imagem válida encontrada na pasta '{pasta}'.")
            exit(1)
        return imagens
    except FileNotFoundError:
        print(f"Erro: A pasta '{pasta}' não foi encontrada.")
        exit(1)

# Função para converter imagens .webp para .png
def converter_webp_para_png(caminho_imagem):
    try:
        with Image.open(caminho_imagem) as img:
            # Cria um arquivo temporário para salvar a imagem convertida
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            img.convert('RGBA').save(temp_file.name, 'PNG')
            return temp_file.name
    except Exception as e:
        print(f"Erro ao converter {caminho_imagem} para PNG: {e}")
        return None

# Função principal para postar a mensagem com a imagem
async def postar_mensagem(config, posts, imagens):
    # Adicionar variação aleatória
    if config['variation_minutes'] > 0:
        delay = random.randint(0, config['variation_minutes'])
        print(f"Aguardando {delay} minutos para enviar o post.")
        await asyncio.sleep(delay * 60)  # Converter minutos para segundos

    # Inicializar o cliente Telethon
    client = TelegramClient('session_name', config['api_id'], config['api_hash'])

    try:
        await client.start()
        print("Cliente iniciado com sucesso.")
    except Exception as e:
        print(f"Erro ao iniciar o cliente Telethon: {e}")
        return

    # Verificar se a entidade (grupo ou canal) existe e está acessível
    try:
        entity = await client.get_entity(config['target_id'])
        entity_name = entity.title if hasattr(entity, 'title') else (entity.username if hasattr(entity, 'username') else 'Nome Desconhecido')
        print(f"Entidade encontrada: {entity_name}")
    except Exception as e:
        print(f"Erro ao encontrar a entidade: {e}")
        await client.disconnect()
        return

    # Selecionar um post e uma imagem aleatoriamente
    post_selecionado = random.choice(posts)
    imagem_selecionada = random.choice(imagens)

    print(f"Post selecionado: {post_selecionado}")
    print(f"Imagem selecionada: {imagem_selecionada}")

    # Verificar se a imagem é .webp e converter se necessário
    extensao = os.path.splitext(imagem_selecionada)[1].lower()
    if extensao == '.webp':
        imagem_para_enviar = converter_webp_para_png(imagem_selecionada)
        if not imagem_para_enviar:
            print("Erro: Não foi possível converter a imagem .webp.")
            await client.disconnect()
            return
    else:
        imagem_para_enviar = imagem_selecionada

    # Enviar a mensagem com a imagem sem os marcadores -- INICIO e -- FIM
    try:
        await client.send_file(
            config['target_id'],
            imagem_para_enviar,
            caption=post_selecionado  # Envia apenas o conteúdo do post
        )
        print("Mensagem enviada com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
    finally:
        # Se a imagem foi convertida, remover o arquivo temporário
        if extensao == '.webp' and imagem_para_enviar:
            try:
                os.remove(imagem_para_enviar)
            except Exception as e:
                print(f"Erro ao remover arquivo temporário: {e}")
        await client.disconnect()

# Função para agendar os posts
def agendar_posts(config, posts, imagens):
    scheduler = AsyncIOScheduler()

    def parse_time(time_str):
        """Converte uma string de horário 'HH:MM' para hora e minuto inteiros."""
        try:
            hora, minuto = map(int, time_str.split(':'))
            return hora, minuto
        except ValueError:
            print(f"Erro: Horário '{time_str}' está no formato inválido. Use 'HH:MM'.")
            exit(1)

    async def job_wrapper():
        await postar_mensagem(config, posts, imagens)

    for scheduled_time in config['scheduled_times']:
        hora, minuto = parse_time(scheduled_time)
        # Define o trigger cron para cada horário
        trigger = CronTrigger(hour=hora, minute=minuto)
        # Adiciona o job ao scheduler
        scheduler.add_job(
            job_wrapper,
            trigger=trigger,
            name=f"Post diário às {scheduled_time}"
        )
        print(f"Agendado: Post diário às {scheduled_time} com variação de {config['variation_minutes']} minutos.")

    # Iniciar o scheduler
    scheduler.start()
    print("Scheduler iniciado e funcionando.")

    # Manter o loop rodando
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass

# Função principal que coordena o fluxo do programa
def main():
    config = carregar_config()
    posts = carregar_posts()
    imagens = listar_imagens()

    if not posts:
        print("Erro: Nenhum post encontrado no arquivo posts.txt.")
        return

    if not imagens:
        print("Erro: Nenhuma imagem encontrada na pasta 'imagens'.")
        return

    agendar_posts(config, posts, imagens)

# Ponto de entrada do script
if __name__ == '__main__':
    main()

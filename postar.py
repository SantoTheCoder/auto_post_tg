# postar.py

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

# ----------------------------------------------------------------------------- 
# NOVO: Definir um arquivo de estado para gravar em disco quais itens já foram usados
# -----------------------------------------------------------------------------
STATE_FILE = 'state.json'

def load_state():
    """Carrega o estado do ciclo (quais posts e mídias ainda faltam) do arquivo STATE_FILE."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            # Se houver qualquer problema para carregar, retorna estado vazio
            return {}
    else:
        return {}

def save_state(state):
    """Salva o estado atual no arquivo STATE_FILE."""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=4)

# -----------------------------------------------------------------------------
# Função para carregar configurações do arquivo config.json
# -----------------------------------------------------------------------------
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

            # Se test_mode não existir no JSON, definimos como False por padrão
            if 'test_mode' not in config:
                config['test_mode'] = False

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


# -----------------------------------------------------------------------------
# Função para ler e parsear os posts do arquivo posts.txt
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# Função para listar mídias (imagens e vídeos) na pasta 'imagens'
# -----------------------------------------------------------------------------
def listar_imagens(pasta='imagens'):
    # Agora incluindo também vídeos .mp4 como mídia válida
    extensoes_validas = (
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', 
        '.webp', '.tiff', '.svg', '.heic', '.mp4'
    )
    try:
        arquivos = [
            os.path.join(pasta, nome)
            for nome in os.listdir(pasta)
            if nome.lower().endswith(extensoes_validas)
        ]
        if not arquivos:
            print(f"Erro: Nenhum arquivo de mídia válido encontrado na pasta '{pasta}'.")
            exit(1)
        return arquivos
    except FileNotFoundError:
        print(f"Erro: A pasta '{pasta}' não foi encontrada.")
        exit(1)


# -----------------------------------------------------------------------------
# Função para converter imagens .webp para .png
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# Classe para selecionar itens aleatoriamente e ciclar indefinidamente,
# sem repetir até completar o ciclo, e com persistência de estado.
# -----------------------------------------------------------------------------
class SelecionadorAleatorio:
    def __init__(self, itens, state_key):
        """
        :param itens: Lista completa de itens (posts ou mídias).
        :param state_key: String para diferenciar o estado ('posts' ou 'midias').
        """
        self.state_key = state_key
        self.itens_original = itens.copy()
        
        # Carrega o estado
        self.state = load_state()
        
        # Se não existir algo no estado para essa key, cria um novo shuffle
        if self.state_key not in self.state:
            # Gera um novo ciclo e salva
            random.shuffle(self.itens_original)
            self.state[self.state_key] = self.itens_original.copy()
            save_state(self.state)
        
        # Aqui usamos a lista do estado como "itens atuais"
        self.itens = self.state[self.state_key].copy()

    def proximo(self):
        """
        Retorna o próximo item sem repetir até esgotar o ciclo.
        Quando esgota, inicia novo shuffle.
        """
        # Se não houver mais itens no estado (ciclo acabou), reinicia
        if not self.itens:
            random.shuffle(self.itens_original)
            self.itens = self.itens_original.copy()
            # Atualiza o estado
            self.state[self.state_key] = self.itens
            save_state(self.state)

        # Pega o último item
        item = self.itens.pop()
        # Atualiza a lista no estado com o item removido
        self.state[self.state_key] = self.itens
        save_state(self.state)

        return item

    def reset(self):
        """Se quiser reiniciar completamente o ciclo (não é obrigatório usar)."""
        random.shuffle(self.itens_original)
        self.itens = self.itens_original.copy()
        self.state[self.state_key] = self.itens
        save_state(self.state)

    def set_itens(self, novos_itens):
        """
        Se quiser trocar a lista original por uma nova (não é obrigatório usar).
        """
        self.itens_original = novos_itens.copy()
        random.shuffle(self.itens_original)
        self.itens = self.itens_original.copy()
        self.state[self.state_key] = self.itens
        save_state(self.state)


# -----------------------------------------------------------------------------
# Função principal para postar a mensagem com a imagem ou vídeo
# -----------------------------------------------------------------------------
async def postar_mensagem(config, posts_selecionados, midias_selecionadas):
    # Inicializar os selecionadores aleatórios se ainda não existirem
    # ** Repare que passamos a key 'posts' ou 'midias' para persistir corretamente. **
    if not hasattr(postar_mensagem, "selecionador_posts"):
        postar_mensagem.selecionador_posts = SelecionadorAleatorio(posts_selecionados, 'posts')
    if not hasattr(postar_mensagem, "selecionador_midias"):
        postar_mensagem.selecionador_midias = SelecionadorAleatorio(midias_selecionadas, 'midias')

    # Selecionar um post e uma mídia aleatoriamente (sem repetir até ciclo fechar)
    post_selecionado = postar_mensagem.selecionador_posts.proximo()
    midia_selecionada = postar_mensagem.selecionador_midias.proximo()

    print(f"Post selecionado: {post_selecionado[:50]}...")  # Mostra os primeiros 50 caracteres
    print(f"Mídia selecionada: {midia_selecionada}")

    # Verificar o comprimento do post
    if len(post_selecionado) > 1024:
        enviar_com_midia = False
        print("O post excede 1024 caracteres. Será enviado sem a imagem.")
    else:
        enviar_com_midia = True

    extensao = os.path.splitext(midia_selecionada)[1].lower()

    # Se for .webp, converter para .png
    if enviar_com_midia and extensao == '.webp':
        midia_para_enviar = converter_webp_para_png(midia_selecionada)
        if not midia_para_enviar:
            print("Erro: Não foi possível converter a imagem .webp.")
            midia_para_enviar = None
            enviar_com_midia = False
    elif enviar_com_midia:
        midia_para_enviar = midia_selecionada
    else:
        midia_para_enviar = None

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
        entity_name = (entity.title if hasattr(entity, 'title') 
                       else (entity.username if hasattr(entity, 'username') 
                             else 'Nome Desconhecido'))
        print(f"Entidade encontrada: {entity_name}")
    except Exception as e:
        print(f"Erro ao encontrar a entidade: {e}")
        await client.disconnect()
        return

    # Enviar a mensagem (imagem ou vídeo) com a legenda ou apenas texto
    try:
        if enviar_com_midia and midia_para_enviar:
            await client.send_file(
                config['target_id'],
                midia_para_enviar,
                caption=post_selecionado  # Envia o conteúdo do post como legenda
            )
            print("Mensagem com mídia enviada com sucesso!")
        else:
            await client.send_message(
                config['target_id'],
                post_selecionado
            )
            print("Mensagem de texto enviada com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
    finally:
        # Se a imagem foi convertida, remover o arquivo temporário
        if enviar_com_midia and extensao == '.webp' and midia_para_enviar:
            try:
                os.remove(midia_para_enviar)
            except Exception as e:
                print(f"Erro ao remover arquivo temporário: {e}")
        await client.disconnect()


# -----------------------------------------------------------------------------
# Função para agendar os posts com base em horários específicos
# -----------------------------------------------------------------------------
def agendar_posts(config, posts, midias):
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
        await postar_mensagem(config, posts, midias)

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


# -----------------------------------------------------------------------------
# Função para modo de teste: enviar posts a cada 10 segundos
# -----------------------------------------------------------------------------
async def modo_teste(config, posts, midias):
    while True:
        await postar_mensagem(config, posts, midias)
        # Intervalo de 10 segundos entre cada post no modo de teste
        await asyncio.sleep(10)


# -----------------------------------------------------------------------------
# Função principal que coordena o fluxo do programa
# -----------------------------------------------------------------------------
def main():
    config = carregar_config()
    posts = carregar_posts()
    midias = listar_imagens()

    if not posts:
        print("Erro: Nenhum post encontrado no arquivo posts.txt.")
        return

    if not midias:
        print("Erro: Nenhuma mídia (imagem/vídeo) encontrada na pasta 'imagens'.")
        return

    # Se test_mode estiver ativo, executa o modo de teste
    if config.get('test_mode', False):
        print("Modo de teste ativado. Enviaremos posts a cada 10 segundos, indefinidamente.")
        try:
            asyncio.run(modo_teste(config, posts, midias))
        except (KeyboardInterrupt, SystemExit):
            print("Bot interrompido pelo usuário.")
    else:
        # Caso contrário, segue a lógica de agendamento
        agendar_posts(config, posts, midias)


# -----------------------------------------------------------------------------
# Ponto de entrada do script
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    main()

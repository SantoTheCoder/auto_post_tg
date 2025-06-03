# kriasys.py
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

            # -----------------------------------------------------------------------------
            # Verificar e atribuir default para postar_dias_da_semana
            # -----------------------------------------------------------------------------
            if 'postar_dias_da_semana' in config:
                if not isinstance(config['postar_dias_da_semana'], bool):
                    print("Erro: 'postar_dias_da_semana' deve ser um valor booleano (true ou false).")
                    exit(1)
                if config['postar_dias_da_semana']:
                    if 'numero_de_dias_por_semana' not in config:
                        print("Erro: 'numero_de_dias_por_semana' deve ser definido quando 'postar_dias_da_semana' está ativo.")
                        exit(1)
                    if not isinstance(config['numero_de_dias_por_semana'], int) or not (1 <= config['numero_de_dias_por_semana'] <=7):
                        print("Erro: 'numero_de_dias_por_semana' deve ser um inteiro entre 1 e 7.")
                        exit(1)
            else:
                # Definir padrão se não existir
                config['postar_dias_da_semana'] = False

            # -----------------------------------------------------------------------------
            # "dias_exatos" (novo) é opcional. Se existir, deve ser lista de strings.
            # -----------------------------------------------------------------------------
            if 'dias_exatos' in config:
                if not isinstance(config['dias_exatos'], list):
                    print("Erro: 'dias_exatos' deve ser uma lista de strings (ex: ['terca','quinta']).")
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

# -----------------------------------------------------------------------------
# Função para ler e parsear os posts do arquivo posts.txt, capturando o tipo
# -----------------------------------------------------------------------------
def carregar_posts(posts_path='posts.txt'):
    try:
        with open(posts_path, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        # Expressão regular para capturar o tipo e o texto entre -- INICIO tipo e -- FIM
        padrao = r'-- INICIO (\w+)\s*(.*?)\s*-- FIM'
        matches = re.findall(padrao, conteudo, re.DOTALL)
        posts = [(tipo.strip(), post.strip()) for tipo, post in matches]
        if not posts:
            print("Erro: Nenhum post encontrado no arquivo posts.txt.")
            exit(1)
        return posts
    except FileNotFoundError:
        print(f"Erro: O arquivo {posts_path} não foi encontrado.")
        exit(1)

# -----------------------------------------------------------------------------
# Função para listar mídias (imagens e vídeos) em uma pasta específica
# -----------------------------------------------------------------------------
def listar_imagens(pasta):
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
        :param state_key: String para diferenciar o estado ('posts', 'midias_usuario', 'midias_revenda').
        """
        self.state_key = state_key
        self.itens_original = itens.copy()
        
        # Carrega o estado
        self.state = load_state()
        
        # Se não existir algo no estado para essa key, cria um novo shuffle
        if self.state_key not in self.state:
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
# Função para parsear os nomes de dias exatos em formato CronTrigger (0 a 6)
# -----------------------------------------------------------------------------
def parse_dias_exatos(dias_lista):
    """
    Converte strings como 'segunda', 'terca', 'quarta', etc. 
    em números (0=segunda, 1=terça, ... 6=domingo).
    Se algum dia for inválido, levanta ValueError.
    """
    mapping = {
        # Você pode expandir se quiser abreviações:
        'seg': 0, 'segunda': 0, 'segunda-feira': 0,
        'ter': 1, 'terca': 1, 'terça': 1, 'terça-feira': 1,
        'qua': 2, 'quarta': 2, 'quarta-feira': 2,
        'qui': 3, 'quinta': 3, 'quinta-feira': 3,
        'sex': 4, 'sexta': 4, 'sexta-feira': 4,
        'sab': 5, 'sábado': 5, 'sabado': 5,
        'dom': 6, 'domingo': 6
    }
    result = []
    for dia in dias_lista:
        dia_lower = dia.strip().lower()
        if dia_lower in mapping:
            result.append(mapping[dia_lower])
        else:
            raise ValueError(f"Dia da semana inválido no config: '{dia}'")
    # Remover duplicados e retornar
    return list(set(result))

# -----------------------------------------------------------------------------
# Função principal para postar a mensagem com a imagem ou vídeo correspondente ao tipo
# -----------------------------------------------------------------------------
async def postar_mensagem(config, posts, midias_usuario, midias_revenda):
    # Inicializar os selecionadores aleatórios se ainda não existirem
    if not hasattr(postar_mensagem, "selecionador_posts"):
        postar_mensagem.selecionador_posts = SelecionadorAleatorio(posts, 'posts')
    if not hasattr(postar_mensagem, "selecionador_midias_usuario"):
        postar_mensagem.selecionador_midias_usuario = SelecionadorAleatorio(midias_usuario, 'midias_usuario')
    if not hasattr(postar_mensagem, "selecionador_midias_revenda"):
        postar_mensagem.selecionador_midias_revenda = SelecionadorAleatorio(midias_revenda, 'midias_revenda')

    # Selecionar um post aleatoriamente (sem repetir até ciclo fechar)
    tipo, post_selecionado = postar_mensagem.selecionador_posts.proximo()

    # Selecionar a mídia correspondente ao tipo do post
    if tipo == 'usuario':
        midia_selecionada = postar_mensagem.selecionador_midias_usuario.proximo()
    elif tipo == 'revenda':
        midia_selecionada = postar_mensagem.selecionador_midias_revenda.proximo()
    else:
        print(f"Tipo de post inválido: {tipo}. Pulando este post.")
        return

    print(f"Post selecionado: {post_selecionado[:50]}... (Tipo: {tipo})")
    print(f"Mídia selecionada: {midia_selecionada}")

    # Verificar o comprimento do post
    if len(post_selecionado) > 1300:
        enviar_com_midia = False
        print("O post excede 1300 caracteres. Será enviado sem a imagem.")
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
# Função para agendar os posts com base em horários específicos,
# agora com a variação para mais ou para menos.
# -----------------------------------------------------------------------------
def agendar_posts(config, posts, midias_usuario, midias_revenda):
    scheduler = AsyncIOScheduler()

    def parse_time(time_str):
        """Converte uma string de horário 'HH:MM' para hora e minuto inteiros."""
        try:
            hora, minuto = map(int, time_str.split(':'))
            return hora, minuto
        except ValueError:
            print(f"Erro: Horário '{time_str}' está no formato inválido. Use 'HH:MM'.")
            exit(1)

    postar_dias = config.get('postar_dias_da_semana', False)

    # -----------------------------------------------------------------------------
    # Se postar_dias_da_semana = True, definimos a lista de dias_selecionados
    # -----------------------------------------------------------------------------
    if postar_dias:
        # Se dias_exatos estiver definido e não for vazio, usamos ele;
        # caso contrário, sorteamos aleatoriamente numero_de_dias_por_semana
        dias_exatos = config.get('dias_exatos', [])
        if dias_exatos:
            # Converter para índices 0..6
            try:
                dias_selecionados = parse_dias_exatos(dias_exatos)
            except ValueError as e:
                print(f"Erro ao interpretar dias_exatos: {e}")
                exit(1)
            print(f"Dias exatos definidos no config: {dias_exatos} (índices: {dias_selecionados})")
        else:
            numero_dias_semana = config.get('numero_de_dias_por_semana', 7)
            dias_disponiveis = list(range(0,7))  # 0=segunda, 6=domingo
            dias_selecionados = random.sample(dias_disponiveis, numero_dias_semana)
            nomes_dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
            print("Dias selecionados aleatoriamente para postar esta semana: " +
                  ", ".join(nomes_dias[d] for d in dias_selecionados))
    else:
        # Se postar_dias_da_semana = False, iremos postar todos os dias (0..6)
        dias_selecionados = list(range(0,7))

    # Wrapper que será chamado no horário programado
    async def job_wrapper(hora_programada, minuto_programado):
        # Valor total em minutos do horário programado
        total_scheduled_minutes = hora_programada * 60 + minuto_programado

        # Define o intervalo de variação (tanto para mais quanto para menos).
        variation = config['variation_minutes']

        # Cálculo do horário "mais cedo" possível (earliest_minutes)
        earliest_minutes = total_scheduled_minutes - variation
        if earliest_minutes < 0:
            earliest_minutes = 0

        # Quanto de atraso aleatório iremos aplicar (0 até variation*2)
        max_delay = variation * 2
        random_delay = random.randint(0, max_delay)

        print(f"[DEBUG] Horário base: {hora_programada:02d}:{minuto_programado:02d}")
        print(f"[DEBUG] Horário 'earliest' (minutos absolutos): {earliest_minutes}")
        print(f"[DEBUG] Variação ±{variation} min => delay sorteado: {random_delay} min")

        # Aguarda o delay sorteado para efetivamente postar
        await asyncio.sleep(random_delay * 60)

        # Finalmente, chama a função que posta
        await postar_mensagem(config, posts, midias_usuario, midias_revenda)

    # Para cada horário em scheduled_times, cria um job no scheduler
    for scheduled_time in config['scheduled_times']:
        hora, minuto = parse_time(scheduled_time)
        variation = config['variation_minutes']
        total_scheduled_minutes = hora * 60 + minuto
        earliest_minutes = total_scheduled_minutes - variation
        if earliest_minutes < 0:
            earliest_minutes = 0
        hour_earliest = earliest_minutes // 60
        minute_earliest = earliest_minutes % 60

        if postar_dias:
            # Agendar apenas para os dias 'dias_selecionados'
            for dia in dias_selecionados:
                trigger = CronTrigger(day_of_week=dia, hour=hour_earliest, minute=minute_earliest)
                scheduler.add_job(
                    job_wrapper,
                    trigger=trigger,
                    args=[hora, minuto],
                    name=f"Post semanal (var. ±{variation}) - {scheduled_time} - Dia {dia}"
                )
                print(f"Agendado: Post no dia {dia} (0=Seg,...,6=Dom) às {scheduled_time} ±{variation} min.")
        else:
            # Usamos CronTrigger para disparar diariamente
            trigger = CronTrigger(hour=hour_earliest, minute=minute_earliest)
            scheduler.add_job(
                job_wrapper,
                trigger=trigger,
                args=[hora, minuto],
                name=f"Post diário (var. ±{variation}) - {scheduled_time}"
            )
            print(f"Agendado: Post diário em torno de {scheduled_time} (±{variation} min).")

    # Iniciar o scheduler
    scheduler.start()
    print("Scheduler iniciado e funcionando. Aguarde os horários para postar...")

    # Manter o loop rodando
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        pass

# -----------------------------------------------------------------------------
# Função para modo de teste: enviar posts a cada 10 segundos
# -----------------------------------------------------------------------------
async def modo_teste(config, posts, midias_usuario, midias_revenda):
    while True:
        await postar_mensagem(config, posts, midias_usuario, midias_revenda)
        # Intervalo de 10 segundos entre cada post no modo de teste
        await asyncio.sleep(10)

# -----------------------------------------------------------------------------
# Função principal que coordena o fluxo do programa
# -----------------------------------------------------------------------------
def main():
    config = carregar_config()
    posts = carregar_posts()
    midias_usuario = listar_imagens('imagens_usuario')
    midias_revenda = listar_imagens('imagens_revenda')

    if not posts:
        print("Erro: Nenhum post encontrado no arquivo posts.txt.")
        return

    if not midias_usuario:
        print("Erro: Nenhuma mídia encontrada na pasta 'imagens_usuario'.")
        return

    if not midias_revenda:
        print("Erro: Nenhuma mídia encontrada na pasta 'imagens_revenda'.")
        return

    # Se test_mode estiver ativo, executa o modo de teste
    if config.get('test_mode', False):
        print("Modo de teste ativado. Enviaremos posts a cada 10 segundos, indefinidamente.")
        try:
            asyncio.run(modo_teste(config, posts, midias_usuario, midias_revenda))
        except (KeyboardInterrupt, SystemExit):
            print("Bot interrompido pelo usuário.")
    else:
        # Caso contrário, segue a lógica de agendamento
        agendar_posts(config, posts, midias_usuario, midias_revenda)

# -----------------------------------------------------------------------------
# Ponto de entrada do script
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    main()
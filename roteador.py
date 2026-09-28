import uuid
from dataclasses import dataclass, field
from typing import Dict, Any
import socket
import json
import time
import subprocess
import ipaddress
import builtins
from datetime import datetime
import os
import resource

METRICA_INFINITA = 16
TEMPO_UPDATE = 15

# print custom com timestamp
def print_com_timestamp(*args, **kwargs):
    # Formata a data e hora no formato: dd-MM-yyyy hh:mm:ss
    tempo = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    builtins.print(f"\n[{tempo}] - ", *args, **kwargs)

print = print_com_timestamp

@dataclass
class Roteador:
    porta: int
    id_roteador: str = field(default_factory=lambda: str(uuid.uuid4()))
    tabela_rotas: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # tabela de dados duplos, vai ter os dados da segunda melhor rota, usado para redundançia e quedas de link
    tabela_backup: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pacotes_enviados_total: int = 0
    pacotes_recebidos_total: int = 0
    bytes_enviados_total: int = 0

    bytes_enviados: int = 0
    pacotes_enviados: int = 0
    pacotes_recebidos: int = 0
    pacotes_controle: int = 0

    delays_vizinhos: Dict[str, list] = field(default_factory=dict)


def carregar_rotas_locais(node: Roteador):
    """Lê as redes diretamente conectadas das interfaces do Linux"""
    print("Carregando rotas locais...")
    try:
        # Pega as rotas do kernel ignora a rede local do c
        saida = subprocess.check_output(["ip", "-o", "route", "show", "proto", "kernel"]).decode('utf-8')
        for linha in saida.splitlines():
            partes = linha.split()
            rede = partes[0]  # Ex: 10.0.1.0/30 ou 192.168.5.0/24

            # Ignora a rede eth0 do Docker (172.20.20.0/24)
            if not rede.startswith("172.") and rede != "default":
                node.tabela_rotas[rede] = {
                    "next_hop": "0.0.0.0",  # Indica que é local
                    "metrica": 0,
                    "id_origem": node.id_roteador,
                    "ultimo_update": time.time()
                }
                print(f"    -> Rede local detectada: {rede}")
    except Exception as e:
        print(f"[!] Erro ao ler rotas locais: {e}")


def injetar_rota_sistema(rede_destino: str, next_hop: str):
    # injeta uma rota no sistema
    comando_lista = ["ip", "route", "replace", rede_destino, "via", next_hop]
    print(f"Instalando no kernel: {' '.join(comando_lista)}")

    try:
        resultado = subprocess.run(
            comando_lista,
            capture_output=True,
            text=True,
            check=False
        )

        if resultado.returncode != 0:
            print(f"Aviso do kernel ao injetar rota: {resultado.stderr.strip()}")

    except Exception as e:
        print(f"Erro fatal no subprocess: {e}")


def escutar_rotas(node: Roteador):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", node.porta))
    print(f"Escutando atualizações na porta UDP {node.porta}...")

    while True:
        dados, addr = sock.recvfrom(2048)
        try:
            ip_vizinho = addr[0]
            # --- BLOQUEIO DA REDE DE GERÊNCIA DO DOCKER ---
            if ip_vizinho.startswith("172."):
                continue

            mensagem = json.loads(dados.decode('utf-8'))
            redes_recebidas = mensagem.get("minhas_redes", {})

            hora_envio = mensagem.get("timestamp_envio", time.time())
            delay_ms = (time.time() - hora_envio) * 1000
            node.pacotes_recebidos += 1
            node.pacotes_recebidos_total += 1

            if ip_vizinho not in node.delays_vizinhos:
                node.delays_vizinhos[ip_vizinho] = []
            node.delays_vizinhos[ip_vizinho].append(delay_ms)

            for rede_destino, info in redes_recebidas.items():
                metrica_recebida = info["metrica"]
                id_origem = info["id_origem"]

                # Adiciona custo do enlace apenas se não for infinito
                if metrica_recebida < METRICA_INFINITA:
                    metrica_recebida += 1

# validar qual parte desse código aqui, mas o ajuste para quando a rede retorna

                # Se a rede já existe na nossa tabela principal
                if rede_destino in node.tabela_rotas:
                    rota_atual = node.tabela_rotas[rede_destino]

                    # --- REGRAS DE MÉTRICA ---
                    if rota_atual["next_hop"] == ip_vizinho:

                        # CASO 1: Rota caiu (Poisoning)
                        if metrica_recebida >= METRICA_INFINITA:
                            print(f"Rota para {rede_destino} via {ip_vizinho} falhou (Métrica Infinita)!")

                            # valida se o destino existe na tabela de backup, se existe usa a rota de backup
                            # isso impede que o router fique sem uma rota por muito tempo
                            if rede_destino in node.tabela_backup and len(node.tabela_backup[rede_destino]) > 0:
                                print(f"Promovendo rota de backup para {rede_destino}...")
                                melhor_vizinho_backup = min(
                                    node.tabela_backup[rede_destino],
                                    key=lambda v: node.tabela_backup[rede_destino][v]["metrica"]
                                )
                                nova_rota = node.tabela_backup[rede_destino].pop(melhor_vizinho_backup)
                                nova_rota["next_hop"] = melhor_vizinho_backup
                                nova_rota["ultimo_update"] = time.time()
                                node.tabela_rotas[rede_destino] = nova_rota
                                injetar_rota_sistema(rede_destino, melhor_vizinho_backup)
                            else:
                                print("Sem rotas de backup. Alterando a Rota para peso infinito")
                                node.tabela_rotas[rede_destino]["metrica"] = METRICA_INFINITA
                                subprocess.run(["ip", "route", "del", rede_destino, "via", ip_vizinho], check=False)

                        # CASO 2: Recebeu a mesma métrica do original, mantém o valor e atualizar o timer
                        elif metrica_recebida == rota_atual["metrica"]:
                            node.tabela_rotas[rede_destino]["ultimo_update"] = time.time()

                        # CASO 3: A rota da origem piorou, usa a nova rota da origem, pois ele era o melhor antes
                        # confia 100% nele
                        elif metrica_recebida > rota_atual["metrica"]:
                            print(f"Métrica degradada de {rota_atual['metrica']} para {metrica_recebida} na rede {rede_destino} via {ip_vizinho}")
                            node.tabela_rotas[rede_destino]["metrica"] = metrica_recebida
                            node.tabela_rotas[rede_destino]["ultimo_update"] = time.time()


                    # CASO 4: Outra interface ofereceu uma rota melhor
                    elif metrica_recebida < rota_atual["metrica"]:
                        if rede_destino not in node.tabela_backup:
                            node.tabela_backup[rede_destino] = {}
                        node.tabela_backup[rede_destino][rota_atual["next_hop"]] = rota_atual

                        node.tabela_rotas[rede_destino] = {
                            "next_hop": ip_vizinho,
                            "metrica": metrica_recebida,
                            "id_origem": id_origem,
                            "ultimo_update": time.time()
                        }
                        injetar_rota_sistema(rede_destino, ip_vizinho)

                    # CASO 5: Outra interface ofereceu uma rota PIOR (Guardar no Backup)
                    # isso é usado para no caso de uma interface cair para sempre ter um caminho
                    elif rota_atual["metrica"] < metrica_recebida < METRICA_INFINITA:
                        if rede_destino not in node.tabela_backup:
                            node.tabela_backup[rede_destino] = {}
                        node.tabela_backup[rede_destino][ip_vizinho] = {
                            "metrica": metrica_recebida,
                            "id_origem": id_origem
                        }

                # --- CASO 6: Nova rota, adiciona na tabela
                else:
                    # Só aceita se a métrica inicial for de um link ativo
                    if metrica_recebida < METRICA_INFINITA:
                        print(f"Nova rede descoberta: {rede_destino} via {ip_vizinho}")
                        node.tabela_rotas[rede_destino] = {
                            "next_hop": ip_vizinho,
                            "metrica": metrica_recebida,
                            "id_origem": id_origem,
                            "ultimo_update": time.time()
                        }
                        injetar_rota_sistema(rede_destino, ip_vizinho)

        except Exception as e:
            print(f"erro: {e}")


def validar_link(ip_vizinho: str) -> bool:
    try:
        # envia pacote(s) de ping com um timeout para validar se o link ainda esta ativo
        # -c 2 (2 pacote), -W 1 (timeout de 1 segundo)
        resultado = subprocess.run(
            ["ping", "-c", "2", "-W", "1", ip_vizinho],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        return resultado.returncode == 0
    except Exception as e:
        print(f"erro: {e}")
        return False


def anunciar_rotas(node: Roteador):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    while True:

        dados_envio = {
            "minhas_redes": node.tabela_rotas,
            "timestamp_envio": time.time()
        }
        meu_anuncio = json.dumps(dados_envio)

        for rede, info in node.tabela_rotas.items():
            # Anuncia a tabela para os nós ligados
            if info["metrica"] == 0:
                try:
                    rede_obj = ipaddress.IPv4Network(rede, strict=False)
                    ip_broadcast = str(rede_obj.broadcast_address)
                    print(f"anunciando rotas pela porta {node.porta} na rede {ip_broadcast}")

                    # Envia para os ips de broadcast de cada interface, um erro no docker acontece se não for
                    # feito um sendo para o ip correto da interface
                    payload_bytes = meu_anuncio.encode('utf-8')
                    sock.sendto(meu_anuncio.encode('utf-8'), (ip_broadcast, node.porta))

                    node.pacotes_enviados_total += 1
                    node.pacotes_enviados += 1
                    node.bytes_enviados += len(payload_bytes)
                    node.bytes_enviados_total += len(payload_bytes)
                except Exception as e:
                    pass
        time.sleep(TEMPO_UPDATE)


def verificar_timeouts(node: Roteador):
    timeout = 20
    print(f"Iniciando monitoramento de timeouts ({timeout})...")
    while True:
        agora = time.time()
        rotas_cairam = []

        # 1. Varredura para encontrar rotas expiradas
        for rede, info in list(node.tabela_rotas.items()):
            # só identifica rotas de vizinhos que não tem tamanho 0 e que ainda não estão caídos
            if 0 < info["metrica"] < METRICA_INFINITA:
                if (agora - info["ultimo_update"]) > timeout:
                    print(f"Alerta: Sem atualizações de {rede} por {timeout}s. Validando link via ping...")

                    if not validar_link(info["next_hop"]):
                        rotas_cairam.append((rede, info["next_hop"]))
                    else:
                        print(f"Ping OK. Roteador {info['next_hop']} está sobrecarregado, mas ativo.")
                        # Renova o timer para não pingar a cada 5 segundos
                        node.tabela_rotas[rede]["ultimo_update"] = agora

                    node.pacotes_controle = node.pacotes_controle + 2

        # 2. para cada rota que caiu, a tabela é atualizada usando a tabela de backup para não ficar sem uma rota
        # caso a rota não exista na tabela muda a métrica para infinito e deleta a rota do sistema
        for rede_destino, ip_vizinho in rotas_cairam:
            print(f"Link para {ip_vizinho} falhou!")

            if rede_destino in node.tabela_backup and len(node.tabela_backup[rede_destino]) > 0:
                print(f"Promovendo rota de backup para {rede_destino}...")
                melhor_vizinho_backup = min(
                    node.tabela_backup[rede_destino],
                    key=lambda v: node.tabela_backup[rede_destino][v]["metrica"]
                )

                # atualiza a rota atual com a do backup
                nova_rota = node.tabela_backup[rede_destino].pop(melhor_vizinho_backup)
                nova_rota["next_hop"] = melhor_vizinho_backup
                nova_rota["ultimo_update"] = time.time()
                node.tabela_rotas[rede_destino] = nova_rota

                # injeta a nova rota no sistema
                injetar_rota_sistema(rede_destino, melhor_vizinho_backup)

            else:
                print(f"Sem rotas de backup. Envenenando rota {rede_destino}...")
                node.tabela_rotas[rede_destino]["metrica"] = METRICA_INFINITA
                subprocess.run(["ip", "route", "del", rede_destino, "via", ip_vizinho], check=False)

        time.sleep(5)


def monitorar_metricas(node: Roteador):
    print("Iniciando coleta de métricas...")
    intervalo = 10

    while True:
        time.sleep(intervalo)

        # 1. Tamanho da Tabela
        tamanho_tabela = len(node.tabela_rotas)
        tamanho_tabela_backup = len(node.tabela_backup)

        bytes_tabela_principal = len(json.dumps(node.tabela_rotas).encode('utf-8'))
        bytes_tabela_backup = len(json.dumps(node.tabela_backup).encode('utf-8'))
        bytes_totais = bytes_tabela_principal + bytes_tabela_backup

        # 2. Taxas de Transmissão (Ciclo)
        taxa_tx_bps = (node.bytes_enviados * 8) / intervalo
        tx_pps = node.pacotes_enviados / intervalo  # Pacotes por segundo enviados
        rx_pps = node.pacotes_recebidos / intervalo  # Pacotes por segundo recebidos

        # 3. Cálculo da Média de Delay
        delays_medios = []
        for vizinho, lista_delays in node.delays_vizinhos.items():
            if lista_delays:
                media = sum(lista_delays) / len(lista_delays)
                delays_medios.append(f"{vizinho}: {media:.2f}ms")

        texto_delays = " | ".join(delays_medios) if delays_medios else "Sem dados"

        # 4. Memória RAM (Linux Resident Set Size)
        uso_memoria_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        print(f"=== TELEMETRIA (10s) ===")
        print(f" -> Tabela: {tamanho_tabela} rotas ativas ({bytes_tabela_principal} bytes)")
        print(f" -> Backup: {tamanho_tabela_backup} rotas de backup ({bytes_tabela_backup} bytes)")
        print(f" -> Total Tabelas: {tamanho_tabela_backup + tamanho_tabela} total de rotas ({bytes_totais} bytes)")
        print(f" -> Tráfego: Tx {taxa_tx_bps:.2f} bps | Tx {tx_pps:.1f} pps | Rx {rx_pps:.1f} pps")
        print(f" -> Controle: {node.pacotes_controle} Pkt Enviados")
        print(f" -> Ciclo: {node.pacotes_enviados} Pkt Enviados | {node.pacotes_recebidos} Pkt Recebidos")
        print(f" -> Totais: {node.pacotes_enviados_total} Pkt Enviados | {node.pacotes_recebidos_total} Pkt Recebidos")
        print(f" -> Memória: {uso_memoria_kb} KB")
        print(f" -> Delays Médios: {texto_delays}")
        print("========================\n")

        try:
            # Força o caminho para ser a mesma pasta do script roteador.py
            diretorio_script = os.path.dirname(os.path.abspath(__file__))
            arquivo_csv = os.path.join(diretorio_script, "metricas_customizado.csv")

            cabecalho_existe = os.path.exists(arquivo_csv)

            with open(arquivo_csv, "a", encoding="utf-8") as f:
                if not cabecalho_existe:
                    f.write(
                        "Timestamp,Tabela_Rotas,Memoria_KB,Updates_Enviados,Updates_Recebidos,Rotas_Backup,Bytes_Principal,Bytes_Backup,Pacotes_Controle,Taxa_TX_bps,Delay_Medio\n")

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                linha = f"{timestamp},{tamanho_tabela},{uso_memoria_kb},{node.pacotes_enviados},{node.pacotes_recebidos},{tamanho_tabela_backup},{bytes_tabela_principal},{bytes_tabela_backup},{node.pacotes_controle},{taxa_tx_bps:.2f},{texto_delays}\n"
                f.write(linha)

            # Imprime na tela o caminho exato onde o arquivo está sendo gerado
            print(f" [OK] CSV atualizado em: {arquivo_csv}")

        except Exception as e:
            print(f" [ERRO] Falha ao gravar CSV: {e}")
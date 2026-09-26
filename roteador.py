import uuid
from dataclasses import dataclass, field
from typing import Dict, Any
import socket
import json
import time
import os
import subprocess

METRICA_INFINITA = 16

@dataclass
class Roteador:
    porta: int
    id_roteador: str = field(default_factory=lambda: str(uuid.uuid4()))
    tabela_rotas: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # tabela de dados duplos, vai ter os dados da segunda melhor rota, usado para redundançia e quedas de link
    tabela_backup: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def injetar_rota_sistema(rede_destino: str, next_hop: str):
    comando = f"ip route replace {rede_destino} via {next_hop}"
    subprocess.run(comando)
    print(f"[+] Rota instalada: {comando}")

def injetar_rota_sistema_interface(rede_destino: str, next_hop: str, interface: str):
    comando = f"ip route replace {rede_destino} via {next_hop} dev {interface}"
    subprocess.run(comando)
    print(f"[+] Rota instalada: {comando}")


def escutar_rotas(node: Roteador):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", node.porta))
    print(f"[*] Escutando atualizações na porta UDP {node.porta}...")

    while True:
        dados, addr = sock.recvfrom(1024)
        ip_vizinho = addr[0]
        mensagem = json.loads(dados.decode('utf-8'))

        redes_recebidas = mensagem.get("minhas_redes", {})

        # Dentro do loop de escutar_vizinhos...
        for rede_destino, info in redes_recebidas.items():
            metrica_recebida = info["metrica"]
            id_origem = info["id_origem"]

            # Se for uma métrica normal, adicionamos 1 salto (nosso custo até o vizinho)
            if metrica_recebida < METRICA_INFINITA:
                metrica_recebida += 1

            # Se a rede já existe na nossa tabela principal
            if rede_destino in node.tabela_rotas:
                rota_atual = node.tabela_rotas[rede_destino]

                # --- CASO 1: O NOSSO VIZINHO PRINCIPAL AVISOU QUE A ROTA CAIU (POISONING) ---
                if rota_atual["next_hop"] == ip_vizinho and metrica_recebida >= METRICA_INFINITA:
                    print(f"[!] Rota para {rede_destino} via {ip_vizinho} falhou (Métrica Infinita)!")

                    # Verifica se temos uma rota de segurança na tabela de backup
                    if rede_destino in node.tabela_backup and len(node.tabela_backup[rede_destino]) > 0:
                        print(f"[*] Promovendo rota de backup para {rede_destino}...")

                        # Encontra o vizinho com a menor métrica no backup
                        melhor_vizinho_backup = min(
                            node.tabela_backup[rede_destino],
                            key=lambda v: node.tabela_backup[rede_destino][v]["metrica"]
                        )

                        # Remove do backup e move para a principal
                        nova_rota = node.tabela_backup[rede_destino].pop(melhor_vizinho_backup)
                        nova_rota["next_hop"] = melhor_vizinho_backup
                        node.tabela_rotas[rede_destino] = nova_rota

                        # Injeta a nova rota no Linux
                        injetar_rota_sistema(rede_destino, melhor_vizinho_backup)

                    else:
                        print("[-] Sem rotas de backup. Envenenando nossa própria rota...")
                        # Repassa a métrica infinita para que os outros vizinhos também saibam
                        node.tabela_rotas[rede_destino]["metrica"] = METRICA_INFINITA
                        subprocess.run(f"ip route del {rede_destino} via {ip_vizinho}")

                elif metrica_recebida < rota_atual["metrica"]:
                    # adiciona no backup
                    if rede_destino not in node.tabela_backup:
                        node.tabela_backup[rede_destino] = {}
                    node.tabela_backup[rede_destino][rota_atual["next_hop"]] = rota_atual

                    # Atualiza a principal
                    node.tabela_rotas[rede_destino] = {
                        "next_hop": ip_vizinho,
                        "metrica": metrica_recebida,
                        "id_origem": id_origem
                    }
                    injetar_rota_sistema(rede_destino, ip_vizinho)
                elif rota_atual["metrica"] < metrica_recebida < METRICA_INFINITA:
                    if rota_atual["next_hop"] != ip_vizinho:  # Não salva a si mesmo como backup
                        if rede_destino not in node.tabela_backup:
                            node.tabela_backup[rede_destino] = {}
                        node.tabela_backup[rede_destino][ip_vizinho] = {
                            "metrica": metrica_recebida,
                            "id_origem": id_origem
                        }


def validar_link(ip_vizinho: str) -> bool:
    try:
        # -c 1 (1 pacote), -W 1 (timeout de 1 segundo)
        resultado = subprocess.run(
            ["ping", "-c", "2", "-W", "1", ip_vizinho],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        return resultado.returncode == 0
    except Exception as e:
        return False


def anunciar_rotas(estado: Roteador):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    while True:
        meu_anuncio = json.dumps({"minhas_redes": estado.tabela_rotas})
        sock.sendto(meu_anuncio.encode('utf-8'), ("255.255.255.255", estado.porta))
        time.sleep(5)
import threading
import argparse
from roteador import Roteador, escutar_rotas, anunciar_rotas

if __name__ == "__main__":
    # cria parser para argumento de porta do roteador
    parser = argparse.ArgumentParser(description="Algoritmo de Roteamento Próprio")
    parser.add_argument(
        "-p", "--porta",
        type=int,
        default=9000,
        help="Porta UDP para troca de mensagens de roteamento (Padrão: 9000)"
    )

    args = parser.parse_args()
    node = Roteador(porta=args.porta)

    print(f"Iniciando Protocolo na porta: {node.porta} \n")

    # Inicia as threads passando a instância do dataclass como argumento
    t_rx = threading.Thread(target=escutar_rotas, args=(node,))
    t_tx = threading.Thread(target=anunciar_rotas, args=(node,))

    t_rx.start()
    t_tx.start()

    # Mantém a thread principal viva
    t_rx.join()
    t_tx.join()


# algoritmo é similar ao ripv2, mantem uma tabela secundária com o segundo melhor valor de cada rota
# ao não receber um update por mais de 30 s manda um ping para o roteador pela interface com erro, se não retornar nada
# dropa o link e faz o broadcast com custo infinito, os roteadores que antes achavam que a rota mais rapido mais rapida
# era pelo roteador que mandou infinito, agora usa o valor da tabela temporaria e manda para o roteador infinito a sua
# rota para manter a rede funcionando, isso só acontece se o roteador com a menor rota é o que envia o tamanho infinito
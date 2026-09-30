#!/bin/bash

CONTAINER="clab-lab-redes-r0"
ARQUIVO_CSV="metricas_rip.csv"
INTERVALO=10

if [ ! -f "$ARQUIVO_CSV" ]; then
    echo "Timestamp,Tabela_Rotas,Memoria_KB,Updates_Enviados,Updates_Recebidos" > "$ARQUIVO_CSV"
fi

echo "=== Iniciando Coleta de Métricas do RIP (Modo Kernel) ==="
echo "Monitorando o container: $CONTAINER"
echo "Salvando dados em: $ARQUIVO_CSV"
echo "Pressione Ctrl+C para parar."
echo "--------------------------------------------------------"

# Variáveis para guardar o total do ciclo anterior e calcular a taxa
ULTIMO_TX=""
ULTIMO_RX=""

while true; do
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

    # 1. Rotas
    ROTAS=$(docker exec $CONTAINER sh -c 'vtysh -c "show ip route rip" 2>/dev/null | grep "^R" | wc -l')
    if [ -z "$ROTAS" ]; then ROTAS=0; fi

    # 2. Memória (Lendo direto do arquivo de status do processo no Kernel)
    PID=$(docker exec $CONTAINER pidof ripd 2>/dev/null)
    if [ -n "$PID" ]; then
        # VmRSS é a memória física (RAM) real ocupada pelo processo
        MEMORIA_KB=$(docker exec $CONTAINER sh -c "cat /proc/$PID/status 2>/dev/null | grep VmRSS | awk '{print \$2}'")
    else
        MEMORIA_KB=0
    fi
    if [ -z "$MEMORIA_KB" ]; then MEMORIA_KB=0; fi

    # 3. Tráfego Tx/Rx (Lendo as estatísticas globais de UDP do Kernel)
    UDP_STATS=$(docker exec $CONTAINER sh -c "cat /proc/net/snmp 2>/dev/null | grep Udp: | tail -n 1")
    
    # Coluna 2 é InDatagrams (Rx), Coluna 5 é OutDatagrams (Tx)
    RX_TOTAL=$(echo "$UDP_STATS" | awk '{print $2}')
    TX_TOTAL=$(echo "$UDP_STATS" | awk '{print $5}')

    # Calcula quantos pacotes trafegaram APENAS nestes últimos 10 segundos
    if [ -z "$ULTIMO_RX" ]; then
        RX_PKT=0
        TX_PKT=0
    else
        RX_PKT=$((RX_TOTAL - ULTIMO_RX))
        TX_PKT=$((TX_TOTAL - ULTIMO_TX))
    fi

    # Salva o atual para a próxima rodada
    ULTIMO_RX=$RX_TOTAL
    ULTIMO_TX=$TX_TOTAL

    # 4. Salva e Imprime
    LINHA="$TIMESTAMP,$ROTAS,$MEMORIA_KB,$TX_PKT,$RX_PKT"
    echo "$LINHA" >> "$ARQUIVO_CSV"
    
    echo "[$TIMESTAMP] Rotas: $ROTAS | Memória: ${MEMORIA_KB}KB | Tx (10s): $TX_PKT pkt | Rx (10s): $RX_PKT pkt"

    sleep $INTERVALO
done

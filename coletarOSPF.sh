#!/bin/bash

CONTAINER="clab-lab-redes-r0"
ARQUIVO_CSV="metricas_ospf.csv"
INTERVALO=10

if [ ! -f "$ARQUIVO_CSV" ]; then
    echo "Timestamp,Tabela_Rotas,Memoria_KB,Execucoes_SPF,Total_LSAs" > "$ARQUIVO_CSV"
fi

echo "=== Iniciando Coleta de Métricas do OSPF (Modo SPF) ==="
echo "Monitorando o container: $CONTAINER"
echo "Salvando dados em: $ARQUIVO_CSV"
echo "Pressione Ctrl+C para parar."
echo "--------------------------------------------------------"

# Variável para saber quantos SPFs rodaram no ciclo de 10s
ULTIMO_SPF=""

while true; do
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

    # 1. Rotas OSPF (Conta as linhas que começam com O)
    ROTAS=$(docker exec $CONTAINER sh -c 'vtysh -c "show ip route ospf" 2>/dev/null | grep "^O" | wc -l')
    if [ -z "$ROTAS" ]; then ROTAS=0; fi

    # 2. Memória (Direto do Kernel)
    PID=$(docker exec $CONTAINER pidof ospfd 2>/dev/null)
    if [ -n "$PID" ]; then
        MEMORIA_KB=$(docker exec $CONTAINER sh -c "cat /proc/$PID/status 2>/dev/null | grep VmRSS | awk '{print \$2}'")
    else
        MEMORIA_KB=0
    fi
    if [ -z "$MEMORIA_KB" ]; then MEMORIA_KB=0; fi

    # 3. Métricas de Esforço do OSPF (Capturando do comando geral)
    STATUS_OSPF=$(docker exec $CONTAINER vtysh -c "show ip ospf" 2>/dev/null)
    
    # Extrai o número de vezes que o algoritmo SPF rodou
    SPF_TOTAL=$(echo "$STATUS_OSPF" | grep "SPF algorithm executed" | awk '{print $4}')
    if [ -z "$SPF_TOTAL" ]; then SPF_TOTAL=0; fi

    # Extrai a quantidade de LSAs na base de dados
    LSA_TOTAL=$(echo "$STATUS_OSPF" | grep "Number of LSA" | head -n 1 | awk '{print $4}')
    if [ -z "$LSA_TOTAL" ]; then LSA_TOTAL=0; fi

    # Calcula se o algoritmo rodou nestes últimos 10 segundos
    if [ -z "$ULTIMO_SPF" ]; then
        SPF_CICLO=0
    else
        SPF_CICLO=$((SPF_TOTAL - ULTIMO_SPF))
    fi
    ULTIMO_SPF=$SPF_TOTAL

    # 4. Salva no CSV e Imprime na tela
    LINHA="$TIMESTAMP,$ROTAS,$MEMORIA_KB,$SPF_CICLO,$LSA_TOTAL"
    echo "$LINHA" >> "$ARQUIVO_CSV"
    
    echo "[$TIMESTAMP] Rotas: $ROTAS | Mem. RAM: ${MEMORIA_KB}KB | LSAs Totais: $LSA_TOTAL | Novos Cálculos SPF (10s): $SPF_CICLO"

    sleep $INTERVALO
done

#!/usr/bin/env bash

set -e

ROUTERS=("r0" "r1" "r2" "r3" "r4" "r5")
LAB_FILE="lab.clab.yml"
TARGET_PROTO="$1"

usage() {
    echo "Uso: $0 [ospf | rip | none | custom]"
    echo "  ospf   : Ajusta para OSPF, destrói e recria o lab"
    echo "  rip    : Ajusta para RIP, destrói e recria o lab"
    echo "  none   : Desativa protocolos do FRR"
    echo "  custom : Protocolos inativados, usando protocolo customizado"
    exit 1
}

if [[ -z "$TARGET_PROTO" ]]; then
    usage
fi

case "$TARGET_PROTO" in
    ospf)
        echo "==> Configurando arquivos daemons para OSPF..."
        for r in "${ROUTERS[@]}"; do
            sed -i 's/^ospfd=.*/ospfd=yes/' "configs/$r/daemons"
            sed -i 's/^ripd=.*/ripd=no/' "configs/$r/daemons"
        done
        ;;
    rip)
        echo "==> Configurando arquivos daemons para RIP..."
        for r in "${ROUTERS[@]}"; do
            sed -i 's/^ospfd=.*/ospfd=no/' "configs/$r/daemons"
            sed -i 's/^ripd=.*/ripd=yes/' "configs/$r/daemons"
        done
        ;;
    none|custom)
        echo "==> Desativando protocolos dinâmicos do FRR..."
        for r in "${ROUTERS[@]}"; do
            sed -i 's/^ospfd=.*/ospfd=no/' "configs/$r/daemons"
            sed -i 's/^ripd=.*/ripd=no/' "configs/$r/daemons"
        done
        ;;
    *)
        usage
        ;;
esac

sudo chmod -R 777 configs/

echo "==> Destruindo topologia antiga e limpando interfaces..."
sudo clab destroy -t "$LAB_FILE" --cleanup

echo "==> Subindo topologia limpa..."
sudo clab deploy -t "$LAB_FILE"

echo "==> Aguardando o ambiente estabilizar (5 segundos)..."
sleep 5

# --- INICIALIZAÇÃO DO ALGORITMO CUSTOMIZADO ---
if [[ "$TARGET_PROTO" == "custom" ]]; then
    echo "==> Iniciando o Algoritmo Customizado em Python em background..."
    
    # Garante que a pasta de logs tem permissão de escrita
    sudo chmod -R 777 algoritmo_customizado/
    
    for r in "${ROUTERS[@]}"; do
        # O comando docker exec -d roda em segundo plano.
        # O sh -c redireciona o output (stdout e stderr) para um arquivo .log com o nome do roteador.
        docker exec -d "clab-lab-redes-$r" sh -c "python3 -u /opt/algoritmo_customizado/main.py > /opt/algoritmo_customizado/$r.log 2>&1"
    done
    
    echo "==> Algoritmo rodando! Verifique a pasta 'algoritmo_customizado/' para ver os logs de cada roteador."
else
    echo "==> Ambiente pronto com protocolo: $TARGET_PROTO"
fi

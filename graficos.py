import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as plt_dates
import os

# Arquivos gerados pelos scripts Bash e pelo Python
ARQUIVOS = {
    "RIPv2": "../metricas_rip.csv",
    "OSPF": "../metricas_ospf.csv",
    "CUSTOM": "../metricas_customizado.csv"
}

CORES = {"RIPv2": "blue", "OSPF": "orange", "CUSTOM": "green"}

# Cores padronizadas
def carregar_dados(nome_arquivo):
    if not os.path.exists(nome_arquivo):
        return None
    # Lê o CSV e converte a coluna de Timestamp para o formato de data real
    df = pd.read_csv(nome_arquivo)
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])

    # NOVO: Cria uma coluna de Tempo Relativo (Segundos decorridos desde o início do teste)
    df['Tempo_Relativo'] = (df['Timestamp'] - df['Timestamp'].iloc[0]).dt.total_seconds()
    return df


def preparar_dados(dados):
    for protocolo, df in dados.items():
        if df is None or df.empty:
            continue

        if 'Updates_Enviados' in df.columns and 'Updates_Recebidos' in df.columns:
            df['Esforco_Bruto'] = df['Updates_Enviados'] + df['Updates_Recebidos']
            df['Esforco_Medio'] = df['Esforco_Bruto'].rolling(window=3, min_periods=1).mean()
            df['Esforco_Acumulado'] = df['Esforco_Bruto'].cumsum()
            df['Label_Bruto'] = f"{protocolo} (Tx+Rx Bruto)"
            df['Label_Medio'] = f"{protocolo} (Média por Ciclo)"
            df['Label_Acum'] = f"{protocolo} (Pacotes Acumulados)"

        elif 'Execucoes_SPF' in df.columns:
            df['Esforco_Bruto'] = df['Execucoes_SPF']
            df['Esforco_Medio'] = df['Esforco_Bruto'].rolling(window=3, min_periods=1).mean()
            df['Esforco_Acumulado'] = df['Esforco_Bruto'].cumsum()
            df['Label_Bruto'] = f"{protocolo} (Recálculos SPF)"
            df['Label_Medio'] = f"{protocolo} (Média de SPF)"
            df['Label_Acum'] = f"{protocolo} (SPF Acumulado)"

    return dados


def formatar_e_salvar(nome_arquivo, titulo, ylabel):
    plt.title(titulo, fontweight='bold')
    plt.ylabel(ylabel)
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()

    # NOVO: O Eixo X agora é em Segundos, não precisamos do DateFormatter
    plt.xlabel("Tempo de Teste (Segundos decorridos)", fontweight='bold')

    plt.tight_layout()
    plt.savefig(nome_arquivo, dpi=300)
    plt.close()
    print(f"[+] Gerado: {nome_arquivo}")


def plotar_graficos():
    dados_brutos = {proto: carregar_dados(arq) for proto, arq in ARQUIVOS.items()}
    dados = preparar_dados(dados_brutos)

    print("Iniciando geração dos gráficos individuais alinhados...\n")

    # Gráfico 1: Convergência de Rotas
    plt.figure(figsize=(10, 5))
    for protocolo, df in dados.items():
        if df is not None and 'Tabela_Rotas' in df.columns:
            # Substituímos df['Timestamp'] por df['Tempo_Relativo'] em todos os gráficos
            plt.plot(df['Tempo_Relativo'], df['Tabela_Rotas'], label=protocolo, color=CORES[protocolo], linewidth=2,
                     marker='o', markersize=4)
    formatar_e_salvar("grafico_1_rotas.png", "1. Convergência da Tabela de Roteamento", "Rotas Ativas")

    # Gráfico 2: Consumo de Memória
    plt.figure(figsize=(10, 5))
    for protocolo, df in dados.items():
        if df is not None and 'Memoria_KB' in df.columns:
            plt.plot(df['Tempo_Relativo'], df['Memoria_KB'], label=protocolo, color=CORES[protocolo], linewidth=2)
    formatar_e_salvar("grafico_2_memoria.png", "2. Consumo de Memória (RAM)", "Memória (KB)")

    # Gráfico 3: Eventos Brutos por Ciclo
    plt.figure(figsize=(10, 5))
    for protocolo, df in dados.items():
        if df is not None and 'Esforco_Bruto' in df.columns:
            plt.plot(df['Tempo_Relativo'], df['Esforco_Bruto'], label=df['Label_Bruto'].iloc[0], color=CORES[protocolo],
                     linewidth=2, alpha=0.8)
    formatar_e_salvar("grafico_3_eventos_brutos.png", "3. Eventos Brutos por Ciclo (10s)", "Eventos / Pacotes (Bruto)")

    # Gráfico 4: Média de Eventos (Suavização)
    plt.figure(figsize=(10, 5))
    for protocolo, df in dados.items():
        if df is not None and 'Esforco_Medio' in df.columns:
            plt.plot(df['Tempo_Relativo'], df['Esforco_Medio'], label=df['Label_Medio'].iloc[0], color=CORES[protocolo],
                     linewidth=2, linestyle='--')
    formatar_e_salvar("grafico_4_eventos_media.png", "4. Média de Eventos (Suavização por Ciclo)", "Média de Eventos")

    # Gráfico 5: Total Acumulado no Tempo
    plt.figure(figsize=(10, 5))
    for protocolo, df in dados.items():
        if df is not None and 'Esforco_Acumulado' in df.columns:
            plt.plot(df['Tempo_Relativo'], df['Esforco_Acumulado'], label=df['Label_Acum'].iloc[0],
                     color=CORES[protocolo], linewidth=3)
    formatar_e_salvar("grafico_5_trafego_acumulado.png", "5. Tráfego Total Acumulado (Custo da Rede)",
                      "Total Acumulado")

    print("\nTodos os gráficos foram exportados e o tempo foi sincronizado com sucesso!")


if __name__ == "__main__":
    plotar_graficos()
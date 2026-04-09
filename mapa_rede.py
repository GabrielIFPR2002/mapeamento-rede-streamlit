import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import igraph as ig
import random
import hashlib

SENHA_ACESSO = st.secrets["SENHA_ACESSO"]


# =========================================================
# Utilidades
# =========================================================

def norm(x):
    """Padroniza texto: remove espaços e transforma vazio em NaN."""
    if pd.isna(x):
        return np.nan
    s = str(x).strip()
    return np.nan if s == "" else s


def obter_iniciais(nome_completo):
    """Gera iniciais ignorando conectivos comuns."""
    ignorar = {"de", "da", "do", "das", "dos", "e"}
    palavras = str(nome_completo).split()
    return "".join([p[0].upper() for p in palavras if p.lower() not in ignorar])


def assinatura_grafo(vertices, edges):
    """
    Cria uma assinatura estável do grafo.
    Se mudar conjunto de nós/arestas, recalculamos o layout (evita index out of range).
    """
    v_sorted = sorted(vertices)
    e_sorted = sorted((min(a, b), max(a, b)) for a, b in edges)
    payload = str((v_sorted, e_sorted)).encode("utf-8")
    return hashlib.md5(payload).hexdigest()


# =========================================================
# Mapas de atributos (Coordenação / PRN / Anônimo)
# =========================================================

def gerar_mapa_coordenacao(df):
    """
    Coordenação por pessoa com as colunas corretas:
    - Entrevistado -> 'Coordenação'
    - Alvo         -> 'Coord do Alvo'

    Se a pessoa aparecer em ambos, escolhe a coordenação mais frequente (modo).
    Em caso de empate, prioriza a coordenação do Entrevistado.
    """
    mapa = {}
    pessoas = pd.unique(df[["Entrevistado", "Alvo"]].values.ravel("K"))

    for p in pessoas:
        if pd.isna(p):
            continue

        coords_ent = df.loc[df["Entrevistado"] == p, "Coordenação"].dropna()
        coords_alv = df.loc[df["Alvo"] == p, "Coord do Alvo"].dropna()
        coords = pd.concat([coords_ent, coords_alv], ignore_index=True)

        if coords.empty:
            mapa[p] = "Sem Coordenação"
            continue

        cont = coords.value_counts()
        top = cont.max()
        candidatos = cont[cont == top].index.tolist()

        # Empate: tenta priorizar coord do entrevistado
        escolhido = None
        if not coords_ent.empty:
            modo_ent = coords_ent.value_counts().idxmax()
            if modo_ent in candidatos:
                escolhido = modo_ent

        mapa[p] = escolhido if escolhido else candidatos[0]

    return mapa


def gerar_mapa_prn(df):
    """
    PRN por pessoa:
    - Entrevistado -> 'PRN'
    - Alvo         -> 'PRN do Alvo'

    Preferência: se existir PRN como Entrevistado, usa ele; senão usa PRN do Alvo.
    """
    mapa = {}
    pessoas = pd.unique(df[["Entrevistado", "Alvo"]].values.ravel("K"))

    for p in pessoas:
        if pd.isna(p):
            continue

        prn_ent = df.loc[df["Entrevistado"] == p, "PRN"].dropna()
        if not prn_ent.empty:
            mapa[p] = str(prn_ent.iloc[0])
            continue

        prn_alv = df.loc[df["Alvo"] == p, "PRN do Alvo"].dropna()
        mapa[p] = str(prn_alv.iloc[0]) if not prn_alv.empty else "Desconhecido"

    return mapa


def gerar_mapa_anonimo(df):
    """Gera IDs anônimos por coordenação (estável via seed)."""
    random.seed(42)
    mapa = {}

    mapa_coord = gerar_mapa_coordenacao(df)
    pessoas = [
        p for p in pd.unique(df[["Entrevistado", "Alvo"]].values.ravel("K"))
        if pd.notna(p)
    ]

    agrupado = {}
    for p in pessoas:
        c = mapa_coord.get(p, "Sem Coordenação")
        agrupado.setdefault(c, []).append(p)

    for coord, lista in agrupado.items():
        lista = list(set(lista))
        random.shuffle(lista)
        for i, nome in enumerate(lista, start=1):
            mapa[nome] = {"id": i, "coordenacao": coord}

    return mapa


# =========================================================
# Gráfico de rede
# =========================================================

def criar_grafico_rede(df, mapa_anonimo, modo_anonimo=True):
    """
    modo_anonimo=True  -> Aba pública (anônima): mostra ID, sem PRN
    modo_anonimo=False -> Aba privada: mostra iniciais e PRN no hover
    """
    try:
        # Arestas válidas: só entra se entrevistado e alvo existirem
        edges = [(a, b) for a, b in zip(df["Entrevistado"], df["Alvo"]) if pd.notna(a) and pd.notna(b)]
        if not edges:
            st.warning("Nenhuma aresta válida encontrada no CSV.")
            return None

        g = ig.Graph.TupleList(edges, directed=False)

        # Layout: recalcula quando o grafo mudar (evita list index out of range)
        sig = assinatura_grafo(g.vs["name"], edges)
        if (
            "layout_posicoes" not in st.session_state
            or st.session_state.get("layout_assinatura") != sig
            or len(st.session_state["layout_posicoes"]) != g.vcount()
        ):
            random.seed(42)
            layout_obj = g.layout("fr")
            st.session_state["layout_posicoes"] = [(p[0], p[1]) for p in layout_obj]
            st.session_state["layout_assinatura"] = sig

        layout = st.session_state["layout_posicoes"]

        # Mapas auxiliares
        mapa_coord = gerar_mapa_coordenacao(df)
        mapa_prn = gerar_mapa_prn(df)

        # Paleta por coordenação
        coordenacoes = sorted(set(mapa_coord.values()))
        paleta = [
            "#e74c3c", "#3498db", "#2ecc71", "#e67e22", "#9b59b6",
            "#8d6e63", "#e91e63", "#7f8c8d", "#3d9970", "#16a085",
        ]
        mapa_cores = {c: paleta[i % len(paleta)] for i, c in enumerate(coordenacoes)}

        hover_info, tamanhos, cores_nos, texto = [], [], [], []

        for nome in g.vs["name"]:
            n_ent = int((df["Entrevistado"] == nome).sum())
            n_alv = int((df["Alvo"] == nome).sum())
            total = n_ent + n_alv

            # Tamanho cresce com quantas vezes foi indicado (alvo)
            tamanhos.append(15 + (n_alv * 5))

            coord = mapa_coord.get(nome, "Sem Coordenação")
            prn = mapa_prn.get(nome, "Desconhecido")
            cores_nos.append(mapa_cores.get(coord, "black"))

            if modo_anonimo:
                # Público/anônimo
                anon = mapa_anonimo.get(nome, {"id": "", "coordenacao": coord})
                texto.append(str(anon["id"]))
                hover_info.append(
                    f"<b>Usuário Anônimo</b><br>"
                    f"Identificador: {anon['coordenacao']}-{anon['id']}<br>"
                    f"Área: {anon['coordenacao']}<br>"
                    f"Total de Conexões: {total}<br>"
                    f"Como Entrevistado: {n_ent}<br>"
                    f"Como Alvo: {n_alv}"
                )
            else:
                # Privado (nome e PRN)
                texto.append(obter_iniciais(nome))
                hover_info.append(
                    f"<b>{nome}</b><br>"
                    f"Coordenação: {coord}<br>"
                    f"PRN: {prn}<br>"
                    f"Total de Conexões: {total}<br>"
                    f"Como Entrevistado: {n_ent}<br>"
                    f"Como Alvo: {n_alv}"
                )

        # Coordenadas dos nós
        node_x = [p[0] for p in layout]
        node_y = [p[1] for p in layout]

        # Coordenadas das arestas
        edge_x, edge_y = [], []
        for e in g.es:
            x1, y1 = layout[e.source]
            x2, y2 = layout[e.target]
            edge_x += [x1, x2, None]
            edge_y += [y1, y2, None]

        fig = go.Figure()

        # Arestas
        fig.add_trace(go.Scatter(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color="rgba(100,100,100,0.5)", width=1),
            hoverinfo="skip",
            showlegend=False
        ))

        # Nós
        fig.add_trace(go.Scatter(
            x=node_x, y=node_y,
            mode="markers+text",
            text=texto,
            hovertext=hover_info,
            textposition="middle center",
            textfont=dict(color="black", size=[max(10, int(s * 0.45)) for s in tamanhos]),
            marker=dict(size=tamanhos, color=cores_nos, line=dict(width=1, color="white")),
            hovertemplate="%{hovertext}<extra></extra>",
            showlegend=False
        ))

        # Legenda
        for c in coordenacoes:
            fig.add_trace(go.Scatter(
                x=[None], y=[None],
                mode="markers",
                marker=dict(size=10, color=mapa_cores.get(c, "black")),
                name=c,
                showlegend=True
            ))

        fig.update_layout(
            plot_bgcolor="white",
            height=700,
            hovermode="closest",
            margin=dict(l=10, r=10, t=10, b=10)
        )

        return fig

    except Exception as e:
        st.error(f"Erro ao gerar gráfico: {e}")
        return None


# =========================================================
# App Streamlit
# =========================================================

def main():
    st.set_page_config(page_title="Mapeamento de Rede", layout="wide")
    st.title("🕸️ Mapeamento de Relacionamentos")

    with st.sidebar:
        st.header("📋 Instruções")
        st.markdown("""
**Formato do arquivo CSV (colunas obrigatórias):**
- `Entrevistado`: pessoa que fez a indicação  
- `Alvo`: pessoa indicada  
- `Coordenação`: coordenação do entrevistado  
- `Coord do Alvo`: coordenação do alvo  
- `PRN`: PRN do entrevistado  
- `PRN do Alvo`: PRN do alvo  

**Exemplo :**
```csv
Entrevistado,Coordenação,PRN,Alvo,Coord do Alvo,PRN do Alvo
Maria Silva,Gerência Financeira, 123456, João Souza,Gerência TI,654321
```
        """)

    uploaded_file = st.file_uploader("📁 Carregue o arquivo CSV", type=["csv"])

    if uploaded_file:
        # Leitura com fallback de encoding
        try:
            df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(uploaded_file, encoding="latin1")

        # Remove espaços do cabeçalho (ex.: "PRN ")
        df.columns = df.columns.str.strip()

        colunas = {"Entrevistado", "Alvo", "Coordenação", "Coord do Alvo", "PRN", "PRN do Alvo"}
        if not colunas.issubset(df.columns):
            st.error(f"Colunas obrigatórias ausentes: {colunas - set(df.columns)}")
            return

        # Normaliza os campos principais
        for c in ["Entrevistado", "Alvo", "Coordenação", "Coord do Alvo", "PRN", "PRN do Alvo"]:
            df[c] = df[c].apply(norm)

        mapa_anonimo = gerar_mapa_anonimo(df)

        tab_publica, tab_privada = st.tabs(["🔒 Aba Pública (Anônima)", "🔑 Aba Privada (Nomes Reais)"])

        with tab_publica:
            st.subheader("Visualização Protegida")
            fig = criar_grafico_rede(df, mapa_anonimo, modo_anonimo=True)
            if fig:
                st.plotly_chart(fig, use_container_width=True)

        with tab_privada:
            st.subheader("Área Administrativa")
            senha = st.text_input("Insira a senha:", type="password")

            if senha == SENHA_ACESSO:
                st.success("Acesso liberado.")
                fig = criar_grafico_rede(df, mapa_anonimo, modo_anonimo=False)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                st.dataframe(df, use_container_width=True)
            elif senha != "":
                st.error("Senha incorreta.")


if __name__ == "__main__":
    main()

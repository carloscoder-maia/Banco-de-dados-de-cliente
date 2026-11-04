# -*- coding: utf-8 -*-
"""
Gestor de Estabelecimentos - Ferro Fundido
------------------------------------------
Interface moderna (CustomTkinter) para:
  - cadastrar Nome, Localização e Telefone
  - agrupar automaticamente por cidade
  - marcar estabelecimentos com potencial (página separada)
  - pesquisar na internet estabelecimentos de ferro fundido por região

Dependência: pip install customtkinter
Os dados ficam em  %APPDATA%\\GestorEstabelecimentos\\estabelecimentos.json
"""

import csv
import html
import json
import os
import queue
import re
import shutil
import sys
import threading
import urllib.parse
import urllib.request
import uuid
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

# ----------------------------------------------------------------------------
# Tema
# ----------------------------------------------------------------------------
BG = "#0B1220"
SIDEBAR = "#0F172A"
CARD = "#151F36"
CARD_HOVER = "#1C2845"
FIELD = "#0B1220"
ACCENT = "#F97316"
ACCENT_HOVER = "#EA580C"
TEXT = "#E5E7EB"
MUTED = "#94A3B8"
STAR = "#FBBF24"
OK = "#22C55E"
DANGER = "#EF4444"
DANGER_HOVER = "#B91C1C"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
       "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
       "SP", "SE", "TO"}


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------
def pasta_programa():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def pasta_dados():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    pasta = os.path.join(base, "GestorEstabelecimentos")
    os.makedirs(pasta, exist_ok=True)
    return pasta


ARQUIVO_DADOS = os.path.join(pasta_dados(), "estabelecimentos.json")


def carregar_dados():
    antigo = os.path.join(pasta_programa(), "estabelecimentos.json")
    if not os.path.exists(ARQUIVO_DADOS) and os.path.exists(antigo):
        try:
            shutil.copy(antigo, ARQUIVO_DADOS)  # importa dados da versão anterior
        except OSError:
            pass
    dados = []
    if os.path.exists(ARQUIVO_DADOS):
        try:
            with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except (json.JSONDecodeError, OSError):
            messagebox.showwarning("Aviso", "Não consegui ler o arquivo de dados. "
                                            "Começando com lista vazia.")
    for d in dados:
        d.setdefault("id", uuid.uuid4().hex)
        d.setdefault("potencial", False)
    return dados


def salvar_dados(dados):
    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def extrair_cidade(localizacao):
    """'Rua A, 123 - Centro, Sumaré - SP' -> 'Sumaré'"""
    if not localizacao:
        return "Sem cidade"
    partes = [p.strip() for p in re.split(r"[,\-–/|]", localizacao) if p.strip()]
    candidatas = [p for p in partes
                  if p.upper() not in UFS
                  and p.lower() not in ("brasil", "brazil")
                  and not re.search(r"\d", p)]
    return candidatas[-1].title() if candidatas else "Sem cidade"


REGEX_TEL = re.compile(r"(\(?\d{2}\)?\s?(?:9\s?)?\d{4}[-\s.]?\d{4})")


def pesquisar_web(consulta, max_resultados=25):
    """Pesquisa no DuckDuckGo (versão HTML)."""
    dados = urllib.parse.urlencode({"q": consulta, "kl": "br-pt"}).encode()
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/", data=dados,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        pagina = resp.read().decode("utf-8", errors="ignore")

    blocos = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?class="result__snippet"[^>]*>(.*?)</a>', pagina, flags=re.S)

    def limpar(s):
        return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()

    resultados = []
    for href, titulo, trecho in blocos[:max_resultados]:
        m = re.search(r"uddg=([^&]+)", href)
        url = urllib.parse.unquote(m.group(1)) if m else href
        if url.startswith("//"):
            url = "https:" + url
        titulo, trecho = limpar(titulo), limpar(trecho)
        tel = REGEX_TEL.search(trecho)
        resultados.append({"titulo": titulo, "url": url, "trecho": trecho,
                           "telefone": tel.group(1) if tel else ""})
    return resultados


# ----------------------------------------------------------------------------
# Componentes visuais reutilizáveis
# ----------------------------------------------------------------------------
def cabecalho(master, titulo, subtitulo=""):
    f = ctk.CTkFrame(master, fg_color="transparent")
    f.pack(fill="x", padx=30, pady=(26, 14))
    ctk.CTkLabel(f, text=titulo, font=ctk.CTkFont(size=28, weight="bold"),
                 text_color=TEXT, anchor="w").pack(fill="x")
    if subtitulo:
        ctk.CTkLabel(f, text=subtitulo, font=ctk.CTkFont(size=13),
                     text_color=MUTED, anchor="w").pack(fill="x", pady=(2, 0))
    return f


def botao(master, texto, comando, primario=True, largura=140, perigo=False):
    if perigo:
        cor, hov, txt = DANGER, DANGER_HOVER, "white"
    elif primario:
        cor, hov, txt = ACCENT, ACCENT_HOVER, "white"
    else:
        cor, hov, txt = "#26324F", "#33426A", TEXT
    return ctk.CTkButton(master, text=texto, command=comando, width=largura, height=38,
                         corner_radius=10, fg_color=cor, hover_color=hov, text_color=txt,
                         font=ctk.CTkFont(size=13, weight="bold"))


def card_estabelecimento(master, app, d):
    """Cartão de um estabelecimento com botões de potencial, copiar e excluir."""
    card = ctk.CTkFrame(master, fg_color=CARD, corner_radius=12)
    card.pack(fill="x", padx=4, pady=5)
    card.grid_columnconfigure(0, weight=1)

    info = ctk.CTkFrame(card, fg_color="transparent")
    info.grid(row=0, column=0, sticky="we", padx=16, pady=12)
    ctk.CTkLabel(info, text=d["nome"], font=ctk.CTkFont(size=15, weight="bold"),
                 text_color=TEXT, anchor="w", justify="left", wraplength=520).pack(fill="x")
    if d.get("local"):
        ctk.CTkLabel(info, text="📍  " + d["local"], font=ctk.CTkFont(size=12),
                     text_color=MUTED, anchor="w", justify="left", wraplength=520).pack(fill="x", pady=(3, 0))
    if d.get("tel"):
        ctk.CTkLabel(info, text="📞  " + d["tel"], font=ctk.CTkFont(size=12),
                     text_color=MUTED, anchor="w").pack(fill="x", pady=(2, 0))

    acoes = ctk.CTkFrame(card, fg_color="transparent")
    acoes.grid(row=0, column=1, padx=12)
    pot = d.get("potencial", False)
    ctk.CTkButton(acoes, text="★" if pot else "☆", width=40, height=38, corner_radius=10,
                  fg_color="#2A2410" if pot else "#26324F", hover_color="#3A3216" if pot else "#33426A",
                  text_color=STAR if pot else MUTED, font=ctk.CTkFont(size=20),
                  command=lambda: app.alternar_potencial(d["id"])).pack(side="left", padx=3)
    ctk.CTkButton(acoes, text="Copiar tel.", width=86, height=38, corner_radius=10,
                  fg_color="#26324F", hover_color="#33426A", text_color=TEXT,
                  font=ctk.CTkFont(size=12),
                  command=lambda: app.copiar(d.get("tel", ""))).pack(side="left", padx=3)
    ctk.CTkButton(acoes, text="✕", width=40, height=38, corner_radius=10,
                  fg_color="#26324F", hover_color=DANGER_HOVER, text_color=MUTED,
                  font=ctk.CTkFont(size=14, weight="bold"),
                  command=lambda: app.excluir(d["id"])).pack(side="left", padx=3)
    return card


# ----------------------------------------------------------------------------
# Páginas
# ----------------------------------------------------------------------------
class PaginaCadastro(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG)
        self.app = app
        cabecalho(self, "Novo cadastro", "Adicione estabelecimentos. A cidade é detectada pela localização.")

        # Estatísticas
        linha = ctk.CTkFrame(self, fg_color="transparent")
        linha.pack(fill="x", padx=30)
        self.lbl_total = self._stat(linha, "Estabelecimentos", ACCENT)
        self.lbl_cidades = self._stat(linha, "Cidades", "#38BDF8")
        self.lbl_pot = self._stat(linha, "Com potencial", STAR)

        # Formulário
        form = ctk.CTkFrame(self, fg_color=CARD, corner_radius=16)
        form.pack(fill="x", padx=30, pady=22)
        inner = ctk.CTkFrame(form, fg_color="transparent")
        inner.pack(fill="x", padx=24, pady=22)

        self.ent_nome = self._campo(inner, "Nome do estabelecimento", "Ex.: Fundição Silva Ltda.")
        self.ent_local = self._campo(inner, "Localização", "Ex.: Rua das Indústrias, 120 - Centro, Sumaré - SP")
        self.ent_tel = self._campo(inner, "Telefone", "Ex.: (19) 99999-9999")
        self.ent_cidade = self._campo(inner, "Cidade (opcional)", "Deixe vazio para detectar automaticamente")

        rodape = ctk.CTkFrame(inner, fg_color="transparent")
        rodape.pack(fill="x", pady=(10, 0))
        self.var_pot = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(rodape, text="Marcar como potencial", variable=self.var_pot,
                      progress_color=STAR, text_color=TEXT).pack(side="left")
        botao(rodape, "Salvar estabelecimento", self.salvar, largura=200).pack(side="right")
        self.lbl_msg = ctk.CTkLabel(inner, text="", text_color=OK, anchor="w")
        self.lbl_msg.pack(fill="x", pady=(10, 0))

        for e in (self.ent_nome, self.ent_local, self.ent_tel, self.ent_cidade):
            e.bind("<Return>", lambda ev: self.salvar())

    def _stat(self, master, rotulo, cor):
        c = ctk.CTkFrame(master, fg_color=CARD, corner_radius=16)
        c.pack(side="left", fill="x", expand=True, padx=(0, 14))
        v = ctk.CTkLabel(c, text="0", font=ctk.CTkFont(size=32, weight="bold"), text_color=cor)
        v.pack(anchor="w", padx=20, pady=(14, 0))
        ctk.CTkLabel(c, text=rotulo, text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="w", padx=20, pady=(0, 14))
        return v

    def _campo(self, master, rotulo, placeholder):
        ctk.CTkLabel(master, text=rotulo, text_color=MUTED, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(fill="x", pady=(8, 3))
        e = ctk.CTkEntry(master, placeholder_text=placeholder, height=42, corner_radius=10,
                         fg_color=FIELD, border_color="#26324F", border_width=1)
        e.pack(fill="x")
        return e

    def salvar(self):
        nome = self.ent_nome.get().strip()
        if not nome:
            self.lbl_msg.configure(text="Informe o nome do estabelecimento.", text_color=DANGER)
            return
        local = self.ent_local.get().strip()
        cidade = self.ent_cidade.get().strip() or extrair_cidade(local)
        self.app.adicionar(nome, local, self.ent_tel.get().strip(), cidade, self.var_pot.get())
        for e in (self.ent_nome, self.ent_local, self.ent_tel, self.ent_cidade):
            e.delete(0, "end")
        self.var_pot.set(False)
        self.ent_nome.focus()
        self.lbl_msg.configure(text=f"✓ “{nome}” salvo em {cidade.title()}.", text_color=OK)

    def render(self):
        d = self.app.dados
        self.lbl_total.configure(text=str(len(d)))
        self.lbl_cidades.configure(text=str(len({x["cidade"] for x in d})))
        self.lbl_pot.configure(text=str(sum(1 for x in d if x.get("potencial"))))


class ListaAgrupada(ctk.CTkFrame):
    """Lista de estabelecimentos agrupados por cidade, com busca e seções recolhíveis."""

    def __init__(self, master, app, titulo, subtitulo, so_potencial=False):
        super().__init__(master, fg_color=BG)
        self.app = app
        self.so_potencial = so_potencial
        self.fechadas = set()
        cabecalho(self, titulo, subtitulo)

        self.busca = ctk.CTkEntry(self, placeholder_text="🔍  Buscar por nome, cidade, endereço ou telefone...",
                                  height=42, corner_radius=10, fg_color=CARD, border_color="#26324F",
                                  border_width=1)
        self.busca.pack(fill="x", padx=30, pady=(0, 10))
        self.busca.bind("<KeyRelease>", lambda e: self.render())

        self.lista = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.lista.pack(fill="both", expand=True, padx=26, pady=(0, 16))

    def alternar_grupo(self, cidade):
        if cidade in self.fechadas:
            self.fechadas.discard(cidade)
        else:
            self.fechadas.add(cidade)
        self.render()

    def render(self):
        for w in self.lista.winfo_children():
            w.destroy()
        termo = self.busca.get().strip().lower()
        grupos = {}
        for d in self.app.dados:
            if self.so_potencial and not d.get("potencial"):
                continue
            texto = " ".join([d["nome"], d.get("local", ""), d.get("tel", ""), d["cidade"]]).lower()
            if termo and termo not in texto:
                continue
            grupos.setdefault(d["cidade"], []).append(d)

        if not grupos:
            msg = ("Nenhum estabelecimento com potencial ainda.\nClique na ☆ de um cartão para marcar."
                   if self.so_potencial else "Nenhum estabelecimento encontrado.")
            ctk.CTkLabel(self.lista, text=msg, text_color=MUTED, font=ctk.CTkFont(size=14),
                         justify="center").pack(pady=60)
            return

        for cidade in sorted(grupos):
            membros = sorted(grupos[cidade], key=lambda x: x["nome"].lower())
            aberta = cidade not in self.fechadas
            seta = "▾" if aberta else "▸"
            ctk.CTkButton(self.lista, text=f"{seta}   {cidade}   ·   {len(membros)}", anchor="w",
                          height=40, corner_radius=10, fg_color="#1B2745", hover_color="#26335A",
                          text_color=ACCENT, font=ctk.CTkFont(size=14, weight="bold"),
                          command=lambda c=cidade: self.alternar_grupo(c)).pack(fill="x", padx=4, pady=(12, 4))
            if aberta:
                for d in membros:
                    card_estabelecimento(self.lista, self.app, d)


class PaginaPesquisa(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG)
        self.app = app
        self.fila = queue.Queue()
        self.resultados = []
        cabecalho(self, "Pesquisar na internet",
                  "Encontre estabelecimentos por região e adicione-os à sua lista.")

        barra = ctk.CTkFrame(self, fg_color=CARD, corner_radius=16)
        barra.pack(fill="x", padx=30, pady=(0, 10))
        linha = ctk.CTkFrame(barra, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=16)

        self.ent_termo = ctk.CTkEntry(linha, width=200, height=42, corner_radius=10,
                                      fg_color=FIELD, border_color="#26324F", border_width=1)
        self.ent_termo.insert(0, "ferro fundido")
        self.ent_termo.pack(side="left", padx=(0, 10))
        self.ent_regiao = ctk.CTkEntry(linha, width=280, height=42, corner_radius=10,
                                       placeholder_text="Região (ex.: Sumaré, SP)",
                                       fg_color=FIELD, border_color="#26324F", border_width=1)
        self.ent_regiao.pack(side="left", padx=(0, 10))
        self.ent_regiao.bind("<Return>", lambda e: self.pesquisar())
        self.btn_pesq = botao(linha, "🔎  Pesquisar", self.pesquisar, largura=130)
        self.btn_pesq.pack(side="left", padx=(0, 10))
        botao(linha, "Abrir no Maps", self.abrir_maps, primario=False, largura=130).pack(side="left")

        self.lbl_status = ctk.CTkLabel(self, text="Digite a região e clique em Pesquisar.",
                                       text_color=MUTED, anchor="w")
        self.lbl_status.pack(fill="x", padx=32, pady=(0, 6))

        self.lista = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.lista.pack(fill="both", expand=True, padx=26, pady=(0, 16))

    def _consulta(self):
        termo, regiao = self.ent_termo.get().strip(), self.ent_regiao.get().strip()
        if not termo or not regiao:
            self.lbl_status.configure(text="Informe o termo e a região.", text_color=DANGER)
            return None, None
        return termo, regiao

    def abrir_maps(self):
        termo, regiao = self._consulta()
        if termo:
            webbrowser.open("https://www.google.com/maps/search/" + urllib.parse.quote(f"{termo} {regiao}"))

    def pesquisar(self):
        termo, regiao = self._consulta()
        if not termo:
            return
        consulta = f"{termo} {regiao} telefone endereço"
        self.lbl_status.configure(text=f"Pesquisando: {consulta} ...", text_color=MUTED)
        self.btn_pesq.configure(state="disabled")
        for w in self.lista.winfo_children():
            w.destroy()
        threading.Thread(target=self._worker, args=(consulta,), daemon=True).start()
        self.after(150, self._poll)

    def _worker(self, consulta):
        try:
            self.fila.put(("ok", pesquisar_web(consulta)))
        except Exception as e:
            self.fila.put(("erro", str(e)))

    def _poll(self):
        try:
            tipo, payload = self.fila.get_nowait()
        except queue.Empty:
            self.after(150, self._poll)
            return
        self.btn_pesq.configure(state="normal")
        if tipo == "erro":
            self.lbl_status.configure(
                text=f"Falha na pesquisa ({payload}). Tente o botão “Abrir no Maps”.", text_color=DANGER)
            return
        self.resultados = payload
        if not payload:
            self.lbl_status.configure(
                text="Nenhum resultado (o buscador pode ter bloqueado). Tente “Abrir no Maps”.",
                text_color=DANGER)
            return
        self.lbl_status.configure(text=f"{len(payload)} resultados encontrados.", text_color=OK)
        for r in payload:
            self._card_resultado(r)

    def _card_resultado(self, r):
        card = ctk.CTkFrame(self.lista, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", padx=4, pady=5)
        card.grid_columnconfigure(0, weight=1)
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=0, sticky="we", padx=16, pady=12)
        ctk.CTkLabel(info, text=r["titulo"], font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT,
                     anchor="w", justify="left", wraplength=560).pack(fill="x")
        dominio = urllib.parse.urlparse(r["url"]).netloc
        ctk.CTkLabel(info, text=dominio, text_color=ACCENT, font=ctk.CTkFont(size=11),
                     anchor="w").pack(fill="x", pady=(1, 3))
        ctk.CTkLabel(info, text=r["trecho"], text_color=MUTED, font=ctk.CTkFont(size=12),
                     anchor="w", justify="left", wraplength=560).pack(fill="x")
        if r["telefone"]:
            ctk.CTkLabel(info, text="📞  " + r["telefone"], text_color=OK,
                         font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(fill="x", pady=(4, 0))

        acoes = ctk.CTkFrame(card, fg_color="transparent")
        acoes.grid(row=0, column=1, padx=14)
        btn_add = botao(acoes, "+ Adicionar", None, largura=110)
        btn_add.configure(command=lambda: self.adicionar(r, btn_add))
        btn_add.pack(pady=(0, 6))
        botao(acoes, "Abrir página", lambda: webbrowser.open(r["url"]), primario=False, largura=110).pack()

    def adicionar(self, r, btn):
        regiao = self.ent_regiao.get().strip()
        self.app.adicionar(r["titulo"], regiao, r["telefone"], extrair_cidade(regiao), False)
        btn.configure(text="Adicionado ✓", state="disabled", fg_color="#166534")

    def render(self):
        pass


# ----------------------------------------------------------------------------
# Janela principal
# ----------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Gestor de Estabelecimentos · Ferro Fundido")
        self.geometry("1200x740")
        self.minsize(1020, 640)
        self.configure(fg_color=BG)
        self.dados = carregar_dados()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._montar_sidebar()
        self.area = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.area.grid(row=0, column=1, sticky="nsew")

        self.paginas = {
            "cadastro": PaginaCadastro(self.area, self),
            "cidades": ListaAgrupada(self.area, self, "Por cidade",
                                     "Todos os estabelecimentos agrupados por cidade."),
            "potencial": ListaAgrupada(self.area, self, "Com potencial",
                                       "Estabelecimentos marcados como potenciais, por cidade.",
                                       so_potencial=True),
            "pesquisa": PaginaPesquisa(self.area, self),
        }
        self.mostrar("cadastro")

    def _montar_sidebar(self):
        sb = ctk.CTkFrame(self, width=240, fg_color=SIDEBAR, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)

        ctk.CTkLabel(sb, text="⚙  FERRO FUNDIDO", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=ACCENT).pack(anchor="w", padx=24, pady=(30, 0))
        ctk.CTkLabel(sb, text="Gestor de estabelecimentos", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", padx=24, pady=(0, 28))

        self.botoes_nav = {}
        for chave, texto in (("cadastro", "＋   Cadastro"), ("cidades", "▦   Por cidade"),
                             ("potencial", "★   Com potencial"), ("pesquisa", "🔎   Pesquisar na web")):
            b = ctk.CTkButton(sb, text=texto, anchor="w", height=44, corner_radius=10,
                              fg_color="transparent", hover_color="#1B2745", text_color=TEXT,
                              font=ctk.CTkFont(size=14, weight="bold"),
                              command=lambda c=chave: self.mostrar(c))
            b.pack(fill="x", padx=14, pady=3)
            self.botoes_nav[chave] = b

        botao(sb, "Exportar CSV", self.exportar_csv, primario=False, largura=200).pack(
            side="bottom", padx=20, pady=24)

    def mostrar(self, chave):
        for k, p in self.paginas.items():
            p.pack_forget()
            self.botoes_nav[k].configure(fg_color=ACCENT if k == chave else "transparent",
                                         hover_color=ACCENT_HOVER if k == chave else "#1B2745")
        self.paginas[chave].pack(fill="both", expand=True)
        self.paginas[chave].render()

    def atualizar(self):
        for p in self.paginas.values():
            if p.winfo_ismapped():
                p.render()
        self.paginas["cadastro"].render()

    # ---- operações sobre os dados
    def adicionar(self, nome, local, tel, cidade, potencial):
        self.dados.append({"id": uuid.uuid4().hex, "nome": nome, "local": local, "tel": tel,
                           "cidade": (cidade or "Sem cidade").title(), "potencial": bool(potencial)})
        salvar_dados(self.dados)
        self.atualizar()

    def alternar_potencial(self, id_):
        for d in self.dados:
            if d["id"] == id_:
                d["potencial"] = not d.get("potencial", False)
        salvar_dados(self.dados)
        self.atualizar()

    def excluir(self, id_):
        d = next((x for x in self.dados if x["id"] == id_), None)
        if d and messagebox.askyesno("Excluir", f"Excluir “{d['nome']}”?"):
            self.dados = [x for x in self.dados if x["id"] != id_]
            salvar_dados(self.dados)
            self.atualizar()

    def copiar(self, texto):
        if texto:
            self.clipboard_clear()
            self.clipboard_append(texto)

    def exportar_csv(self):
        caminho = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                               initialfile="estabelecimentos.csv")
        if not caminho:
            return
        with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Nome", "Localização", "Telefone", "Cidade", "Potencial"])
            for d in sorted(self.dados, key=lambda x: (x["cidade"], x["nome"])):
                w.writerow([d["nome"], d.get("local", ""), d.get("tel", ""), d["cidade"],
                            "Sim" if d.get("potencial") else "Não"])
        messagebox.showinfo("Pronto", "Arquivo exportado com sucesso.")


if __name__ == "__main__":
    App().mainloop()

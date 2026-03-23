import csv
import hashlib
import shutil
import sqlite3
import calendar
import tkinter as tk
import unicodedata
from datetime import datetime
from tkinter import messagebox, ttk, filedialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

DB_NAME = 'financeiro.db'

CATEGORIAS_DESPESA = ['Alimentação', 'Rolê', 'Extra', 'Vestuário']
CATEGORIAS_RECEITA = ['PIX', 'Trabalho', 'Transferência', 'Venda', 'Outro']

OPCOES_MES = [
    'Histórico completo',
    '01 - Janeiro',
    '02 - Fevereiro',
    '03 - Março',
    '04 - Abril',
    '05 - Maio',
    '06 - Junho',
    '07 - Julho',
    '08 - Agosto',
    '09 - Setembro',
    '10 - Outubro',
    '11 - Novembro',
    '12 - Dezembro',
]

TIPOS_FILTRO = ['Todos', 'Receita', 'Despesa']


def formatar_moeda(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def converter_data_para_iso(data_br: str) -> str:
    return datetime.strptime(data_br.strip(), '%d/%m/%Y').strftime('%Y-%m-%d')


def converter_data_para_br(data_iso: str) -> str:
    try:
        return datetime.strptime(data_iso, '%Y-%m-%d').strftime('%d/%m/%Y')
    except Exception:
        return data_iso


def normalizar_texto(texto: str) -> str:
    texto = (texto or '').strip().lower()
    texto = unicodedata.normalize('NFKD', texto)
    return ''.join(ch for ch in texto if not unicodedata.combining(ch))


class BancoDados:
    def __init__(self, caminho=DB_NAME):
        self.caminho = caminho
        self.conn = sqlite3.connect(caminho)
        self.conn.row_factory = sqlite3.Row
        self.criar_tabelas()
        self.migrar_colunas()

    def criar_tabelas(self):
        cur = self.conn.cursor()

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('Receita','Despesa')),
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            '''
        )

        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                month_ref TEXT NOT NULL,
                goal_type TEXT NOT NULL CHECK(goal_type IN ('gasto_maximo','economia_minima')),
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, month_ref, goal_type),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            '''
        )

        self.conn.commit()

    def migrar_colunas(self):
        cur = self.conn.cursor()

        cur.execute("PRAGMA table_info(users)")
        colunas_users = [linha['name'] for linha in cur.fetchall()]
        if 'full_name' not in colunas_users:
            cur.execute("ALTER TABLE users ADD COLUMN full_name TEXT DEFAULT ''")

        cur.execute("PRAGMA table_info(transactions)")
        colunas_trans = [linha['name'] for linha in cur.fetchall()]
        if 'note' not in colunas_trans:
            cur.execute("ALTER TABLE transactions ADD COLUMN note TEXT DEFAULT ''")

        self.conn.commit()

    @staticmethod
    def gerar_hash_senha(senha: str) -> str:
        return hashlib.sha256(senha.encode('utf-8')).hexdigest()

    def cadastrar_usuario(self, usuario: str, senha: str, nome_completo: str):
        try:
            self.conn.execute(
                'INSERT INTO users (username, password_hash, created_at, full_name) VALUES (?, ?, ?, ?)',
                (usuario, self.gerar_hash_senha(senha), datetime.now().isoformat(), nome_completo),
            )
            self.conn.commit()
            return True, 'Cadastro realizado com sucesso.'
        except sqlite3.IntegrityError:
            return False, 'Esse nome de usuário já existe.'

    def autenticar(self, usuario: str, senha: str):
        cur = self.conn.cursor()
        cur.execute(
            'SELECT * FROM users WHERE username = ? AND password_hash = ?',
            (usuario, self.gerar_hash_senha(senha)),
        )
        return cur.fetchone()

    def adicionar_transacao(self, user_id, tipo, nome, categoria, data_iso, valor, observacao=''):
        self.conn.execute(
            '''
            INSERT INTO transactions (user_id, type, name, category, date, amount, created_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (user_id, tipo, nome, categoria, data_iso, valor, datetime.now().isoformat(), observacao),
        )
        self.conn.commit()

    def atualizar_transacao(self, transacao_id, user_id, tipo, nome, categoria, data_iso, valor, observacao=''):
        self.conn.execute(
            '''
            UPDATE transactions
            SET type = ?, name = ?, category = ?, date = ?, amount = ?, note = ?
            WHERE id = ? AND user_id = ?
            ''',
            (tipo, nome, categoria, data_iso, valor, observacao, transacao_id, user_id),
        )
        self.conn.commit()

    def excluir_transacao(self, transacao_id, user_id):
        self.conn.execute(
            'DELETE FROM transactions WHERE id = ? AND user_id = ?',
            (transacao_id, user_id)
        )
        self.conn.commit()

    def obter_transacoes(self, user_id, filtro_mes=None, filtro_tipo='Todos', filtro_categoria='Todas', busca_nome=''):
        cur = self.conn.cursor()

        sql = 'SELECT * FROM transactions WHERE user_id = ?'
        params = [user_id]

        if filtro_mes and filtro_mes != 'Histórico completo':
            numero_mes = filtro_mes[:2]
            sql += ' AND substr(date, 6, 2) = ?'
            params.append(numero_mes)

        if filtro_tipo and filtro_tipo != 'Todos':
            sql += ' AND type = ?'
            params.append(filtro_tipo)

        if filtro_categoria and filtro_categoria != 'Todas':
            sql += ' AND category = ?'
            params.append(filtro_categoria)

        if busca_nome.strip():
            sql += ' AND lower(name) LIKE ?'
            params.append(f"%{busca_nome.strip().lower()}%")

        sql += ' ORDER BY date DESC, id DESC'

        cur.execute(sql, tuple(params))
        return cur.fetchall()

    def obter_resumo(self, user_id, filtro_mes=None, filtro_tipo='Todos', filtro_categoria='Todas', busca_nome=''):
        linhas = self.obter_transacoes(user_id, filtro_mes, filtro_tipo, filtro_categoria, busca_nome)

        receitas = sum(float(l['amount']) for l in linhas if l['type'] == 'Receita')
        despesas = sum(float(l['amount']) for l in linhas if l['type'] == 'Despesa')

        acumulado_categorias = {}
        for linha in linhas:
            if linha['type'] == 'Despesa':
                acumulado_categorias.setdefault(linha['category'], 0.0)
                acumulado_categorias[linha['category']] += float(linha['amount'])

        categorias = [
            {'category': categoria, 'total': total}
            for categoria, total in sorted(acumulado_categorias.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            'receitas': receitas,
            'despesas': despesas,
            'saldo': receitas - despesas,
            'categorias_despesa': categorias,
            'quantidade': len(linhas),
        }

    def obter_ultimas_transacoes(self, user_id, limite=5):
        cur = self.conn.cursor()
        cur.execute(
            '''
            SELECT * FROM transactions
            WHERE user_id = ?
            ORDER BY date DESC, id DESC
            LIMIT ?
            ''',
            (user_id, limite),
        )
        return cur.fetchall()

    def obter_maior_receita(self, user_id, filtro_mes=None):
        cur = self.conn.cursor()
        sql = "SELECT * FROM transactions WHERE user_id = ? AND type = 'Receita'"
        params = [user_id]
        if filtro_mes and filtro_mes != 'Histórico completo':
            sql += ' AND substr(date, 6, 2) = ?'
            params.append(filtro_mes[:2])
        sql += ' ORDER BY amount DESC LIMIT 1'
        cur.execute(sql, tuple(params))
        return cur.fetchone()

    def obter_categoria_topo_despesa(self, user_id, filtro_mes=None):
        cur = self.conn.cursor()
        sql = '''
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE user_id = ? AND type = 'Despesa'
        '''
        params = [user_id]
        if filtro_mes and filtro_mes != 'Histórico completo':
            sql += ' AND substr(date, 6, 2) = ?'
            params.append(filtro_mes[:2])

        sql += ' GROUP BY category ORDER BY total DESC LIMIT 1'
        cur.execute(sql, tuple(params))
        return cur.fetchone()

    def obter_media_despesas(self, user_id, filtro_mes=None):
        cur = self.conn.cursor()
        sql = "SELECT AVG(amount) AS media FROM transactions WHERE user_id = ? AND type = 'Despesa'"
        params = [user_id]
        if filtro_mes and filtro_mes != 'Histórico completo':
            sql += ' AND substr(date, 6, 2) = ?'
            params.append(filtro_mes[:2])
        cur.execute(sql, tuple(params))
        linha = cur.fetchone()
        return float(linha['media']) if linha and linha['media'] is not None else 0.0

    def salvar_meta(self, user_id, month_ref, goal_type, amount):
        cur = self.conn.cursor()
        cur.execute(
            '''
            INSERT INTO goals (user_id, month_ref, goal_type, amount, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, month_ref, goal_type)
            DO UPDATE SET amount = excluded.amount
            ''',
            (user_id, month_ref, goal_type, amount, datetime.now().isoformat())
        )
        self.conn.commit()

    def obter_metas_mes(self, user_id, month_ref):
        cur = self.conn.cursor()
        cur.execute(
            'SELECT * FROM goals WHERE user_id = ? AND month_ref = ?',
            (user_id, month_ref)
        )
        linhas = cur.fetchall()
        resultado = {'gasto_maximo': None, 'economia_minima': None}
        for linha in linhas:
            resultado[linha['goal_type']] = float(linha['amount'])
        return resultado

    def listar_metas(self, user_id):
        cur = self.conn.cursor()
        cur.execute(
            '''
            SELECT
                month_ref,
                MAX(CASE WHEN goal_type = 'gasto_maximo' THEN amount END) AS gasto_maximo,
                MAX(CASE WHEN goal_type = 'economia_minima' THEN amount END) AS economia_minima
            FROM goals
            WHERE user_id = ?
            GROUP BY month_ref
            ORDER BY month_ref DESC
            ''',
            (user_id,)
        )
        return cur.fetchall()

    def excluir_metas_mes(self, user_id, month_ref):
        self.conn.execute(
            'DELETE FROM goals WHERE user_id = ? AND month_ref = ?',
            (user_id, month_ref)
        )
        self.conn.commit()

    def importar_transacoes_em_lote(self, user_id, transacoes):
        cur = self.conn.cursor()
        momento = datetime.now().isoformat()
        cur.executemany(
            '''
            INSERT INTO transactions (user_id, type, name, category, date, amount, created_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            [
                (
                    user_id,
                    transacao['type'],
                    transacao['name'],
                    transacao['category'],
                    transacao['date'],
                    transacao['amount'],
                    momento,
                    transacao.get('note', '')
                )
                for transacao in transacoes
            ]
        )
        self.conn.commit()


class CalendarioMini(tk.Toplevel):
    def __init__(self, master, data_inicial=None, ao_selecionar=None):
        super().__init__(master)
        self.title('Selecionar data')
        self.geometry('290x300')
        self.resizable(False, False)
        self.configure(bg='#f4f6fb')
        self.transient(master)
        self.grab_set()

        self.ao_selecionar = ao_selecionar

        hoje = datetime.now()
        if data_inicial:
            try:
                data_base = datetime.strptime(data_inicial, '%d/%m/%Y')
            except Exception:
                data_base = hoje
        else:
            data_base = hoje

        self.ano_var = tk.IntVar(value=data_base.year)
        self.mes_var = tk.IntVar(value=data_base.month)

        self.montar_interface()
        self.renderizar_dias()

    def montar_interface(self):
        topo = tk.Frame(self, bg='white', bd=1, relief='solid')
        topo.pack(fill='both', expand=True, padx=12, pady=12)

        cabecalho = tk.Frame(topo, bg='white')
        cabecalho.pack(fill='x', padx=10, pady=(10, 6))

        tk.Button(cabecalho, text='<', command=self.mes_anterior, bg='#eef3ff', relief='flat').pack(side='left')
        self.lbl_titulo = tk.Label(cabecalho, text='', font=('Segoe UI', 11, 'bold'), bg='white', fg='#1d2a57')
        self.lbl_titulo.pack(side='left', expand=True)
        tk.Button(cabecalho, text='>', command=self.proximo_mes, bg='#eef3ff', relief='flat').pack(side='right')

        linha_semana = tk.Frame(topo, bg='white')
        linha_semana.pack(fill='x', padx=10)
        for nome_dia in ['S', 'T', 'Q', 'Q', 'S', 'S', 'D']:
            tk.Label(linha_semana, text=nome_dia, width=3, bg='white', fg='#4b587c', font=('Segoe UI', 9, 'bold')).pack(side='left', expand=True)

        self.frame_dias = tk.Frame(topo, bg='white')
        self.frame_dias.pack(fill='both', expand=True, padx=10, pady=(6, 8))

        rodape = tk.Frame(topo, bg='white')
        rodape.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(rodape, text='Hoje', command=self.selecionar_hoje, bg='#eef3ff', fg='#1d2a57', relief='flat').pack(side='left', fill='x', expand=True, padx=(0, 5), ipady=6)
        tk.Button(rodape, text='Cancelar', command=self.destroy, bg='#f0f2f7', fg='#1d2a57', relief='flat').pack(side='left', fill='x', expand=True, padx=(5, 0), ipady=6)

    def renderizar_dias(self):
        for widget in self.frame_dias.winfo_children():
            widget.destroy()

        ano = self.ano_var.get()
        mes = self.mes_var.get()
        self.lbl_titulo.config(text=f'{calendar.month_name[mes]} / {ano}')

        calendario_mes = calendar.monthcalendar(ano, mes)

        for semana in calendario_mes:
            linha = tk.Frame(self.frame_dias, bg='white')
            linha.pack(fill='x')

            for dia in semana:
                if dia == 0:
                    tk.Label(linha, text='', width=4, bg='white').pack(side='left', expand=True, padx=1, pady=1)
                else:
                    tk.Button(
                        linha,
                        text=str(dia),
                        width=4,
                        command=lambda d=dia: self.selecionar_dia(d),
                        bg='#f7f9fd',
                        fg='#1d2a57',
                        relief='flat'
                    ).pack(side='left', expand=True, padx=1, pady=1)

    def mes_anterior(self):
        mes = self.mes_var.get() - 1
        ano = self.ano_var.get()
        if mes < 1:
            mes = 12
            ano -= 1
        self.mes_var.set(mes)
        self.ano_var.set(ano)
        self.renderizar_dias()

    def proximo_mes(self):
        mes = self.mes_var.get() + 1
        ano = self.ano_var.get()
        if mes > 12:
            mes = 1
            ano += 1
        self.mes_var.set(mes)
        self.ano_var.set(ano)
        self.renderizar_dias()

    def selecionar_dia(self, dia):
        data_str = f'{dia:02d}/{self.mes_var.get():02d}/{self.ano_var.get()}'
        if self.ao_selecionar:
            self.ao_selecionar(data_str)
        self.destroy()

    def selecionar_hoje(self):
        hoje = datetime.now().strftime('%d/%m/%Y')
        if self.ao_selecionar:
            self.ao_selecionar(hoje)
        self.destroy()


class JanelaCadastroUsuario(tk.Toplevel):
    def __init__(self, master, banco: BancoDados):
        super().__init__(master)
        self.banco = banco
        self.title('Cadastro de usuário')
        self.geometry('420x440')
        self.resizable(False, False)
        self.configure(bg='#f4f6fb')
        self.transient(master)
        self.grab_set()
        self.mostrando_senha = False
        self.montar_interface()

    def montar_interface(self):
        painel = tk.Frame(self, bg='white', bd=1, relief='solid')
        painel.place(relx=0.5, rely=0.5, anchor='center', width=360, height=380)

        tk.Label(painel, text='Cadastro de usuário', font=('Segoe UI', 15, 'bold'), bg='white', fg='#1d2a57').pack(pady=(18, 4))
        tk.Label(painel, text='Você está cadastrando um novo usuário.', font=('Segoe UI', 10), bg='white', fg='#4b587c').pack(pady=(0, 12))

        formulario = tk.Frame(painel, bg='white')
        formulario.pack(fill='both', expand=True, padx=20)

        tk.Label(formulario, text='Nome completo', font=('Segoe UI', 10, 'bold'), bg='white', anchor='w').pack(fill='x')
        self.nome_completo_var = tk.StringVar()
        tk.Entry(formulario, textvariable=self.nome_completo_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 10), ipady=6)

        tk.Label(formulario, text='Usuário', font=('Segoe UI', 10, 'bold'), bg='white', anchor='w').pack(fill='x')
        self.usuario_var = tk.StringVar()
        tk.Entry(formulario, textvariable=self.usuario_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 10), ipady=6)

        tk.Label(formulario, text='Senha', font=('Segoe UI', 10, 'bold'), bg='white', anchor='w').pack(fill='x')
        linha_senha = tk.Frame(formulario, bg='white')
        linha_senha.pack(fill='x', pady=(4, 12))

        self.senha_var = tk.StringVar()
        self.entrada_senha = tk.Entry(linha_senha, textvariable=self.senha_var, font=('Segoe UI', 10), relief='solid', bd=1, show='*')
        self.entrada_senha.pack(side='left', fill='x', expand=True, ipady=6)

        tk.Button(linha_senha, text='👁', command=self.alternar_senha, relief='solid', bd=1, bg='#eef3ff').pack(side='left', padx=(8, 0), ipadx=6, ipady=3)

        botoes = tk.Frame(formulario, bg='white')
        botoes.pack(fill='x')
        tk.Button(botoes, text='Criar conta', command=self.cadastrar, bg='#4a90e2', fg='white', relief='flat').pack(side='left', fill='x', expand=True, ipady=8, padx=(0, 6))
        tk.Button(botoes, text='Cancelar', command=self.destroy, bg='#f0f2f7', fg='#1d2a57', relief='flat').pack(side='left', fill='x', expand=True, ipady=8)

    def alternar_senha(self):
        self.mostrando_senha = not self.mostrando_senha
        self.entrada_senha.configure(show='' if self.mostrando_senha else '*')

    def cadastrar(self):
        nome_completo = self.nome_completo_var.get().strip()
        usuario = self.usuario_var.get().strip()
        senha = self.senha_var.get().strip()

        if len(nome_completo) < 3:
            messagebox.showwarning('Aviso', 'Informe o nome completo.', parent=self)
            return
        if len(usuario) < 3:
            messagebox.showwarning('Aviso', 'O usuário deve ter pelo menos 3 caracteres.', parent=self)
            return
        if len(senha) < 4:
            messagebox.showwarning('Aviso', 'A senha deve ter pelo menos 4 caracteres.', parent=self)
            return

        ok, msg = self.banco.cadastrar_usuario(usuario, senha, nome_completo)
        if ok:
            messagebox.showinfo('Sucesso', msg, parent=self)
            self.destroy()
        else:
            messagebox.showerror('Erro', msg, parent=self)


class JanelaInformacoesRapidas(tk.Toplevel):
    def __init__(self, master, texto_esquerda, texto_direita):
        super().__init__(master)
        self.title('Informações rápidas')
        self.geometry('820x420')
        self.minsize(760, 360)
        self.configure(bg='#eef2f8')

        container = tk.Frame(self, bg='white', bd=1, relief='solid')
        container.pack(fill='both', expand=True, padx=12, pady=12)

        tk.Label(
            container,
            text='Resumo rápido',
            font=('Segoe UI', 13, 'bold'),
            bg='white',
            fg='#1d2a57'
        ).pack(anchor='w', padx=12, pady=(12, 8))

        corpo = tk.Frame(container, bg='white')
        corpo.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        esquerda = tk.Frame(corpo, bg='#f8fbff', bd=1, relief='solid')
        esquerda.pack(side='left', fill='both', expand=True, padx=(0, 6))

        direita = tk.Frame(corpo, bg='#f8fbff', bd=1, relief='solid')
        direita.pack(side='left', fill='both', expand=True, padx=(6, 0))

        self.lbl_esquerda = tk.Label(
            esquerda,
            text=texto_esquerda,
            justify='left',
            anchor='nw',
            bg='#f8fbff',
            fg='#1d2a57',
            font=('Segoe UI', 10)
        )
        self.lbl_esquerda.pack(fill='both', expand=True, padx=12, pady=12)

        self.lbl_direita = tk.Label(
            direita,
            text=texto_direita,
            justify='left',
            anchor='nw',
            bg='#f8fbff',
            fg='#1d2a57',
            font=('Segoe UI', 10)
        )
        self.lbl_direita.pack(fill='both', expand=True, padx=12, pady=12)

    def atualizar_textos(self, texto_esquerda, texto_direita):
        self.lbl_esquerda.config(text=texto_esquerda)
        self.lbl_direita.config(text=texto_direita)


class JanelaMetas(tk.Toplevel):
    def __init__(self, master, banco: BancoDados, usuario, ao_atualizar=None):
        super().__init__(master)
        self.title('Metas do mês')
        self.geometry('860x500')
        self.minsize(780, 420)
        self.configure(bg='#eef2f8')
        self.banco = banco
        self.usuario = usuario
        self.ao_atualizar = ao_atualizar

        self.mes_var = tk.StringVar(value=datetime.now().strftime('%m'))
        self.ano_var = tk.StringVar(value=datetime.now().strftime('%Y'))
        self.meta_gasto_var = tk.StringVar()
        self.meta_economia_var = tk.StringVar()

        self.montar_interface()
        self.carregar_mes_selecionado()
        self.atualizar_lista()

    def montar_interface(self):
        container = tk.Frame(self, bg='white', bd=1, relief='solid')
        container.pack(fill='both', expand=True, padx=12, pady=12)

        tk.Label(container, text='Metas do mês', font=('Segoe UI', 13, 'bold'), bg='white', fg='#1d2a57').pack(anchor='w', padx=12, pady=(12, 4))
        tk.Label(container, text='Cadastre metas por mês e acompanhe as que já foram salvas.', font=('Segoe UI', 9), bg='white', fg='#5f6f91').pack(anchor='w', padx=12, pady=(0, 10))

        corpo = tk.Frame(container, bg='white')
        corpo.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        esquerda = tk.Frame(corpo, bg='#f8fbff', bd=1, relief='solid')
        esquerda.pack(side='left', fill='y', padx=(0, 8))

        direita = tk.Frame(corpo, bg='#f8fbff', bd=1, relief='solid')
        direita.pack(side='left', fill='both', expand=True, padx=(8, 0))

        filtros = tk.Frame(esquerda, bg='#f8fbff')
        filtros.pack(fill='x', padx=12, pady=12)

        tk.Label(filtros, text='Mês', font=('Segoe UI', 10, 'bold'), bg='#f8fbff').pack(anchor='w')
        ttk.Combobox(
            filtros,
            textvariable=self.mes_var,
            state='readonly',
            values=[f'{i:02d}' for i in range(1, 13)],
            width=8,
            font=('Segoe UI', 10)
        ).pack(fill='x', pady=(4, 10))

        tk.Label(filtros, text='Ano', font=('Segoe UI', 10, 'bold'), bg='#f8fbff').pack(anchor='w')
        anos = [str(datetime.now().year + delta) for delta in range(-3, 4)]
        ttk.Combobox(
            filtros,
            textvariable=self.ano_var,
            state='readonly',
            values=anos,
            width=8,
            font=('Segoe UI', 10)
        ).pack(fill='x', pady=(4, 10))

        tk.Button(filtros, text='Carregar mês', command=self.carregar_mes_selecionado, bg='#eef3ff', fg='#1d2a57', relief='flat').pack(fill='x', ipady=7, pady=(0, 12))

        tk.Label(filtros, text='Gasto máximo', font=('Segoe UI', 10, 'bold'), bg='#f8fbff').pack(anchor='w')
        tk.Entry(filtros, textvariable=self.meta_gasto_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 10), ipady=6)

        tk.Label(filtros, text='Economia mínima', font=('Segoe UI', 10, 'bold'), bg='#f8fbff').pack(anchor='w')
        tk.Entry(filtros, textvariable=self.meta_economia_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 10), ipady=6)

        tk.Button(filtros, text='Salvar metas', command=self.salvar_metas, bg='#4a90e2', fg='white', relief='flat').pack(fill='x', ipady=8, pady=(0, 8))
        tk.Button(filtros, text='Excluir metas deste mês', command=self.excluir_mes_atual, bg='#fde2e1', fg='#8a1c1c', relief='flat').pack(fill='x', ipady=8)

        tk.Label(direita, text='Metas cadastradas', font=('Segoe UI', 11, 'bold'), bg='#f8fbff', fg='#1d2a57').pack(anchor='w', padx=12, pady=(12, 8))

        colunas = ('mes_ref', 'gasto', 'economia')
        self.tree_metas = ttk.Treeview(direita, columns=colunas, show='headings', height=14)
        self.tree_metas.heading('mes_ref', text='Mês')
        self.tree_metas.heading('gasto', text='Gasto máximo')
        self.tree_metas.heading('economia', text='Economia mínima')
        self.tree_metas.column('mes_ref', width=120, anchor='center')
        self.tree_metas.column('gasto', width=150, anchor='center')
        self.tree_metas.column('economia', width=150, anchor='center')
        self.tree_metas.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.tree_metas.bind('<<TreeviewSelect>>', self.ao_selecionar_meta)

    def obter_month_ref(self):
        return f'{self.ano_var.get()}-{self.mes_var.get()}'

    def formatar_month_ref(self, month_ref):
        try:
            ano, mes = month_ref.split('-')
            nome_mes = calendar.month_name[int(mes)].capitalize()
            nomes_pt = {
                'January': 'Janeiro', 'February': 'Fevereiro', 'March': 'Março', 'April': 'Abril',
                'May': 'Maio', 'June': 'Junho', 'July': 'Julho', 'August': 'Agosto',
                'September': 'Setembro', 'October': 'Outubro', 'November': 'Novembro', 'December': 'Dezembro'
            }
            return f"{nomes_pt.get(nome_mes, nome_mes)}/{ano}"
        except Exception:
            return month_ref

    def carregar_mes_selecionado(self):
        metas = self.banco.obter_metas_mes(self.usuario['id'], self.obter_month_ref())
        self.meta_gasto_var.set('' if metas['gasto_maximo'] is None else str(metas['gasto_maximo']).replace('.', ','))
        self.meta_economia_var.set('' if metas['economia_minima'] is None else str(metas['economia_minima']).replace('.', ','))

    def salvar_metas(self):
        try:
            month_ref = self.obter_month_ref()
            houve_alguma = False
            if self.meta_gasto_var.get().strip():
                self.banco.salvar_meta(self.usuario['id'], month_ref, 'gasto_maximo', self.master.interpretar_valor(self.meta_gasto_var.get()))
                houve_alguma = True
            if self.meta_economia_var.get().strip():
                self.banco.salvar_meta(self.usuario['id'], month_ref, 'economia_minima', self.master.interpretar_valor(self.meta_economia_var.get()))
                houve_alguma = True
            if not houve_alguma:
                messagebox.showwarning('Aviso', 'Preencha pelo menos uma meta.', parent=self)
                return
            self.atualizar_lista()
            if callable(self.ao_atualizar):
                self.ao_atualizar()
            messagebox.showinfo('Sucesso', 'Metas salvas com sucesso.', parent=self)
        except Exception:
            messagebox.showwarning('Aviso', 'Informe valores válidos nas metas.', parent=self)

    def atualizar_lista(self):
        for item in self.tree_metas.get_children():
            self.tree_metas.delete(item)
        for linha in self.banco.listar_metas(self.usuario['id']):
            self.tree_metas.insert('', 'end', values=(
                linha['month_ref'],
                '' if linha['gasto_maximo'] is None else formatar_moeda(float(linha['gasto_maximo'])),
                '' if linha['economia_minima'] is None else formatar_moeda(float(linha['economia_minima'])),
            ))

    def ao_selecionar_meta(self, _event=None):
        selecionados = self.tree_metas.selection()
        if not selecionados:
            return
        valores = self.tree_metas.item(selecionados[0], 'values')
        month_ref = valores[0]
        try:
            ano, mes = month_ref.split('-')
            self.ano_var.set(ano)
            self.mes_var.set(mes)
        except Exception:
            pass
        self.carregar_mes_selecionado()

    def excluir_mes_atual(self):
        month_ref = self.obter_month_ref()
        if not messagebox.askyesno('Confirmar exclusão', f'Deseja excluir as metas de {self.formatar_month_ref(month_ref)}?', parent=self):
            return
        self.banco.excluir_metas_mes(self.usuario['id'], month_ref)
        self.meta_gasto_var.set('')
        self.meta_economia_var.set('')
        self.atualizar_lista()
        if callable(self.ao_atualizar):
            self.ao_atualizar()
        messagebox.showinfo('Sucesso', 'Metas excluídas com sucesso.', parent=self)


class TelaLogin(tk.Frame):
    def __init__(self, master, banco: BancoDados, ao_logar, abrir_cadastro):
        super().__init__(master, bg='#eef2f8')
        self.banco = banco
        self.ao_logar = ao_logar
        self.abrir_cadastro = abrir_cadastro
        self.mostrando_senha = False
        self.montar_interface()

    def montar_interface(self):
        painel = tk.Frame(self, bg='white', bd=1, relief='solid')
        painel.place(relx=0.5, rely=0.5, anchor='center', width=410, height=420)

        tk.Label(painel, text='Controle Financeiro', font=('Segoe UI', 18, 'bold'), bg='white', fg='#1d2a57').pack(pady=(24, 8))
        tk.Label(painel, text='Faça login para acessar o software', font=('Segoe UI', 10), bg='white', fg='#55627f').pack(pady=(0, 16))

        formulario = tk.Frame(painel, bg='white')
        formulario.pack(fill='both', expand=True, padx=26)

        tk.Label(formulario, text='Usuário', font=('Segoe UI', 10, 'bold'), bg='white', anchor='w').pack(fill='x')
        self.usuario_var = tk.StringVar()
        tk.Entry(formulario, textvariable=self.usuario_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 10), ipady=6)

        tk.Label(formulario, text='Senha', font=('Segoe UI', 10, 'bold'), bg='white', anchor='w').pack(fill='x')
        linha_senha = tk.Frame(formulario, bg='white')
        linha_senha.pack(fill='x', pady=(4, 14))

        self.senha_var = tk.StringVar()
        self.entrada_senha = tk.Entry(linha_senha, textvariable=self.senha_var, font=('Segoe UI', 10), relief='solid', bd=1, show='*')
        self.entrada_senha.pack(side='left', fill='x', expand=True, ipady=6)

        tk.Button(linha_senha, text='👁', command=self.alternar_senha, relief='solid', bd=1, bg='#eef3ff').pack(side='left', padx=(8, 0), ipadx=6, ipady=3)

        tk.Button(formulario, text='Entrar', command=self.fazer_login, bg='#4a90e2', fg='white', relief='flat').pack(fill='x', ipady=9, pady=(4, 8))
        tk.Button(formulario, text='Cadastrar novo usuário', command=self.abrir_cadastro, bg='#f0f2f7', fg='#1d2a57', relief='flat').pack(fill='x', ipady=9)

        self.entrada_senha.bind('<Return>', lambda e: self.fazer_login())

    def alternar_senha(self):
        self.mostrando_senha = not self.mostrando_senha
        self.entrada_senha.configure(show='' if self.mostrando_senha else '*')

    def fazer_login(self):
        usuario = self.usuario_var.get().strip()
        senha = self.senha_var.get().strip()
        user = self.banco.autenticar(usuario, senha)

        if user:
            self.ao_logar(user)
        else:
            messagebox.showerror('Erro', 'Usuário ou senha inválidos.')


class TelaPrincipal(tk.Frame):
    def __init__(self, master, banco: BancoDados, usuario, ao_sair_conta):
        super().__init__(master, bg='#eef2f8')
        self.banco = banco
        self.usuario = usuario
        self.ao_sair_conta = ao_sair_conta
        self.id_selecionado = None
        self.estado_ordenacao = {}
        self.janela_infos = None
        self.janela_metas = None
        self.texto_info_esquerda = ''
        self.texto_info_direita = ''

        self.tipo_var = tk.StringVar(value='Despesa')
        self.categoria_var = tk.StringVar(value=CATEGORIAS_DESPESA[0])
        self.nome_var = tk.StringVar()
        self.data_var = tk.StringVar(value=datetime.now().strftime('%d/%m/%Y'))
        self.valor_var = tk.StringVar()
        self.observacao_var = tk.StringVar()

        self.saldo_var = tk.StringVar(value='Saldo: R$ 0,00')
        self.total_receitas_var = tk.StringVar(value='Receitas: R$ 0,00')
        self.total_despesas_var = tk.StringVar(value='Despesas: R$ 0,00')

        self.filtro_mes_var = tk.StringVar(value='Histórico completo')
        self.filtro_tipo_var = tk.StringVar(value='Todos')
        self.filtro_categoria_var = tk.StringVar(value='Todas')
        self.busca_nome_var = tk.StringVar()

        self.modo_edicao_var = tk.StringVar(value='Modo atual: novo lançamento')
        self.info_filtro_var = tk.StringVar(value='Exibindo: histórico completo')

        self.meta_gasto_var = tk.StringVar()
        self.meta_economia_var = tk.StringVar()

        self.montar_interface()
        self.atualizar_menu_categorias()
        self.atualizar_combo_categorias_filtro()
        self.atualizar_tudo()
        self.carregar_metas_mes_atual()

    def montar_interface(self):
        topo = tk.Frame(self, bg='#1d2a57', height=58)
        topo.pack(fill='x')
        topo.pack_propagate(False)

        nome_exibicao = self.usuario['full_name'] if 'full_name' in self.usuario.keys() and self.usuario['full_name'] else self.usuario['username']

        tk.Label(
            topo,
            text=f'Controle Financeiro - {nome_exibicao}',
            font=('Segoe UI', 14, 'bold'),
            bg='#1d2a57',
            fg='white'
        ).pack(side='left', padx=18)

        tk.Button(topo, text='Backup do banco', command=self.fazer_backup_banco, bg='#e8f0ff', fg='#1d2a57', relief='flat').pack(side='right', padx=(8, 18), pady=12)
        tk.Button(topo, text='Sair do app', command=self.confirmar_saida_app, bg='#f8d7da', fg='#842029', relief='flat').pack(side='right', padx=(8, 8), pady=12)
        tk.Button(topo, text='Trocar usuário', command=self.confirmar_troca_usuario, bg='#ffffff', fg='#1d2a57', relief='flat').pack(side='right', pady=12)

        faixa_info = tk.Frame(self, bg='#eef2f8')
        faixa_info.pack(fill='x', padx=12, pady=(12, 8))

        linha_botoes_topo = tk.Frame(faixa_info, bg='#eef2f8')
        linha_botoes_topo.pack(anchor='w')

        tk.Button(
            linha_botoes_topo,
            text='Informações rápidas',
            command=self.abrir_janela_infos_rapidas,
            bg='#dbeafe',
            fg='#1e3a8a',
            relief='flat',
            font=('Segoe UI', 10, 'bold')
        ).pack(side='left', ipadx=8, ipady=6)

        tk.Button(
            linha_botoes_topo,
            text='Metas do mês',
            command=self.abrir_janela_metas,
            bg='#fff3cd',
            fg='#856404',
            relief='flat',
            font=('Segoe UI', 10, 'bold')
        ).pack(side='left', padx=(8, 0), ipadx=8, ipady=6)

        totais = tk.Frame(self, bg='#eef2f8')
        totais.pack(fill='x', padx=12, pady=(0, 12))
        self.criar_card_total(totais, 'Receitas', self.total_receitas_var, '#d8f3dc', '#1b5e20').pack(side='left', fill='x', expand=True, padx=(0, 6))
        self.criar_card_total(totais, 'Despesas', self.total_despesas_var, '#ffe5d9', '#9a3412').pack(side='left', fill='x', expand=True, padx=6)
        self.criar_card_total(totais, 'Saldo da conta', self.saldo_var, '#dbeafe', '#1e3a8a').pack(side='left', fill='x', expand=True, padx=(6, 0))

        conteudo = tk.Frame(self, bg='#eef2f8')
        conteudo.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        esquerda = tk.Frame(conteudo, bg='white', bd=1, relief='solid')
        esquerda.pack(side='left', fill='y', padx=(0, 10))

        direita = tk.Frame(conteudo, bg='#eef2f8')
        direita.pack(side='left', fill='both', expand=True)

        self.montar_formulario(esquerda)
        self.montar_tabela(direita)
        self.montar_graficos(direita)

    def criar_card_total(self, parent, titulo, variavel, bg, fg):
        card = tk.Frame(parent, bg=bg, bd=1, relief='solid', height=70)
        card.pack_propagate(False)
        tk.Label(card, text=titulo, font=('Segoe UI', 10, 'bold'), bg=bg, fg=fg).pack(anchor='w', padx=14, pady=(10, 2))
        tk.Label(card, textvariable=variavel, font=('Segoe UI', 12, 'bold'), bg=bg, fg=fg).pack(anchor='w', padx=14)
        return card

    def montar_formulario(self, parent):
        parent.configure(width=470)
        parent.pack_propagate(False)

        cabecalho = tk.Frame(parent, bg='white')
        cabecalho.pack(fill='x', padx=14, pady=(14, 8))
        tk.Label(cabecalho, text='Cadastrar / Editar', font=('Segoe UI', 14, 'bold'), bg='white', fg='#1d2a57').pack(anchor='w')
        tk.Label(cabecalho, text='Adicione receitas e despesas com mais organização.', font=('Segoe UI', 9), bg='white', fg='#5f6f91').pack(anchor='w', pady=(2, 0))

        destaque = tk.Frame(parent, bg='#eef7ff', bd=2, relief='solid', highlightbackground='#b8d6ff', highlightthickness=1)
        destaque.pack(fill='x', padx=14, pady=(0, 12))

        self.lbl_tipo = tk.Label(destaque, text='Modo atual: Despesa', font=('Segoe UI', 10, 'bold'), bg='#eef7ff', fg='#9a3412')
        self.lbl_tipo.pack(anchor='w', padx=10, pady=(8, 0))

        self.lbl_categorias = tk.Label(
            destaque,
            text='Categorias de despesa: Alimentação, Rolê, Extra e Vestuário.',
            font=('Segoe UI', 9),
            bg='#eef7ff',
            fg='#5f6f91'
        )
        self.lbl_categorias.pack(anchor='w', padx=10, pady=(2, 2))

        self.lbl_modo_edicao = tk.Label(destaque, textvariable=self.modo_edicao_var, font=('Segoe UI', 9, 'bold'), bg='#eef7ff', fg='#1d2a57')
        self.lbl_modo_edicao.pack(anchor='w', padx=10, pady=(0, 8))
        self.frame_destaque_edicao = destaque

        formulario = tk.Frame(parent, bg='white')
        formulario.pack(fill='both', expand=True, padx=14, pady=(0, 14))

        tk.Label(formulario, text='Tipo', font=('Segoe UI', 10, 'bold'), bg='white').pack(anchor='w')

        caixa_tipo = tk.Frame(formulario, bg='#eef4ff', bd=1, relief='solid', highlightbackground='#c9d8fb', highlightthickness=1)
        caixa_tipo.pack(fill='x', pady=(4, 12), ipady=6)

        tk.Radiobutton(caixa_tipo, text='Despesa', variable=self.tipo_var, value='Despesa', command=self.atualizar_menu_categorias, bg='#eef4ff', activebackground='#eef4ff', font=('Segoe UI', 10)).pack(anchor='w', padx=10)
        tk.Radiobutton(caixa_tipo, text='Receita', variable=self.tipo_var, value='Receita', command=self.atualizar_menu_categorias, bg='#eef4ff', activebackground='#eef4ff', font=('Segoe UI', 10)).pack(anchor='w', padx=10)

        corpo = tk.Frame(formulario, bg='white')
        corpo.pack(fill='both', expand=True)

        card_campos = tk.Frame(corpo, bg='#fbfcff', bd=1, relief='solid', highlightbackground='#dde6f7', highlightthickness=1)
        card_campos.pack(side='left', fill='both', expand=True, padx=(0, 10))

        campos = tk.Frame(card_campos, bg='#fbfcff')
        campos.pack(fill='both', expand=True, padx=10, pady=10)

        tk.Label(campos, text='Categoria', font=('Segoe UI', 10, 'bold'), bg='#fbfcff').pack(anchor='w')
        wrapper_categoria = tk.Frame(campos, bg='#fbfcff')
        wrapper_categoria.pack(fill='x', pady=(4, 12))

        self.menu_categoria = tk.OptionMenu(wrapper_categoria, self.categoria_var, *CATEGORIAS_DESPESA)
        self.menu_categoria.config(font=('Segoe UI', 10), bg='#f5f7fb', relief='solid', bd=1, highlightthickness=0, anchor='w', width=20)
        self.menu_categoria['menu'].config(font=('Segoe UI', 10))
        self.menu_categoria.pack(fill='x', ipady=4)

        tk.Label(campos, text='Nome', font=('Segoe UI', 10, 'bold'), bg='#fbfcff').pack(anchor='w')
        tk.Entry(campos, textvariable=self.nome_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 12), ipady=6)

        tk.Label(campos, text='Data (dd/mm/aaaa)', font=('Segoe UI', 10, 'bold'), bg='#fbfcff').pack(anchor='w')
        linha_data = tk.Frame(campos, bg='#fbfcff')
        linha_data.pack(fill='x', pady=(4, 12))
        tk.Entry(linha_data, textvariable=self.data_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(side='left', fill='x', expand=True, ipady=6)
        tk.Button(linha_data, text='📅', command=self.abrir_calendario, bg='#eef3ff', fg='#1d2a57', relief='flat').pack(side='left', padx=(8, 0), ipadx=10, ipady=6)

        tk.Label(campos, text='Valor', font=('Segoe UI', 10, 'bold'), bg='#fbfcff').pack(anchor='w')
        tk.Entry(campos, textvariable=self.valor_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 12), ipady=6)

        tk.Label(campos, text='Observação', font=('Segoe UI', 10, 'bold'), bg='#fbfcff').pack(anchor='w')
        tk.Entry(campos, textvariable=self.observacao_var, font=('Segoe UI', 10), relief='solid', bd=1).pack(fill='x', pady=(4, 4), ipady=6)

        painel_lateral = tk.Frame(corpo, bg='white', width=180)
        painel_lateral.pack(side='left', fill='y')
        painel_lateral.pack_propagate(False)

        card_acoes = tk.Frame(painel_lateral, bg='#f8fbff', bd=1, relief='solid', highlightbackground='#d7e6ff', highlightthickness=1)
        card_acoes.pack(fill='x', pady=(0, 10))
        tk.Label(card_acoes, text='Ações do lançamento', font=('Segoe UI', 10, 'bold'), bg='#f8fbff', fg='#1d2a57').pack(anchor='w', padx=10, pady=(10, 8))

        botoes_acoes = [
            ('Salvar', self.salvar_transacao, '#4a90e2', 'white'),
            ('Limpar', self.limpar_formulario, '#f0f2f7', '#1d2a57'),
            ('Editar selecionado', self.carregar_selecionado, '#eef3ff', '#1d2a57'),
            ('Cancelar edição', self.cancelar_edicao, '#fff3cd', '#856404'),
            ('Excluir selecionado', self.excluir_selecionado, '#fde2e1', '#8a1c1c'),
            ('Importar CSV', self.importar_csv, '#e6f6ed', '#125c2f'),
            ('Exportar CSV', self.exportar_csv, '#daf0e5', '#125c2f'),
        ]

        for texto, comando, bg, fg in botoes_acoes:
            tk.Button(card_acoes, text=texto, command=comando, bg=bg, fg=fg, relief='flat').pack(fill='x', padx=10, pady=(0, 8), ipady=8)


    def montar_tabela(self, parent):
        card_tabela = tk.Frame(parent, bg='white', bd=1, relief='solid')
        card_tabela.pack(fill='both', expand=True)

        cabecalho = tk.Frame(card_tabela, bg='white')
        cabecalho.pack(fill='x', padx=12, pady=(10, 8))
        tk.Label(cabecalho, text='Lançamentos', font=('Segoe UI', 13, 'bold'), bg='white', fg='#1d2a57').pack(side='left')

        faixa_filtro = tk.Frame(card_tabela, bg='white')
        faixa_filtro.pack(fill='x', padx=12, pady=(0, 8))

        tk.Label(faixa_filtro, text='Mês:', font=('Segoe UI', 10, 'bold'), bg='white', fg='#1d2a57').grid(row=0, column=0, sticky='w')
        self.combo_mes = ttk.Combobox(faixa_filtro, textvariable=self.filtro_mes_var, values=OPCOES_MES, state='readonly', width=19, font=('Segoe UI', 10))
        self.combo_mes.grid(row=0, column=1, padx=(6, 10), sticky='w')
        self.combo_mes.bind('<<ComboboxSelected>>', lambda e: self.alterar_filtro_mes())

        tk.Label(faixa_filtro, text='Tipo:', font=('Segoe UI', 10, 'bold'), bg='white', fg='#1d2a57').grid(row=0, column=2, sticky='w')
        self.combo_tipo = ttk.Combobox(faixa_filtro, textvariable=self.filtro_tipo_var, values=TIPOS_FILTRO, state='readonly', width=12, font=('Segoe UI', 10))
        self.combo_tipo.grid(row=0, column=3, padx=(6, 10), sticky='w')
        self.combo_tipo.bind('<<ComboboxSelected>>', lambda e: self.atualizar_tudo())

        tk.Label(faixa_filtro, text='Categoria:', font=('Segoe UI', 10, 'bold'), bg='white', fg='#1d2a57').grid(row=0, column=4, sticky='w')
        self.combo_categoria_filtro = ttk.Combobox(faixa_filtro, textvariable=self.filtro_categoria_var, values=['Todas'], state='readonly', width=16, font=('Segoe UI', 10))
        self.combo_categoria_filtro.grid(row=0, column=5, padx=(6, 10), sticky='w')
        self.combo_categoria_filtro.bind('<<ComboboxSelected>>', lambda e: self.atualizar_tudo())

        tk.Label(faixa_filtro, text='Buscar nome:', font=('Segoe UI', 10, 'bold'), bg='white', fg='#1d2a57').grid(row=1, column=0, sticky='w', pady=(8, 0))
        entry_busca = tk.Entry(faixa_filtro, textvariable=self.busca_nome_var, font=('Segoe UI', 10), relief='solid', bd=1)
        entry_busca.grid(row=1, column=1, columnspan=3, padx=(6, 10), sticky='ew', pady=(8, 0), ipady=4)
        entry_busca.bind('<KeyRelease>', lambda e: self.atualizar_tudo())

        tk.Button(faixa_filtro, text='Ver histórico completo', command=self.mostrar_historico_completo, bg='#f0f2f7', fg='#1d2a57', relief='flat').grid(row=1, column=4, columnspan=2, sticky='ew', pady=(8, 0))
        tk.Label(faixa_filtro, textvariable=self.info_filtro_var, font=('Segoe UI', 9), bg='white', fg='#5f6f91').grid(row=0, column=6, rowspan=2, padx=(10, 0), sticky='e')

        faixa_filtro.columnconfigure(1, weight=1)

        colunas = ('id', 'name', 'category', 'date', 'amount', 'type', 'note')
        self.tree = ttk.Treeview(card_tabela, columns=colunas, show='headings', height=11)

        titulos = {
            'id': 'ID',
            'name': 'Nome',
            'category': 'Categoria',
            'date': 'Data',
            'amount': 'Quantia',
            'type': 'Tipo',
            'note': 'Observação',
        }

        larguras = {
            'id': 60,
            'name': 180,
            'category': 120,
            'date': 100,
            'amount': 120,
            'type': 90,
            'note': 220,
        }

        for coluna in colunas:
            self.tree.heading(coluna, text=titulos[coluna], command=lambda c=coluna: self.ordenar_por(c))
            ancora = 'e' if coluna == 'amount' else 'center'
            if coluna in ('name', 'note'):
                ancora = 'w'
            self.tree.column(coluna, width=larguras[coluna], anchor=ancora)

        container_tabela = tk.Frame(card_tabela, bg='white')
        container_tabela.pack(fill='both', expand=True, padx=12, pady=(0, 0))

        barra_vertical = ttk.Scrollbar(container_tabela, orient='vertical', command=self.tree.yview)
        barra_horizontal = ttk.Scrollbar(card_tabela, orient='horizontal', command=self.tree.xview)

        self.tree.configure(yscrollcommand=barra_vertical.set, xscrollcommand=barra_horizontal.set)

        self.tree.pack(side='left', fill='both', expand=True)
        barra_vertical.pack(side='right', fill='y')
        barra_horizontal.pack(fill='x', padx=12, pady=(0, 10))

        self.tree.tag_configure('receita', background='#e7f6ec', foreground='#125c2f')
        self.tree.tag_configure('despesa', background='#fff0ea', foreground='#8a3412')

        self.tree.bind('<<TreeviewSelect>>', self.quando_selecionar_tabela)

    def montar_graficos(self, parent):
        area_graficos = tk.Frame(parent, bg='#eef2f8')
        area_graficos.pack(fill='both', expand=False, pady=(10, 0))

        card_pizza = tk.Frame(area_graficos, bg='white', bd=1, relief='solid')
        card_pizza.pack(side='left', fill='both', expand=True, padx=(0, 5))
        tk.Label(card_pizza, text='Despesas por categoria', font=('Segoe UI', 12, 'bold'), bg='white', fg='#1d2a57').pack(anchor='w', padx=12, pady=(10, 4))

        self.figura_pizza = Figure(figsize=(4.2, 2.6), dpi=100)
        self.eixo_pizza = self.figura_pizza.add_subplot(111)
        self.canvas_pizza = FigureCanvasTkAgg(self.figura_pizza, card_pizza)
        self.canvas_pizza.get_tk_widget().pack(fill='both', expand=True, padx=8, pady=8)

        card_barras = tk.Frame(area_graficos, bg='white', bd=1, relief='solid')
        card_barras.pack(side='left', fill='both', expand=True, padx=(5, 0))
        tk.Label(card_barras, text='Receita x Despesa x Saldo', font=('Segoe UI', 12, 'bold'), bg='white', fg='#1d2a57').pack(anchor='w', padx=12, pady=(10, 4))

        self.figura_barras = Figure(figsize=(4.2, 2.6), dpi=100)
        self.eixo_barras = self.figura_barras.add_subplot(111)
        self.canvas_barras = FigureCanvasTkAgg(self.figura_barras, card_barras)
        self.canvas_barras.get_tk_widget().pack(fill='both', expand=True, padx=8, pady=8)

    def obter_month_ref(self):
        if self.filtro_mes_var.get() != 'Histórico completo':
            mes = self.filtro_mes_var.get()[:2]
        else:
            mes = datetime.now().strftime('%m')
        ano = datetime.now().strftime('%Y')
        return f'{ano}-{mes}'

    def carregar_metas_mes_atual(self):
        metas = self.banco.obter_metas_mes(self.usuario['id'], self.obter_month_ref())
        self.meta_gasto_var.set('' if metas['gasto_maximo'] is None else str(metas['gasto_maximo']).replace('.', ','))
        self.meta_economia_var.set('' if metas['economia_minima'] is None else str(metas['economia_minima']).replace('.', ','))

    def salvar_metas(self):
        month_ref = self.obter_month_ref()
        try:
            if self.meta_gasto_var.get().strip():
                gasto = self.interpretar_valor(self.meta_gasto_var.get())
                self.banco.salvar_meta(self.usuario['id'], month_ref, 'gasto_maximo', gasto)

            if self.meta_economia_var.get().strip():
                economia = self.interpretar_valor(self.meta_economia_var.get())
                self.banco.salvar_meta(self.usuario['id'], month_ref, 'economia_minima', economia)

            messagebox.showinfo('Sucesso', 'Metas salvas com sucesso.')
            self.atualizar_dashboard()
        except Exception:
            messagebox.showwarning('Aviso', 'Informe valores válidos nas metas.')

    def fazer_backup_banco(self):
        destino = filedialog.asksaveasfilename(
            title='Salvar backup do banco',
            defaultextension='.db',
            filetypes=[('Banco de dados SQLite', '*.db'), ('Todos os arquivos', '*.*')],
            initialfile=f'backup_financeiro_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
        )
        if not destino:
            return

        try:
            self.banco.conn.commit()
            shutil.copyfile(DB_NAME, destino)
            messagebox.showinfo('Sucesso', 'Backup realizado com sucesso.')
        except Exception as e:
            messagebox.showerror('Erro', f'Não foi possível fazer o backup.\n\n{e}')

    def exportar_csv(self):
        caminho = filedialog.asksaveasfilename(
            title='Exportar relatório CSV',
            defaultextension='.csv',
            filetypes=[('Arquivo CSV', '*.csv')],
            initialfile=f'relatorio_financeiro_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        if not caminho:
            return

        linhas = self.obter_linhas_filtradas()
        try:
            with open(caminho, 'w', newline='', encoding='utf-8-sig') as arquivo:
                writer = csv.writer(arquivo, delimiter=';')
                writer.writerow(['ID', 'Nome', 'Categoria', 'Data', 'Valor', 'Tipo', 'Observação'])
                for linha in linhas:
                    writer.writerow([
                        linha['id'],
                        linha['name'],
                        linha['category'],
                        converter_data_para_br(linha['date']),
                        f'{linha["amount"]:.2f}'.replace('.', ','),
                        linha['type'],
                        linha['note'] if 'note' in linha.keys() else '',
                    ])
            messagebox.showinfo('Sucesso', 'Relatório exportado com sucesso.')
        except Exception as e:
            messagebox.showerror('Erro', f'Não foi possível exportar o relatório.\n\n{e}')

    def importar_csv(self):
        caminho = filedialog.askopenfilename(
            title='Importar CSV',
            filetypes=[('Arquivo CSV', '*.csv'), ('Todos os arquivos', '*.*')]
        )
        if not caminho:
            return

        try:
            with open(caminho, 'r', encoding='utf-8-sig', newline='') as arquivo:
                amostra = arquivo.read(4096)
                arquivo.seek(0)
                try:
                    dialeto = csv.Sniffer().sniff(amostra, delimiters=';,')
                    delimitador = dialeto.delimiter
                except Exception:
                    delimitador = ';' if amostra.count(';') >= amostra.count(',') else ','

                leitor = csv.DictReader(arquivo, delimiter=delimitador)
                if not leitor.fieldnames:
                    messagebox.showwarning('Aviso', 'O arquivo CSV não possui cabeçalho.')
                    return

                mapa = {normalizar_texto(campo): campo for campo in leitor.fieldnames if campo}

                def obter_campo(*nomes):
                    for nome in nomes:
                        chave = mapa.get(normalizar_texto(nome))
                        if chave:
                            return chave
                    return None

                campo_tipo = obter_campo('tipo', 'type')
                campo_nome = obter_campo('nome', 'name', 'descricao', 'descrição')
                campo_categoria = obter_campo('categoria', 'category')
                campo_data = obter_campo('data', 'date')
                campo_valor = obter_campo('valor', 'amount')
                campo_obs = obter_campo('observacao', 'observação', 'obs', 'note')

                obrigatorios = [campo_tipo, campo_nome, campo_categoria, campo_data, campo_valor]
                if any(campo is None for campo in obrigatorios):
                    messagebox.showwarning('Aviso', 'O CSV precisa ter as colunas Tipo, Nome, Categoria, Data e Valor.')
                    return

                transacoes = []
                linhas_invalidas = 0
                for linha in leitor:
                    try:
                        tipo = (linha.get(campo_tipo) or '').strip().capitalize()
                        if tipo not in ('Receita', 'Despesa'):
                            raise ValueError('Tipo inválido')

                        nome = (linha.get(campo_nome) or '').strip()
                        categoria = (linha.get(campo_categoria) or '').strip()
                        data_bruta = (linha.get(campo_data) or '').strip()
                        valor_bruto = (linha.get(campo_valor) or '').strip()
                        observacao = (linha.get(campo_obs) or '').strip() if campo_obs else ''

                        if not nome or not categoria or not data_bruta or not valor_bruto:
                            raise ValueError('Dados incompletos')

                        if '/' in data_bruta:
                            data_iso = converter_data_para_iso(data_bruta)
                        else:
                            data_iso = datetime.strptime(data_bruta, '%Y-%m-%d').strftime('%Y-%m-%d')

                        valor = self.interpretar_valor(valor_bruto)
                        if valor <= 0:
                            raise ValueError('Valor inválido')

                        transacoes.append({
                            'type': tipo,
                            'name': nome,
                            'category': categoria,
                            'date': data_iso,
                            'amount': valor,
                            'note': observacao
                        })
                    except Exception:
                        linhas_invalidas += 1

            if not transacoes:
                messagebox.showwarning('Aviso', 'Nenhuma linha válida foi encontrada no arquivo.')
                return

            self.banco.importar_transacoes_em_lote(self.usuario['id'], transacoes)
            self.atualizar_tudo()
            messagebox.showinfo('Importação concluída', f'{len(transacoes)} linha(s) importada(s) com sucesso.\nLinhas inválidas: {linhas_invalidas}.')
        except Exception as e:
            messagebox.showerror('Erro', f'Não foi possível importar o CSV.\n\n{e}')

    def abrir_calendario(self):
        CalendarioMini(self, data_inicial=self.data_var.get(), ao_selecionar=self.definir_data_selecionada)

    def definir_data_selecionada(self, data_str):
        self.data_var.set(data_str)

    def mostrar_historico_completo(self):
        self.filtro_mes_var.set('Histórico completo')
        self.filtro_tipo_var.set('Todos')
        self.filtro_categoria_var.set('Todas')
        self.busca_nome_var.set('')
        self.alterar_filtro_mes()

    def alterar_filtro_mes(self):
        atual = self.filtro_mes_var.get()
        if atual == 'Histórico completo':
            self.info_filtro_var.set('Exibindo: histórico completo')
        else:
            self.info_filtro_var.set(f'Exibindo apenas: {atual}')
        self.carregar_metas_mes_atual()
        self.atualizar_tudo()

    def atualizar_menu_categorias(self):
        categorias = CATEGORIAS_RECEITA if self.tipo_var.get() == 'Receita' else CATEGORIAS_DESPESA

        if self.categoria_var.get() not in categorias:
            self.categoria_var.set(categorias[0])

        menu = self.menu_categoria['menu']
        menu.delete(0, 'end')

        for categoria in categorias:
            menu.add_command(label=categoria, command=lambda valor=categoria: self.categoria_var.set(valor))

        if self.tipo_var.get() == 'Receita':
            self.lbl_tipo.config(text='Modo atual: Receita', fg='#1b5e20')
            self.lbl_categorias.config(text='Categorias de receita: PIX, Trabalho, Transferência, Venda e Outro.')
        else:
            self.lbl_tipo.config(text='Modo atual: Despesa', fg='#9a3412')
            self.lbl_categorias.config(text='Categorias de despesa: Alimentação, Rolê, Extra e Vestuário.')

    def atualizar_combo_categorias_filtro(self):
        categorias = ['Todas'] + sorted(set(CATEGORIAS_DESPESA + CATEGORIAS_RECEITA))
        self.combo_categoria_filtro['values'] = categorias
        if self.filtro_categoria_var.get() not in categorias:
            self.filtro_categoria_var.set('Todas')

    def quando_selecionar_tabela(self, _event=None):
        selecionados = self.tree.selection()
        if not selecionados:
            self.id_selecionado = None
            return
        valores = self.tree.item(selecionados[0], 'values')
        self.id_selecionado = int(valores[0])

    def obter_linhas_filtradas(self):
        return self.banco.obter_transacoes(
            self.usuario['id'],
            self.filtro_mes_var.get(),
            self.filtro_tipo_var.get(),
            self.filtro_categoria_var.get(),
            self.busca_nome_var.get()
        )

    def obter_linha_selecionada_banco(self):
        if self.id_selecionado is None:
            return None

        cur = self.banco.conn.cursor()
        cur.execute('SELECT * FROM transactions WHERE id = ? AND user_id = ?', (self.id_selecionado, self.usuario['id']))
        return cur.fetchone()

    def carregar_selecionado(self):
        linha = self.obter_linha_selecionada_banco()
        if linha is None:
            messagebox.showwarning('Aviso', 'Selecione um lançamento na tabela.')
            return

        self.id_selecionado = linha['id']
        self.tipo_var.set(linha['type'])
        self.atualizar_menu_categorias()
        self.categoria_var.set(linha['category'])
        self.nome_var.set(linha['name'])
        self.data_var.set(converter_data_para_br(linha['date']))
        self.valor_var.set(f"{linha['amount']:.2f}".replace('.', ','))
        self.observacao_var.set(linha['note'] if 'note' in linha.keys() else '')
        self.modo_edicao_var.set(f'Modo atual: editando lançamento ID {linha["id"]} - {linha["name"]}')

        self.frame_destaque_edicao.config(bg='#fff4d6', highlightbackground='#e9b949')
        self.lbl_tipo.config(bg='#fff4d6')
        self.lbl_categorias.config(bg='#fff4d6')
        self.lbl_modo_edicao.config(bg='#fff4d6')

        messagebox.showinfo('Modo edição', 'Você está editando um lançamento.\nUse "Cancelar edição" para sair desse modo.')

    def cancelar_edicao(self):
        self.limpar_formulario()
        messagebox.showinfo('Edição cancelada', 'Você saiu do modo de edição.')

    def limpar_formulario(self, manter_tipo=False):
        self.id_selecionado = None
        tipo_atual = self.tipo_var.get() if manter_tipo else 'Despesa'
        self.tipo_var.set(tipo_atual)
        self.atualizar_menu_categorias()

        categorias = CATEGORIAS_RECEITA if tipo_atual == 'Receita' else CATEGORIAS_DESPESA
        self.categoria_var.set(categorias[0])
        self.nome_var.set('')
        self.data_var.set(datetime.now().strftime('%d/%m/%Y'))
        self.valor_var.set('')
        self.observacao_var.set('')
        self.modo_edicao_var.set('Modo atual: novo lançamento')

        self.frame_destaque_edicao.config(bg='#eef7ff', highlightbackground='#b8d6ff')
        self.lbl_tipo.config(bg='#eef7ff')
        self.lbl_categorias.config(bg='#eef7ff')
        self.lbl_modo_edicao.config(bg='#eef7ff')

        for item in self.tree.selection():
            self.tree.selection_remove(item)

    def interpretar_valor(self, bruto: str) -> float:
        bruto = bruto.strip().replace('.', '').replace(',', '.')
        return float(bruto)

    def salvar_transacao(self):
        tipo = self.tipo_var.get().strip()
        categoria = self.categoria_var.get().strip()
        nome = self.nome_var.get().strip()
        data_br = self.data_var.get().strip()
        valor_str = self.valor_var.get().strip()
        observacao = self.observacao_var.get().strip()

        if not nome:
            messagebox.showwarning('Aviso', 'Informe o nome do lançamento.')
            return

        try:
            data_iso = converter_data_para_iso(data_br)
        except Exception:
            messagebox.showwarning('Aviso', 'Data inválida. Use o formato dd/mm/aaaa.')
            return

        try:
            valor = self.interpretar_valor(valor_str)
            if valor <= 0:
                raise ValueError
        except Exception:
            messagebox.showwarning('Aviso', 'Informe um valor válido maior que zero.')
            return

        if self.id_selecionado is None:
            self.banco.adicionar_transacao(self.usuario['id'], tipo, nome, categoria, data_iso, valor, observacao)
            messagebox.showinfo('Sucesso', 'Lançamento cadastrado com sucesso.')
        else:
            if not messagebox.askyesno('Confirmar edição', 'Deseja realmente salvar as alterações deste lançamento?'):
                return
            self.banco.atualizar_transacao(self.id_selecionado, self.usuario['id'], tipo, nome, categoria, data_iso, valor, observacao)
            messagebox.showinfo('Sucesso', 'Lançamento atualizado com sucesso.')

        manter_tipo = self.id_selecionado is None
        self.limpar_formulario(manter_tipo=manter_tipo)
        self.atualizar_tudo()

    def excluir_selecionado(self):
        if self.id_selecionado is None:
            messagebox.showwarning('Aviso', 'Selecione um lançamento para excluir.')
            return

        if not messagebox.askyesno('Confirmar exclusão', 'Deseja realmente excluir o lançamento selecionado?'):
            return

        self.banco.excluir_transacao(self.id_selecionado, self.usuario['id'])
        self.limpar_formulario()
        self.atualizar_tudo()

    def atualizar_tudo(self):
        self.atualizar_tabela()
        self.atualizar_resumo()
        self.atualizar_graficos()
        self.atualizar_dashboard()

    def atualizar_tabela(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        linhas = self.obter_linhas_filtradas()

        for linha in linhas:
            valores = (
                linha['id'],
                linha['name'],
                linha['category'],
                converter_data_para_br(linha['date']),
                formatar_moeda(linha['amount']),
                linha['type'],
                linha['note'] if 'note' in linha.keys() else '',
            )
            tag_linha = 'receita' if linha['type'] == 'Receita' else 'despesa'
            self.tree.insert('', 'end', values=valores, tags=(tag_linha,))

    def atualizar_resumo(self):
        resumo = self.banco.obter_resumo(
            self.usuario['id'],
            self.filtro_mes_var.get(),
            self.filtro_tipo_var.get(),
            self.filtro_categoria_var.get(),
            self.busca_nome_var.get()
        )
        self.total_receitas_var.set(f'Receitas: {formatar_moeda(resumo["receitas"])}')
        self.total_despesas_var.set(f'Despesas: {formatar_moeda(resumo["despesas"])}')
        self.saldo_var.set(f'Saldo: {formatar_moeda(resumo["saldo"])}')

    def atualizar_graficos(self):
        resumo = self.banco.obter_resumo(
            self.usuario['id'],
            self.filtro_mes_var.get(),
            self.filtro_tipo_var.get(),
            self.filtro_categoria_var.get(),
            self.busca_nome_var.get()
        )

        self.eixo_pizza.clear()
        categorias = [r['category'] for r in resumo['categorias_despesa']]
        valores = [float(r['total']) for r in resumo['categorias_despesa']]

        if valores:
            self.eixo_pizza.pie(valores, labels=categorias, autopct='%1.1f%%', startangle=90)
        else:
            self.eixo_pizza.text(0.5, 0.5, 'Sem despesas\npara exibir', ha='center', va='center', fontsize=12)

        self.eixo_pizza.set_title('')
        self.figura_pizza.tight_layout()
        self.canvas_pizza.draw()

        self.eixo_barras.clear()
        rotulos = ['Receitas', 'Despesas', 'Saldo']
        valores_barras = [resumo['receitas'], resumo['despesas'], resumo['saldo']]
        cores = ['#4CAF50', '#E76F51', '#4A90E2']

        barras = self.eixo_barras.bar(rotulos, valores_barras, color=cores)
        max_abs = max([abs(v) for v in valores_barras] + [1])
        deslocamento = max_abs * 0.03

        for barra, valor in zip(barras, valores_barras):
            x = barra.get_x() + barra.get_width() / 2
            y = valor + deslocamento if valor >= 0 else valor - deslocamento
            alinhamento_vertical = 'bottom' if valor >= 0 else 'top'
            self.eixo_barras.text(x, y, formatar_moeda(valor), ha='center', va=alinhamento_vertical, fontsize=9)

        self.eixo_barras.axhline(0, linewidth=1)
        self.eixo_barras.margins(y=0.25)
        self.figura_barras.tight_layout()
        self.canvas_barras.draw()

    def atualizar_dashboard(self):
        resumo = self.banco.obter_resumo(
            self.usuario['id'],
            self.filtro_mes_var.get(),
            self.filtro_tipo_var.get(),
            self.filtro_categoria_var.get(),
            self.busca_nome_var.get()
        )

        categoria_topo = self.banco.obter_categoria_topo_despesa(self.usuario['id'], self.filtro_mes_var.get())
        media_despesas = self.banco.obter_media_despesas(self.usuario['id'], self.filtro_mes_var.get())
        maior_receita = self.banco.obter_maior_receita(self.usuario['id'], self.filtro_mes_var.get())
        ultimas = self.banco.obter_ultimas_transacoes(self.usuario['id'], 5)
        metas = self.banco.obter_metas_mes(self.usuario['id'], self.obter_month_ref())

        texto1 = []
        texto1.append(f"Total de lançamentos filtrados: {resumo['quantidade']}")
        texto1.append(f"Maior receita: {maior_receita['name']} ({formatar_moeda(maior_receita['amount'])})" if maior_receita else "Maior receita: nenhuma")
        texto1.append(f"Categoria com maior gasto: {categoria_topo['category']} ({formatar_moeda(categoria_topo['total'])})" if categoria_topo else "Categoria com maior gasto: nenhuma")
        texto1.append(f"Média das despesas: {formatar_moeda(media_despesas)}")

        if metas['gasto_maximo'] is not None:
            situacao_gasto = 'dentro da meta' if resumo['despesas'] <= metas['gasto_maximo'] else 'acima da meta'
            texto1.append(f"Meta de gasto: {formatar_moeda(metas['gasto_maximo'])} ({situacao_gasto})")
        else:
            texto1.append("Meta de gasto: não definida")

        if metas['economia_minima'] is not None:
            situacao_economia = 'atingida' if resumo['saldo'] >= metas['economia_minima'] else 'não atingida'
            texto1.append(f"Meta de economia: {formatar_moeda(metas['economia_minima'])} ({situacao_economia})")
        else:
            texto1.append("Meta de economia: não definida")

        texto2 = ['Últimas 5 movimentações:']
        if ultimas:
            for linha in ultimas:
                texto2.append(
                    f"- {converter_data_para_br(linha['date'])} | {linha['name']} | {linha['type']} | {formatar_moeda(linha['amount'])}"
                )
        else:
            texto2.append("- Nenhuma movimentação cadastrada")

        self.texto_info_esquerda = '\n'.join(texto1)
        self.texto_info_direita = '\n'.join(texto2)

        if self.janela_infos and self.janela_infos.winfo_exists():
            self.janela_infos.atualizar_textos(self.texto_info_esquerda, self.texto_info_direita)

    def abrir_janela_infos_rapidas(self):
        self.atualizar_dashboard()

        if self.janela_infos and self.janela_infos.winfo_exists():
            self.janela_infos.lift()
            self.janela_infos.focus_force()
            self.janela_infos.atualizar_textos(self.texto_info_esquerda, self.texto_info_direita)
            return

        self.janela_infos = JanelaInformacoesRapidas(self, self.texto_info_esquerda, self.texto_info_direita)

    def abrir_janela_metas(self):
        if self.janela_metas and self.janela_metas.winfo_exists():
            self.janela_metas.lift()
            self.janela_metas.focus_force()
            return

        self.janela_metas = JanelaMetas(self, self.banco, self.usuario, ao_atualizar=self.atualizar_dashboard)

    def ordenar_por(self, coluna):
        dados = [(self.tree.set(item, coluna), item) for item in self.tree.get_children('')]
        reverso = self.estado_ordenacao.get(coluna, False)
        self.estado_ordenacao[coluna] = not reverso

        def chave_ordenacao(entrada):
            valor = entrada[0]
            if coluna == 'id':
                return int(valor)
            if coluna == 'date':
                return datetime.strptime(valor, '%d/%m/%Y')
            if coluna == 'amount':
                valor_limpo = valor.replace('R$', '').strip().replace('.', '').replace(',', '.')
                return float(valor_limpo)
            return str(valor).lower()

        dados.sort(key=chave_ordenacao, reverse=reverso)

        for indice, (_, item) in enumerate(dados):
            self.tree.move(item, '', indice)

    def confirmar_troca_usuario(self):
        if messagebox.askyesno('Trocar usuário', 'Tem certeza que deseja voltar ao menu principal?'):
            self.ao_sair_conta()

    def confirmar_saida_app(self):
        if messagebox.askyesno('Sair', 'Tem certeza que deseja voltar para a área de trabalho?'):
            self.master.destroy()


class Aplicacao(tk.Tk):
    def __init__(self):
        super().__init__()
        self.banco = BancoDados()
        self.title('Controle Financeiro')
        self.geometry('1320x860')
        self.minsize(1200, 760)
        self.configure(bg='#eef2f8')
        self.protocol('WM_DELETE_WINDOW', self.confirmar_saida)
        self.view_atual = None
        self.iniciar_em_tela_cheia()

        self.configurar_estilo()
        self.mostrar_login()

    def iniciar_em_tela_cheia(self):
        try:
            self.state('zoomed')
        except Exception:
            try:
                self.attributes('-zoomed', True)
            except Exception:
                largura = self.winfo_screenwidth()
                altura = self.winfo_screenheight()
                self.geometry(f'{largura}x{altura}+0+0')

    def configurar_estilo(self):
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except Exception:
            pass

        style.configure('Treeview', rowheight=28, font=('Segoe UI', 10), background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'))

    def limpar_view(self):
        if self.view_atual is not None:
            self.view_atual.destroy()
            self.view_atual = None

    def mostrar_login(self):
        self.limpar_view()
        self.view_atual = TelaLogin(self, self.banco, self.mostrar_principal, self.abrir_cadastro_usuario)
        self.view_atual.pack(fill='both', expand=True)

    def abrir_cadastro_usuario(self):
        JanelaCadastroUsuario(self, self.banco)

    def mostrar_principal(self, usuario):
        self.limpar_view()
        self.view_atual = TelaPrincipal(self, self.banco, usuario, self.mostrar_login)
        self.view_atual.pack(fill='both', expand=True)

    def confirmar_saida(self):
        if messagebox.askyesno('Sair', 'Tem certeza que deseja voltar para a área de trabalho?'):
            self.destroy()


if __name__ == '__main__':
    app = Aplicacao()
    app.mainloop()
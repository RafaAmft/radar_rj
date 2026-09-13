"""
Schema DDL e definições relacionais do Radar de Oportunidades em Recuperação de Ativos.

Compatível com SQLite (armazenamento local / in-memory de testes) e portável para PostgreSQL.
"""

from __future__ import annotations

DDL_SCHEMA = """
-- ==============================================================================
-- TABELA: empresas
-- Empresas monitoradas pelo Radar (devedoras ou recuperandas).
-- ==============================================================================
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    nome_razao_social TEXT NOT NULL,
    cnpj TEXT,
    setor TEXT,
    origem_fonte TEXT DEFAULT 'manual', -- 'cvm', 'aj_ruiz', 'exm', 'tjsp', etc.
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- TABELA: processos
-- Processos judiciais de Recuperação Judicial, Extrajudicial ou Falência.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS processos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    numero_cnj TEXT,
    vara_comarca TEXT,
    administrador_judicial TEXT,
    tipo_processo TEXT DEFAULT 'recuperacao_judicial', -- 'recuperacao_judicial', 'recuperacao_extrajudicial', 'falencia'
    url_detalhe TEXT,
    valor_causa REAL DEFAULT 0.0,
    tribunal TEXT,
    status_processual TEXT DEFAULT 'Em Andamento',
    data_distribuicao TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (empresa_id) REFERENCES empresas (id) ON DELETE CASCADE
);

-- ==============================================================================
-- TABELA: marcos_processuais
-- Linha do tempo de peças-chave, decisões e manifestações do Administrador Judicial.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS marcos_processuais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER NOT NULL,
    data_evento TEXT NOT NULL,
    tipo_evento TEXT NOT NULL, -- 'PETICAO_INICIAL', 'DECISAO_PROCESSAMENTO', 'PRJ', 'QGC', 'RMA_AJ', 'MANIFESTACAO_AJ', 'AGC', 'HOMOLOGACAO', 'ENCERRAMENTO'
    titulo TEXT NOT NULL,
    descricao TEXT,
    autor TEXT DEFAULT 'AJ', -- 'JUIZO', 'AJ', 'RECUPERANDA', 'CREDOR', 'MP'
    url_documento TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (processo_id) REFERENCES processos (id) ON DELETE CASCADE
);

-- ==============================================================================
-- TABELA: documentos
-- Peças processuais, laudos, editais e deliberações em PDF.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER,
    empresa_id INTEGER NOT NULL,
    slug_documento TEXT,
    titulo TEXT NOT NULL,
    categoria TEXT NOT NULL, -- 'QGC', 'PRJ', 'RMA', 'AGC', 'EDITAL', 'OUTROS'
    url_download TEXT,
    caminho_arquivo TEXT,
    sha256 TEXT,
    total_paginas INTEGER DEFAULT 0,
    is_scanned BOOLEAN DEFAULT 0,
    tamanho_bytes INTEGER DEFAULT 0,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (processo_id) REFERENCES processos (id) ON DELETE SET NULL,
    FOREIGN KEY (empresa_id) REFERENCES empresas (id) ON DELETE CASCADE
);

-- ==============================================================================
-- TABELA: credores
-- Registros individuais extraídos dos Quadros Gerais de Credores (QGC).
-- ==============================================================================
CREATE TABLE IF NOT EXISTS credores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processo_id INTEGER,
    documento_id INTEGER,
    nome TEXT NOT NULL,
    documento_formatado TEXT,
    documento_limpo TEXT,
    tipo_documento TEXT DEFAULT 'DESCONHECIDO', -- 'CNPJ', 'CPF', 'ESTRANGEIRO', 'DESCONHECIDO'
    classe TEXT NOT NULL, -- 'I - Trabalhista', 'II - Garantia Real', 'III - Quirografário', 'IV - ME/EPP', 'Extraconcursal'
    natureza TEXT,
    valor_original REAL NOT NULL DEFAULT 0.0,
    moeda TEXT DEFAULT 'BRL',
    cidade TEXT,
    uf TEXT,
    pagina_origem INTEGER DEFAULT 1,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (processo_id) REFERENCES processos (id) ON DELETE CASCADE,
    FOREIGN KEY (documento_id) REFERENCES documentos (id) ON DELETE SET NULL
);

-- ==============================================================================
-- ÍNDICES DE ALTA PERFORMANCE PARA CONSULTAS ANALÍTICAS
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_empresas_slug ON empresas (slug);
CREATE INDEX IF NOT EXISTS idx_processos_empresa ON processos (empresa_id);
CREATE INDEX IF NOT EXISTS idx_processos_cnj ON processos (numero_cnj);
CREATE INDEX IF NOT EXISTS idx_documentos_processo ON documentos (processo_id);
CREATE INDEX IF NOT EXISTS idx_documentos_categoria ON documentos (categoria);
CREATE INDEX IF NOT EXISTS idx_documentos_sha256 ON documentos (sha256);
CREATE INDEX IF NOT EXISTS idx_credores_processo ON credores (processo_id);
CREATE INDEX IF NOT EXISTS idx_credores_documento_limpo ON credores (documento_limpo);
CREATE INDEX IF NOT EXISTS idx_credores_classe ON credores (classe);
CREATE INDEX IF NOT EXISTS idx_credores_valor ON credores (valor_original DESC);
CREATE INDEX IF NOT EXISTS idx_credores_nome ON credores (nome);
CREATE INDEX IF NOT EXISTS idx_marcos_processo ON marcos_processuais (processo_id);
CREATE INDEX IF NOT EXISTS idx_marcos_data ON marcos_processuais (data_evento);
CREATE INDEX IF NOT EXISTS idx_marcos_tipo ON marcos_processuais (tipo_evento);
"""

# 企业文档智能客服（Enterprise RAG Agent）

面向企业的私有知识库问答系统：**上传文档 → 混合检索（向量 + 关键词）→ LLM 生成（可选 Agent 工具推理）→ 会话历史与离线评估**。

后端 FastAPI + SQLAlchemy + ChromaDB，前端 Vue3 + Vite，一条命令启动前后端。

## 目录结构（讲解版）

```
enterprise_rag_agent/
├── run.py              # 一键启动：后端(:8000) + 前端(:5173)
├── README.md           # 本文件
│
├── backend/            # ── 后端（FastAPI）──
│   ├── .env            # 环境变量（模型密钥、数据库、检索参数）
│   ├── requirements.txt
│   └── app/
│       ├── main.py     # 入口：中间件、鉴权、路由注册、启动建表
│       ├── config.py   # 配置中心（读取 .env）
│       ├── api/        # 接口层（5 个接口平铺）
│       │   ├── auth.py       # 注册/登录：账号密码 + token，user/admin 分级
│       │   ├── upload.py     # 文档：上传 / 列表 / 删除
│       │   ├── chat.py      # 问答：检索 + 生成
│       │   ├── history.py   # 会话历史
│       │   └── evaluate.py  # 离线评估
│       ├── rag/        # RAG + Agent 核心
│       │   ├── embedding.py   # 向量化（OpenAI 兼容）
│       │   ├── vector_store.py# 向量库（ChromaDB）
│       │   ├── retriever.py   # 混合检索（向量+BM25，RRF 融合）
│       │   ├── reranker.py    # 可选重排
│       │   ├── llm.py         # LLM 生成
│       │   ├── document_processor.py # 文档解析
│       │   ├── ingestion.py   # 入库：解析→切分→向量化→双写
│       │   ├── retrieval.py   # 检索服务编排
│       │   ├── qa.py          # 问答服务编排
│       │   ├── evaluation.py  # 评估：hit@k / MRR / 忠实度
│       │   ├── agent.py       # ReAct 循环
│       │   └── tools.py       # Agent 工具（检索 / 计算器 / 时间 / 联网）
│       ├── models/     # 数据模型
│       │   ├── database.py    # 引擎 / 会话 / 建表
│       │   ├── orm.py         # 全部 ORM（文档、会话、评估）
│       │   └── schemas.py     # Pydantic 请求/响应
│       └── utils/      # 工具：切分 / 日志（ID 生成在包内）
│
├── frontend/           # ── 前端（Vue3 + Vite）──
│   ├── index.html      # HTML 入口
│   ├── package.json    # 依赖：vue / vue-router / echarts / vite
│   ├── vite.config.js  # 端口 5173，代理 /api → :8000
│   └── src/
│       ├── main.js     # 入口 + 路由（4 个页面）
│       ├── App.vue     # 根组件：侧栏 + 页面切换 + Toast
│       ├── api.js      # 后端 API 封装
│       ├── styles.css  # 全局样式
│       ├── components/ # 共享组件（消息气泡）
│       └── views/      # 五个页面
│           ├── LoginView.vue   # 登录（普通用户 / 管理员切换）
│           ├── ChatView.vue    # 智能问答
│           ├── DocsView.vue    # 文档管理（管理员）
│           ├── HistoryView.vue # 会话历史
│           └── EvalView.vue    # 离线评估（管理员，含指标图表）
│
└── data/               # 运行时数据（自动生成，不入库）
    ├── sample_员工手册.md   # 示例文档
    ├── uploads/            # 上传的原始文件
    └── chroma_db/          # 向量库持久化
```

## 快速开始

```bash
# 1. 安装依赖（已装可跳过）
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend && npm install && cd ..

# 2. 配置模型：复制 backend/.env.example 为 backend/.env，填 LLM 密钥
#    （无密钥可用 backend/scripts/mock_llm_server.py 联调）

# 3. 一键启动
python run.py
```

- 前端控制台：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs

## 核心链路（一句话讲清）

1. **入库**：上传文档 → `rag/document_processor` 解析 → `utils/chunker` 切块 → `rag/embedding` 向量化 → 双写 `ChromaDB`（向量）+ `SQLite`（元数据）
2. **问答**：提问 → `rag/retriever` 混合检索（向量 + BM25 融合）→ 拼上下文 → `agent` ReAct 推理或直接 `rag/llm` 生成 → 返回答案 + 来源引用 + 推理轨迹
3. **评估**：一组问答 → 计算命中率 / MRR / 精确率 / 召回率（无需 LLM）+ 忠实度 / 切题度（LLM 判分）

## 面试可讲的设计点

| 点 | 做了什么 | 为什么 |
| --- | --- | --- |
| 混合检索 | 向量 + BM25 双路召回，RRF/加权融合 | 向量对语义有效、对编号/术语不稳，两者互补 |
| 安全计算器 | AST 白名单求值，不用 eval | 防止 Agent 工具执行任意代码 |
| 防幻觉 | 回答强制附来源引用 + 忠实度评估 | 可追溯、可量化 |
| 可替换 | LLM/Embedding 全部 OpenAI 兼容接口 | 换 DeepSeek / 豆包 / Ollama 只改 .env |

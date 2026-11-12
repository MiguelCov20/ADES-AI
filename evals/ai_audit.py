"""Auditoría anti-IA (feature #24): vulnerabilidades típicas en código generado por IAs.

Combina reglas propias (AST + tokenize + regex, offline) con `bandit` ejecutado en
el sandbox Docker (`core.sandbox.run_command`). Detecta:

  - dependencias inexistentes / alucinadas y typosquatting (lista offline de paquetes
    conocidos + distancia de edición + variantes py-/python-/-py/-lib),
  - secretos hardcodeados (formatos reales de claves y asignaciones a password/token...),
  - eval/exec dinámicos, SQL construido por concatenación/f-strings,
  - shell=True / os.system, deserialización insegura (pickle, marshal, yaml.load...),
  - verificación TLS desactivada (verify=False, CERT_NONE, contexto no verificado),
  - rutas con `..` (path traversal),
  - prompts ocultos / instrucciones para LLMs en comentarios o strings, y caracteres
    invisibles o bidireccionales (Trojan Source).

API usada por el Reviewer de la fábrica:
    from evals.ai_audit import audit_files
    r = audit_files({"main.py": "..."})
    r["score"], r["veredicto"], r["hallazgos"]  # hallazgo: {severidad, archivo, linea, regla, detalle, fuente}
"""
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import PurePosixPath

SEVERIDADES = ("critica", "alta", "media", "baja")
PESOS = {"critica": 40, "alta": 20, "media": 8, "baja": 2}

# Nombres de import de paquetes PyPI conocidos/populares (offline). Ampliable con
# `known_packages=` o con los nombres de distribución equivalentes.
POPULAR = {
    "requests", "httpx", "urllib3", "aiohttp", "fastapi", "starlette", "uvicorn", "gunicorn",
    "flask", "django", "pydantic", "sqlalchemy", "alembic", "psycopg2", "psycopg", "pymysql",
    "pymongo", "redis", "celery", "kombu", "numpy", "pandas", "scipy", "sklearn", "matplotlib",
    "seaborn", "plotly", "torch", "torchvision", "tensorflow", "keras", "transformers",
    "datasets", "tokenizers", "accelerate", "langchain", "langchain_core", "langchain_community",
    "langchain_openai", "langchain_ollama", "langchain_google_genai", "langgraph", "openai",
    "anthropic", "ollama", "tiktoken", "qdrant_client", "neo4j", "graphiti_core", "chromadb",
    "faiss", "boto3", "botocore", "google", "jwt", "jose", "passlib", "bcrypt", "cryptography",
    "nacl", "paramiko", "yaml", "toml", "tomli", "tomllib", "dotenv", "click", "typer", "rich",
    "tqdm", "loguru", "structlog", "pytest", "hypothesis", "mock", "faker", "attr", "attrs",
    "dateutil", "pytz", "arrow", "pendulum", "bs4", "lxml", "html5lib", "PIL", "cv2", "imageio",
    "jinja2", "markupsafe", "werkzeug", "itsdangerous", "orjson", "ujson", "simplejson",
    "msgpack", "protobuf", "grpc", "websockets", "websocket", "socketio", "kafka", "pika",
    "docker", "kubernetes", "jsonschema", "marshmallow", "tenacity", "backoff", "cachetools",
    "diskcache", "joblib", "dask", "polars", "pyarrow", "openpyxl", "xlrd", "docx", "pptx",
    "pypdf", "PyPDF2", "fitz", "reportlab", "markdown", "mistune", "pygments", "sympy",
    "networkx", "statsmodels", "xgboost", "lightgbm", "catboost", "nltk", "spacy", "gensim",
    "sentence_transformers", "huggingface_hub", "safetensors", "selenium", "playwright",
    "scrapy", "tabulate", "colorama", "termcolor", "prompt_toolkit", "psutil", "setuptools",
    "pkg_resources", "wheel", "pip", "six", "typing_extensions", "certifi", "chardet",
    "charset_normalizer", "idna", "multidict", "yarl", "anyio", "sniffio", "h11", "httpcore",
    "bandit", "black", "ruff", "mypy", "flake8", "isort", "coverage", "tox", "nox", "invoke",
    "fabric", "ansible", "pexpect", "sh", "schedule", "apscheduler", "streamlit", "gradio",
    "dash", "bokeh", "altair", "sqlmodel", "tortoise", "peewee", "motor", "asyncpg",
    "aiosqlite", "elasticsearch", "minio", "stripe", "twilio", "sendgrid", "slack_sdk",
    "telegram", "discord", "tweepy", "praw", "github", "gitlab", "git", "sentry_sdk",
    "prometheus_client", "opentelemetry", "langfuse", "ragas", "deepeval", "cognee",
    "fastembed", "litellm", "mem0", "llama_index", "dspy", "instructor", "guidance",
    "mcp", "llmlingua", "tree_sitter", "tree_sitter_python", "tree_sitter_languages",
    "vllm", "unsloth", "peft", "trl", "bitsandbytes", "einops", "onnx", "onnxruntime",
}
# Nombres de distribución (requirements.txt) cuyo nombre difiere del import.
DIST_ALIASES = {
    "pyyaml": "yaml", "python-dotenv": "dotenv", "scikit-learn": "sklearn",
    "beautifulsoup4": "bs4", "pillow": "PIL", "opencv-python": "cv2", "pyjwt": "jwt",
    "python-jose": "jose", "python-dateutil": "dateutil", "psycopg2-binary": "psycopg2",
    "qdrant-client": "qdrant_client", "graphiti-core": "graphiti_core", "pymupdf": "fitz",
    "python-docx": "docx", "python-pptx": "pptx", "pynacl": "nacl", "protobuf": "protobuf",
    "grpcio": "grpc", "faiss-cpu": "faiss", "sentence-transformers": "sentence_transformers",
    "huggingface-hub": "huggingface_hub", "google-genai": "google",
    "langchain-core": "langchain_core", "langchain-community": "langchain_community",
    "langchain-openai": "langchain_openai", "langchain-ollama": "langchain_ollama",
    "langchain-google-genai": "langchain_google_genai", "llama-index": "llama_index",
    "python-socketio": "socketio", "websocket-client": "websocket", "kafka-python": "kafka",
    "slack-sdk": "slack_sdk", "python-telegram-bot": "telegram", "discord.py": "discord",
    "pygithub": "github", "python-gitlab": "gitlab", "gitpython": "git",
    "sentry-sdk": "sentry_sdk", "prometheus-client": "prometheus_client",
    "typing-extensions": "typing_extensions", "charset-normalizer": "charset_normalizer",
    "opentelemetry-api": "opentelemetry", "uvicorn[standard]": "uvicorn",
}
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
_TYPO_AFFIXES = [re.compile(r"^(?:python|py)[-_]?(.+)$", re.I),
                 re.compile(r"^(.+?)[-_]?(?:python|py|lib|dev|api)$", re.I)]

_KEY_FORMATS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "clave de acceso AWS"),
    (re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"), "clave API tipo sk- (OpenAI/Anthropic)"),
    (re.compile(r"\bsk_live_[A-Za-z0-9]{16,}"), "clave secreta Stripe live"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"), "token de GitHub"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"), "token fine-grained de GitHub"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}"), "clave API de Google"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "token de Slack"),
    (re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"), "clave privada"),
]
_SECRET_NAME = re.compile(r"(pass(word|wd)?|pwd|secret|token|api[_-]?key|apikey|private[_-]?key|"
                          r"access[_-]?key|client[_-]?secret|auth[_-]?key|credential)", re.I)
_PLACEHOLDER = re.compile(r"(changeme|change[_-]me|your[_-]|<.*>|example|dummy|xxx|\*\*\*|"
                          r"placeholder|todo|fixme|test|fake|sample|\$\{|%\(|\{\})", re.I)

_INJECTION = [
    re.compile(r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+"
               r"(instructions|prompts?|rules)", re.I),
    re.compile(r"ignora\s+(todas\s+)?(las\s+)?(instrucciones|reglas)\s+(anteriores|previas)", re.I),
    re.compile(r"disregard\s+(the\s+|all\s+)?(system|previous|prior|above)", re.I),
    re.compile(r"\b(you\s+are\s+now|from\s+now\s+on\s+you\s+are)\b", re.I),
    re.compile(r"\b(note|message|instructions?|attention)\s+(to|for)\s+(the\s+)?"
               r"(ai|llm|language\s+model|assistant|ai\s+reviewer|code\s+reviewer|agent)\b", re.I),
    re.compile(r"\b(as\s+an?\s+)(ai|llm|language\s+model)\b.*\b(must|should|always|never)\b", re.I),
    re.compile(r"\bdo\s+not\s+(tell|mention|reveal|report)\b.*\b(user|human|reviewer)\b", re.I),
    re.compile(r"\bno\s+(le\s+)?(digas|menciones|reveles|reportes)\b.*\b(usuario|revisor)\b", re.I),
    re.compile(r"\b(approve|aprueba)\s+(this|este|esta)\s+(pr|pull\s+request|code|c[oó]digo|"
               r"change|cambio)\b", re.I),
    re.compile(r"\b(reveal|print|leak|muestra|revela)\s+(your|the|tu|el)\s+(system\s+prompt|"
               r"prompt\s+de\s+sistema)\b", re.I),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|\[INST\]|<<SYS>>|</?system>|<\|system\|>", re.I),
]
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩\U000e0000-\U000e007f]")
_DOTDOT = re.compile(r"\.\.[\\/]|[\\/]\.\.(?:$|[\\/])")
_SQL = re.compile(r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|"
                  r"drop\s+table|create\s+table|where\s+\w+\s*=)", re.I | re.S)
_SQL_SINKS = {"execute", "executemany", "executescript", "raw", "text", "read_sql",
              "read_sql_query", "mogrify", "exec_driver_sql"}


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


class _Ctx:
    def __init__(self, known: set[str]):
        self.known = known
        self.known_norm = {_norm(k) for k in known}
        self.findings: list[dict] = []

    def add(self, sev, archivo, linea, regla, detalle, fuente="ast"):
        self.findings.append({"severidad": sev, "archivo": archivo, "linea": int(linea or 0),
                              "regla": regla, "detalle": detalle, "fuente": fuente})


def check_package(name: str, known: set[str] | None = None) -> tuple[str, str] | None:
    """Clasifica un nombre de paquete: None (conocido) o (regla, detalle)."""
    known = known if known is not None else (POPULAR | _STDLIB)
    n = _norm(name)
    known_norm = {_norm(k): k for k in known}
    if n in known_norm:
        return None
    for rx in _TYPO_AFFIXES:
        m = rx.match(n)
        core = _norm(m.group(1)).strip("_") if m else ""
        if core and core in known_norm and core != n:
            return ("typosquatting", f"'{name}' imita a '{known_norm[core]}' con prefijo/sufijo")
    best = min(((_levenshtein(n, k), orig) for k, orig in known_norm.items()
                if abs(len(k) - len(n)) <= 2 and len(k) >= 4), default=(99, ""))
    limit = 1 if len(n) < 8 else 2
    if 0 < best[0] <= limit:
        return ("typosquatting", f"'{name}' a distancia {best[0]} de '{best[1]}' (posible typosquatting)")
    return ("dependencia-desconocida",
            f"'{name}' no es stdlib ni un paquete conocido: posible paquete alucinado "
            "(slopsquatting); verifica que existe en PyPI")


def _scan_text(ctx: _Ctx, archivo: str, text: str, check_injection_lines: bool) -> None:
    """Reglas de texto plano: formatos de clave, caracteres invisibles, inyección."""
    for i, line in enumerate(text.splitlines(), 1):
        for rx, what in _KEY_FORMATS:
            if rx.search(line):
                ctx.add("critica", archivo, i, "secreto-hardcodeado", f"Posible {what} en claro",
                        "regex")
        if _INVISIBLE.search(line.lstrip("﻿") if i == 1 else line):
            ctx.add("alta", archivo, i, "caracteres-invisibles",
                    "Caracteres invisibles o bidireccionales (Trojan Source / prompt oculto)",
                    "regex")
        if check_injection_lines:
            _check_injection(ctx, archivo, i, line, "regex")


def _check_injection(ctx, archivo, linea, text, fuente):
    for rx in _INJECTION:
        if rx.search(text):
            ctx.add("critica", archivo, linea, "prompt-oculto",
                    f"Instrucción dirigida a un LLM: {text.strip()[:120]!r}", fuente)
            return


class _Visitor(ast.NodeVisitor):
    def __init__(self, ctx: _Ctx, archivo: str, local: set[str]):
        self.ctx, self.archivo, self.local = ctx, archivo, local
        self.alias: dict[str, str] = {}

    # ---- utilidades
    def _dotted(self, node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(self.alias.get(node.id, node.id))
        elif isinstance(node, ast.Call):
            parts.append(self._dotted(node.func) + "()")
        else:
            return ""
        return ".".join(reversed(parts))

    def _add(self, node, sev, regla, detalle):
        self.ctx.add(sev, self.archivo, getattr(node, "lineno", 0), regla, detalle)

    @staticmethod
    def _const_str(node) -> str | None:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None

    def _is_dynamic_sql(self, node) -> bool:
        if isinstance(node, ast.JoinedStr):
            lit = "".join(v.value for v in node.values
                          if isinstance(v, ast.Constant) and isinstance(v.value, str))
            return bool(_SQL.search(lit)) and any(isinstance(v, ast.FormattedValue)
                                                  for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            lits = [n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            dyn = any(isinstance(n, (ast.Name, ast.Attribute, ast.Call, ast.Subscript))
                      for n in ast.walk(node))
            return dyn and bool(_SQL.search(" ".join(lits)))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"):
            s = self._const_str(node.func.value)
            return bool(s and _SQL.search(s))
        return False

    # ---- imports
    def _check_import(self, node, mod: str):
        top = mod.split(".")[0]
        if not top or top in self.local or top in _STDLIB:
            return
        res = check_package(top, self.ctx.known)
        if res:
            sev = "critica" if res[0] == "typosquatting" else "media"
            self._add(node, sev, res[0], res[1])

    def visit_Import(self, node):
        for a in node.names:
            self.alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            self._check_import(node, a.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            self._check_import(node, node.module)
            for a in node.names:
                self.alias[a.asname or a.name] = f"{node.module}.{a.name}"
        self.generic_visit(node)

    # ---- secretos en asignaciones
    def _secret_assign(self, node, name: str, value):
        s = self._const_str(value)
        if s and _SECRET_NAME.search(name) and len(s) >= 8 and " " not in s.strip() \
                and not _PLACEHOLDER.search(s):
            self._add(node, "alta", "secreto-hardcodeado",
                      f"'{name}' tiene un valor literal; usa variables de entorno / gestor de secretos")

    def visit_Assign(self, node):
        for t in node.targets:
            name = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else ""
            if name:
                self._secret_assign(node, name, node.value)
            if name == "check_hostname" and isinstance(node.value, ast.Constant) \
                    and node.value.value is False:
                self._add(node, "alta", "tls-desactivado", "check_hostname = False")
            if name == "verify_mode" and self._dotted(node.value).endswith("CERT_NONE"):
                self._add(node, "alta", "tls-desactivado", "verify_mode = CERT_NONE")
        if self._is_dynamic_sql(node.value):
            self._add(node, "media", "sql-concatenado",
                      "SQL construido por interpolación/concatenación; usa parámetros")
        self.generic_visit(node)

    def visit_Dict(self, node):
        for k, v in zip(node.keys, node.values):
            ks = self._const_str(k) if k is not None else None
            if ks:
                self._secret_assign(node, ks, v)
        self.generic_visit(node)

    # ---- llamadas peligrosas
    def visit_Call(self, node):
        name = self._dotted(node.func)
        last = name.split(".")[-1] if name else ""
        args_dynamic = any(not isinstance(a, ast.Constant) for a in node.args)
        kw = {k.arg: k.value for k in node.keywords if k.arg}

        for k, v in kw.items():
            self._secret_assign(node, k, v)
        if name in ("eval", "exec", "builtins.eval", "builtins.exec"):
            self._add(node, "alta" if args_dynamic else "media", "eval-exec",
                      f"Uso de {last}() — ejecución de código arbitrario")
        elif name == "__import__" and args_dynamic:
            self._add(node, "media", "import-dinamico", "__import__ con argumento dinámico")
        if isinstance(kw.get("shell"), ast.Constant) and kw["shell"].value is True:
            self._add(node, "alta", "shell-true", f"{name or 'llamada'}(..., shell=True): inyección de comandos")
        if name in ("os.system", "os.popen", "commands.getoutput", "subprocess.getoutput",
                    "subprocess.getstatusoutput"):
            self._add(node, "alta" if args_dynamic else "media", "shell-true",
                      f"{name}() ejecuta a través de la shell")
        if name in ("pickle.load", "pickle.loads", "cPickle.load", "cPickle.loads",
                    "dill.load", "dill.loads", "marshal.load", "marshal.loads", "shelve.open",
                    "jsonpickle.decode", "pandas.read_pickle", "joblib.load", "torch.load") \
                or (last in ("Unpickler",) and "pickle" in name):
            if not (name == "torch.load" and isinstance(kw.get("weights_only"), ast.Constant)
                    and kw["weights_only"].value is True):
                self._add(node, "alta", "deserializacion-insegura",
                          f"{name}() puede ejecutar código al deserializar datos no confiables")
        if name in ("yaml.load", "yaml.load_all"):
            loader = self._dotted(kw["Loader"]) if "Loader" in kw else \
                (self._dotted(node.args[1]) if len(node.args) > 1 else "")
            if not re.search(r"Safe(Loader)?$|CSafeLoader$", loader or ""):
                self._add(node, "alta", "deserializacion-insegura",
                          f"{name}() sin SafeLoader; usa yaml.safe_load")
        if name in ("yaml.unsafe_load", "yaml.unsafe_load_all"):
            self._add(node, "alta", "deserializacion-insegura", f"{name}()")
        if isinstance(kw.get("verify"), ast.Constant) and kw["verify"].value is False:
            self._add(node, "alta", "tls-desactivado", f"{name or 'llamada'}(verify=False)")
        if name in ("ssl._create_unverified_context", "ssl._create_stdlib_context"):
            self._add(node, "alta", "tls-desactivado", f"{name}() desactiva la verificación TLS")
        if name.endswith("disable_warnings") and "urllib3" in name:
            self._add(node, "baja", "tls-desactivado",
                      "urllib3.disable_warnings() suele acompañar a verify=False")
        if last in _SQL_SINKS and node.args and self._is_dynamic_sql(node.args[0]):
            if len(node.args) > 1 or "parameters" in kw or "params" in kw:
                # patrón habitual: fragmentos dinámicos ("IN (?,?)") + parámetros enlazados
                self._add(node, "media", "sql-concatenado",
                          f"{last}() con SQL dinámico pero con parámetros: verifica que solo se "
                          "interpolan fragmentos controlados (placeholders, nombres fijos)")
            else:
                self._add(node, "alta", "sql-concatenado",
                          f"{last}() con SQL construido dinámicamente: inyección SQL; usa parámetros")
        if last in ("open", "FileResponse", "send_file", "send_from_directory") and node.args \
                and isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
            self._add(node, "baja", "path-traversal",
                      f"{last}() con ruta construida dinámicamente; valida/normaliza contra '..'")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr == "CERT_NONE":
            self._add(node, "alta", "tls-desactivado", "ssl.CERT_NONE desactiva la verificación")
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            if _DOTDOT.search(node.value) and len(node.value) < 300 and "\n" not in node.value:
                self._add(node, "media", "path-traversal",
                          f"Ruta con '..': {node.value[:80]!r}")
            for ln_off, line in enumerate(node.value.splitlines() or [""]):
                _check_injection(self.ctx, self.archivo, node.lineno + ln_off, line, "ast")


def _scan_python(ctx: _Ctx, archivo: str, src: str, local: set[str]) -> None:
    _scan_text(ctx, archivo, src, check_injection_lines=False)
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        ctx.add("media", archivo, e.lineno or 0, "sintaxis-invalida",
                f"No se pudo analizar (SyntaxError: {e.msg}); revisión manual")
        _scan_text(ctx, archivo, src, check_injection_lines=True)
        return
    _Visitor(ctx, archivo, local).visit(tree)
    try:  # comentarios: el AST no los ve
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                _check_injection(ctx, archivo, tok.start[0], tok.string, "comentario")
    except (tokenize.TokenError, IndentationError):
        pass


def _scan_requirements(ctx: _Ctx, archivo: str, text: str) -> None:
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        name = re.split(r"[<>=!~;\[ @]", line, 1)[0].strip()
        if not name:
            continue
        mod = DIST_ALIASES.get(name.lower(), name)
        res = check_package(mod, ctx.known)
        if res:
            ctx.add("critica" if res[0] == "typosquatting" else "media", archivo, i, res[0],
                    res[1], "requirements")


# Wrapper que corre DENTRO del sandbox: `run_command` solo conserva los últimos 6000
# caracteres de salida y el JSON completo de bandit se truncaba. Se emite una versión
# compacta (campos mínimos, máx. 60 hallazgos, ordenados por severidad).
_BANDIT_WRAPPER = r"""
import json, subprocess
p = subprocess.run(["bandit", "-r", ".", "-f", "json", "-q", "-x", "./_ades_bandit.py"],
                   capture_output=True, text=True)
try:
    data = json.loads(p.stdout)
except ValueError:
    print("ADES_BANDIT_ERR " + (p.stdout + p.stderr)[-300:].replace("\n", " "))
    raise SystemExit(0)
order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
rs = [r for r in data.get("results", []) if r.get("test_id") != "B101"]
rs.sort(key=lambda r: order.get(r.get("issue_severity"), 3))
out = [[r.get("filename", ""), r.get("line_number", 0), r.get("issue_severity", "LOW"),
        r.get("test_id", ""), r.get("test_name", ""), r.get("issue_text", "")[:140]]
       for r in rs[:60]]
print("ADES_BANDIT_JSON " + json.dumps({"results": out, "total": len(rs)}))
"""


def _run_bandit(files: dict[str, str]) -> tuple[list[dict], str]:
    """Ejecuta bandit en el sandbox. Devuelve (hallazgos, estado). Nunca lanza."""
    try:
        from core import sandbox
        if not sandbox.image_available():
            return [], "no disponible"
        res = sandbox.run_command({**files, "_ades_bandit.py": _BANDIT_WRAPPER},
                                  ["python", "_ades_bandit.py"], timeout=120)
    except Exception as e:  # noqa: BLE001 — Docker caído / no instalado
        return [], f"no disponible ({type(e).__name__})"
    m = re.search(r"ADES_BANDIT_JSON (\{.*\})", res.output)
    if not m:
        err = re.search(r"ADES_BANDIT_ERR (.*)", res.output)
        return [], "no disponible (" + (err.group(1)[:120] if err else "TIMEOUT" if res.timed_out
                                        else "salida inesperada") + ")"
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return [], "no disponible (JSON inválido)"
    sev = {"HIGH": "alta", "MEDIUM": "media", "LOW": "baja"}
    out = []
    for fname, line, severity, test_id, test_name, text in data.get("results", []):
        fname = str(PurePosixPath(fname).as_posix())
        out.append({"severidad": sev.get(severity, "baja"),
                    "archivo": fname[2:] if fname.startswith("./") else fname,
                    "linea": int(line or 0), "regla": f"bandit-{test_id}",
                    "detalle": f"{test_name}: {text}"[:300], "fuente": "bandit"})
    total = data.get("total", len(out))
    return out, "ok" if total <= len(out) else f"ok ({len(out)} de {total} hallazgos)"

def audit_files(files: dict[str, str], *, use_bandit: bool = True,
                known_packages: set[str] | None = None) -> dict:
    """Audita `{ruta: contenido}`. Nunca lanza por falta de Docker/bandit.

    Devuelve {score (0-100), veredicto ("PASS"/"FAIL"), hallazgos, resumen, bandit}.
    FAIL si hay algún hallazgo de severidad crítica o alta.
    """
    files = dict(files or {})
    known = POPULAR | _STDLIB | set(known_packages or ())
    ctx = _Ctx(known)
    local = set()
    for name in files:
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if parts:
            local.add(parts[0][:-3] if parts[0].endswith(".py") else parts[0])
    for name, content in files.items():
        content = content or ""
        base = PurePosixPath(name).name.lower()
        if name.endswith(".py"):
            _scan_python(ctx, name, content, local)
        elif base.startswith("requirements") and base.endswith(".txt"):
            _scan_requirements(ctx, name, content)
            _scan_text(ctx, name, content, check_injection_lines=True)
        else:
            _scan_text(ctx, name, content, check_injection_lines=True)

    bandit_state = "sin archivos python"
    py = {n: c for n, c in files.items() if n.endswith(".py")}
    if py and use_bandit:
        b_findings, bandit_state = _run_bandit(py)
        taken = {(f["archivo"], f["linea"]) for f in ctx.findings}
        for f in b_findings:  # no duplicar lo que ya detectó una regla propia
            if (f["archivo"], f["linea"]) not in taken:
                ctx.findings.append(f)
    elif py:
        bandit_state = "desactivado"

    # dedupe (misma regla, archivo, línea)
    seen, hallazgos = set(), []
    for f in ctx.findings:
        k = (f["regla"], f["archivo"], f["linea"])
        if k not in seen:
            seen.add(k)
            hallazgos.append(f)
    hallazgos.sort(key=lambda f: (SEVERIDADES.index(f["severidad"]), f["archivo"], f["linea"]))
    resumen = {s: sum(1 for f in hallazgos if f["severidad"] == s) for s in SEVERIDADES}
    score = max(0, 100 - sum(PESOS[f["severidad"]] for f in hallazgos))
    veredicto = "FAIL" if resumen["critica"] or resumen["alta"] else "PASS"
    return {"score": score, "veredicto": veredicto, "hallazgos": hallazgos,
            "resumen": resumen, "bandit": bandit_state, "archivos": len(files)}


def audit_text(text: str, **kw) -> dict:
    """Audita una respuesta de LLM con bloques de código (usa `core.sandbox.extract_files`)."""
    from core.sandbox import extract_files
    return audit_files(extract_files(text), **kw)


def render(report: dict) -> str:
    lines = [f"=== Auditoría anti-IA: {report['veredicto']} | score {report['score']}/100 | "
             f"bandit: {report['bandit']} ==="]
    for f in report["hallazgos"]:
        lines.append(f"  [{f['severidad']:7s}] {f['archivo']}:{f['linea']} {f['regla']} — "
                     f"{f['detalle']} ({f['fuente']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: `ades audit <archivo.py|carpeta> ...` (las carpetas se recorren en *.py)."""
    import pathlib

    fs = {}
    for p in (argv if argv is not None else sys.argv[1:]):
        path = pathlib.Path(p)
        targets = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for t in targets:
            if "__pycache__" not in t.parts:
                fs[t.as_posix()] = t.read_text(encoding="utf-8", errors="replace")
    report = audit_files(fs)
    print(render(report))
    return 0 if report["veredicto"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

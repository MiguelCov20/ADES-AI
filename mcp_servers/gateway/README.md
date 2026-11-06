# Gateway Bifrost — mcp_servers/gateway/

Bifrost (Maxim AI, Apache-2.0) es el gateway de IA que centraliza LLMs, MCP y
agentes en una sola API OpenAI-compatible, con enrutamiento, failover, caché
semántico, virtual keys y control de acceso (auth + scope).

## Instalación

Se añadió el servicio `gateway` a `docker-compose.yml` (imagen `maximhq/bifrost`,
puerto `8080`). Para levantarlo:

```powershell
docker compose up -d gateway
```

Alternativa sin Docker (local):

```powershell
npx -y @maximhq/bifrost
```

## Uso

- Web UI (configuración, monitoreo, analytics): http://localhost:8080
- Endpoint OpenAI-compatible: `http://localhost:8080/v1/chat/completions`
- Drop-in replacement: apuntar `base_url` del SDK OpenAI a `http://localhost:8080/openai`

## Auth + scope (gobernanza)

- **Virtual keys**: claves por agente/proyecto con presupuesto y rate-limit.
- **Scopes**: limitar qué proveedores/modelos y qué herramientas MCP puede usar
  cada clave.
- Configuración por Web UI, API o archivo `config.json`.

## Nota

En ADES-AI el gateway protege los servidores MCP (ver `mcp_servers/mcp_config.json`)
para que los agentes (Developer, QA, Explorador) accedan solo a las herramientas
permitidas, sin exponer las APIs directamente.

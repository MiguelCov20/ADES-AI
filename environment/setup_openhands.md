# Workflow OpenHands — issue de GitHub → PR automático (Fase 9)

OpenHands (All-Hands-AI) es un ingeniero de software autónomo: le das un issue
de GitHub y él clona, planifica, codifica, testea y crea el Pull Request solo.

- 🔗 Repo: https://github.com/All-Hands-AI/OpenHands
- 🔗 Docs: https://docs.all-hands.dev

## Instalación (Docker)

```powershell
docker pull docker.all-hands.dev/all-hands-ai/runtime:0.39-nvidia
docker run -it --rm --pull=always ^
  -e SANDBOX_RUNTIME_CONTAINER_IMAGE=docker.all-hands.dev/all-hands-ai/runtime:0.39-nvidia ^
  -e GITHUB_TOKEN="%GITHUB_TOKEN%" ^
  -v /var/run/docker.sock:/var/run/docker.sock ^
  -p 3000:3000 ^
  --add-host host.docker.internal:host-gateway ^
  docker.all-hands.dev/all-hands-ai/openhands:0.39
```

Abre http://localhost:3000 (Web UI) o usa la CLI (`openhands`).

## Flujo issue → PR

1. El usuario crea un issue en GitHub con el requerimiento.
2. Se lanza OpenHands apuntando al issue (Web UI o CLI):
   `openhands "Resuelve el issue #123 de <owner>/<repo>"`.
3. OpenHands clona el repo, entiende el issue, planifica e implementa en un
   contenedor sandbox efímero.
4. Ejecuta tests y, si pasan, abre el PR con el diff y un resumen.
5. Un revisor humano (o el Reviewer de ADES-AI, Fase 3) aprueba el PR.

## Configuración (mínima)

- `GITHUB_TOKEN`: para operar con GitHub (crear PRs). Con scope `repo`.
- `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`: apuntar a OpenCode Go
  (`https://opencode.ai/inference/go/openai/v1`) o a un modelo local.

## Integración con ADES-AI

- OpenHands cubre el flujo **autónomo** (issue → PR), complementando a la
  fábrica LangGraph (Fase 3), que es la orquestación interna PM→Dev⇄QA→Reviewer.
- Para no duplicar: OpenHands se reserva para issues externos de GitHub;
  la fábrica LangGraph para requerimientos internos del workspace.

# ADE-AI (Autonomous Development Ecosystem with Artificial Intelligence)

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Architecture](https://img.shields.io/badge/architecture-Hybrid%20(Local%20%2B%20Cloud)-success.svg)
![Status](https://img.shields.io/badge/status-Active%20Development-orange.svg)

**ADE-AI** es un ecosistema de desarrollo de software autónomo y multi-agente. Diseñado para maximizar la eficiencia cognitiva y minimizar el consumo de recursos, ADE-AI combina la potencia de razonamiento de modelos en la nube con la ejecución rápida y privada de modelos locales, logrando un ahorro del 70% al 80% en el consumo de tokens.

## 🚀 Características Principales

*   **Arquitectura Híbrida Inteligente:** Delega el diseño arquitectónico a Gemini Plus (Cloud) y la codificación iterativa a Qwen 3 14B (Local - 16GB VRAM).
*   **Memoria Anti-Alucinaciones (GraphRAG):** Utiliza Neo4j para mapear el código como un grafo de conocimiento. Los agentes comprenden las relaciones del proyecto sin necesidad de inyectar todo el código fuente en el contexto.
*   **Eficiencia de Tokens (MCP 2026):** Integración nativa con el Model Context Protocol para paginación inteligente y filtrado del lado del servidor, reduciendo el gasto de tokens en herramientas externas.
*   **Fábrica de Software Multi-Agente:** Orquestación basada en LangGraph con roles definidos (Project Manager, Developer Lead, QA Tester) capaces de corregir sus propios errores en bucles cerrados.
*   **Despliegue "One-Click":** Todo el entorno (bases de datos, orquestador y memoria) se levanta de forma determinista mediante contenedores Docker.

## 🧠 Arquitectura del Sistema

```mermaid
graph TD;
    User[Desarrollador] -->|Requerimientos| PM[Project Manager - Gemini Cloud];
    PM -->|Consulta Grafo| GraphDB[(Neo4j GraphRAG)];
    PM -->|Asigna Ticket| LangGraph{Orquestador LangGraph};
    LangGraph --> Dev[Developer Agent - Qwen Local];
    LangGraph --> QA[QA Agent - Qwen Local];
    Dev -->|Lee/Escribe Código| MCP[Servidores MCP];
    Dev -->|Consulta Memoria Semántica| VectorDB[(Qdrant Vector DB)];
    QA -->|Feedback| Dev;
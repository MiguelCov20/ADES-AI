import os
import sys
import uuid
from typing import TypedDict, Annotated, Sequence
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
import operator

# Forzar la lectura de las variables de entorno
load_dotenv()

# Forzar UTF-8 en la consola de Windows (evita UnicodeEncodeError al imprimir planes con emojis)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 1. Definir el Estado (La memoria compartida del flujo)
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    requerimiento_usuario: str
    plan_de_accion: str
    siguiente_agente: str
    modelo_pm: str # Guardamos qué modelo se usó

# 2. Inicializador del LLM dinámico
def get_pm_llm(opcion_modelo: str):
    if opcion_modelo == "1":
        # GEMINI
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("Falta GOOGLE_API_KEY en .env")
        # Gemini 2026. Modelo configurable vía GEMINI_MODEL (por defecto "gemini-flash-latest").
        # Alternativas: "gemini-4-argon" (razonamiento pesado) o "gemini-flash-lite-latest" (más ligero).
        model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        return ChatGoogleGenerativeAI(model=model, temperature=0.2, google_api_key=api_key)
    
    elif opcion_modelo == "2":
        # OPENCODE GO
        api_key = os.getenv("OPENCODE_API_KEY")
        if not api_key:
            raise ValueError("Falta OPENCODE_API_KEY en .env")
        # OpenCode Go expone un endpoint compatible con OpenAI (chat/completions).
        # Requiere el header `x-opencode-session` para enrutar y cachear correctamente.
        return ChatOpenAI(
            model="deepseek-v4.1-flash",
            temperature=0.2,
            api_key=api_key,
            base_url="https://opencode.ai/inference/go/openai/v1",
            default_headers={
                "x-opencode-session": f"ade-ai-pm-{uuid.uuid4().hex}",
                "User-Agent": "ade-ai/1.0",
            },
        )
    else:
        raise ValueError("Opción no válida.")

# 3. Definir el Nodo del Project Manager
def project_manager_node(state: AgentState):
    nombre_modelo = "Gemini" if state["modelo_pm"] == "1" else "OpenCode Go"
    print(f"\n--- PROJECT MANAGER ({nombre_modelo}) PENSANDO ---")
    
    requerimiento = state.get("requerimiento_usuario", "")
    
    system_prompt = SystemMessage(
        content="""Eres el Project Manager de ADES-AI, una Software Factory autónoma.
        Tu trabajo NO es escribir código, sino planificar arquitecturas de software eficientes.
        Recibirás un requerimiento del usuario. Debes:
        1. Analizar el requerimiento.
        2. Dividirlo en pasos técnicos claros (Tickets).
        3. Responder con el plan detallado para que un Agente Developer local pueda programarlo.
        Mantén tus respuestas estructuradas y enfocadas en la arquitectura."""
    )
    
    human_msg = HumanMessage(content=f"Requerimiento del usuario: {requerimiento}")
    
    # Inicializar el LLM correcto según el estado
    llm = get_pm_llm(state["modelo_pm"])
    
    # Ejecutar la inferencia
    response = llm.invoke([system_prompt, human_msg])
    
    # El estado retiene esta memoria sin gastar tokens extra en la terminal local
    return {
        "messages": [response], 
        "plan_de_accion": response.content,
        "siguiente_agente": "developer_local"
    }

# 4. Construir el Grafo de LangGraph
def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("project_manager", project_manager_node)
    workflow.set_entry_point("project_manager")
    workflow.add_edge("project_manager", END)
    return workflow.compile()

# 5. Interfaz interactiva de arranque
if __name__ == "__main__":
    app = build_graph()
    
    print("\n==================================================")
    print("      ADES-AI: SOFTWARE FACTORY INICIALIZADA       ")
    print("==================================================")
    print("Selecciona el cerebro para el Project Manager (Nube):")
    print("1) Gemini (Recomendado para integraciones Google)")
    print("2) OpenCode Go (Recomendado para arquitecturas puras de código)")
    
    opcion = input("\nElige una opción (1 o 2): ").strip()
    
    user_input = input("\nIngresa un nuevo requerimiento de software: ")
    
    initial_state = {
        "messages": [],
        "requerimiento_usuario": user_input,
        "plan_de_accion": "",
        "siguiente_agente": "",
        "modelo_pm": opcion
    }
    
    try:
        result = app.invoke(initial_state)
        print("\n================ PLAN GENERADO =================\n")
        print(result["plan_de_accion"])
        print("\n================================================\n")
        print(f"Siguiente paso asignado a: {result['siguiente_agente']} (Aquí entrará tu Qwen 3 local)")
    except Exception as e:
        print(f"\n[ERROR]: {str(e)}")
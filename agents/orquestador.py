import os
from typing import TypedDict, Annotated, List, Sequence
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
import operator

# Cargar variables de entorno (API Keys)
load_dotenv()

# 1. Definir el Estado (La memoria compartida del flujo)
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    requerimiento_usuario: str
    plan_de_accion: str
    siguiente_agente: str

# 2. Configurar el LLM en la Nube (Project Manager)
# Utilizamos Gemini Pro/Plus para alto razonamiento y ventana de contexto larga
llm_gemini = ChatGoogleGenerativeAI(model="gemini-3.8-flash", temperature=0.2)

# 3. Definir el Nodo del Project Manager
def project_manager_node(state: AgentState):
    print("--- PROJECT MANAGER (Gemini) PENSANDO ---")
    requerimiento = state.get("requerimiento_usuario", "")
    
    system_prompt = SystemMessage(
        content="""Eres el Project Manager de ADE-AI, una Software Factory autónoma.
        Tu trabajo NO es escribir código, sino planificar.
        Recibirás un requerimiento del usuario. Debes:
        1. Analizar el requerimiento.
        2. Dividirlo en pasos técnicos claros y pequeños (Tickets).
        3. Responder con el plan de acción detallado para que el Developer (LLM local) pueda programarlo paso a paso.
        Mantén tus respuestas estrictamente enfocadas en la arquitectura y el diseño técnico."""
    )
    
    # Combinar el prompt del sistema con el requerimiento del usuario
    human_msg = HumanMessage(content=f"Requerimiento del usuario: {requerimiento}")
    
    # Llamar a Gemini
    response = llm_gemini.invoke([system_prompt, human_msg])
    
    # Actualizar el estado con el plan generado
    return {
        "messages": [response], 
        "plan_de_accion": response.content,
        "siguiente_agente": "developer_local" # En el futuro, esto enviará el flujo a tu GPU de 16GB
    }

# 4. Construir el Grafo de LangGraph
def build_graph():
    # Inicializar el grafo con nuestro esquema de estado
    workflow = StateGraph(AgentState)
    
    # Añadir nodos
    workflow.add_node("project_manager", project_manager_node)
    
    # Definir el flujo (Edges)
    workflow.set_entry_point("project_manager")
    workflow.add_edge("project_manager", END) # Temporalmente termina aquí hasta que agreguemos a Qwen
    
    # Compilar el grafo
    return workflow.compile()

# 5. Punto de entrada para probar el agente
if __name__ == "__main__":
    app = build_graph()
    
    print("\n[ADE-AI] Sistema Inicializado.")
    user_input = input("Ingresa un nuevo requerimiento de software: ")
    
    # Iniciar el estado
    initial_state = {
        "messages": [],
        "requerimiento_usuario": user_input,
        "plan_de_accion": "",
        "siguiente_agente": ""
    }
    
    # Ejecutar el grafo
    result = app.invoke(initial_state)
    
    print("\n================ PLAN GENERADO POR EL PM ================\n")
    print(result["plan_de_accion"])
    print("\n=========================================================\n")
    print(f"Siguiente paso asignado a: {result['siguiente_agente']}")
"""Fine-tuning de un SLM con Unsloth (ADES-AI, Fase 9).

Personaliza un modelo pequeño (Qwen 3B/8B) con los patrones del usuario
(estilo de código, preferencias, decisiones) usando Unsloth + LoRA, para que
el cerebro local se ajuste a ADES-AI.

REQUISITO: GPU NVIDIA (CUDA). Unsloth NO soporta Windows/AMD de forma estable,
por lo que este script se ejecuta en un host Linux+CUDA o en la nube
(Google Colab / RunPod / Lambda Labs).

No se ejecuta en la máquina de desarrollo (Windows + AMD RX 9070 XT); es un
artefacto documentado para el entorno de entrenamiento.

Uso (en host CUDA):
    python environment/finetune_unsloth.py
"""
# --- Configuración ---------------------------------------------------------
BASE_MODEL = "unsloth/Qwen3-8B-bnb-4bit"          # o Qwen3-3B
OUTPUT_DIR = "./ades-qwen3-8b-lora"
MAX_SEQ_LENGTH = 2048


def build_dataset():
    """Construye el dataset con los patrones del usuario.

    Formato Alpaca: [{"instruction": ..., "input": ..., "output": ...}].
    Fuente: decisiones de arquitectura, preferencias (Mem0), tickets resueltos,
    estilo de código de ADES-AI.
    """
    # TODO(usuario): reemplazar por tus datos reales.
    return [
        {"instruction": "Escribe un endpoint REST", "input": "",
         "output": "Usa FastAPI con pydantic y tipado completo, siguiendo el estilo de ADES-AI."},
    ]


def main() -> None:
    try:
        from unsloth import FastLanguageModel
        import torch
    except ImportError:
        print("Unsloth no esta instalado. Ejecuta: pip install unsloth")
        print("(requiere GPU NVIDIA/CUDA; ver docstring)")
        return

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH,
        dtype=None,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        use_gradient_checkpointing="unsloth",
    )

    from trl import SFTTrainer
    from transformers import TrainingArguments
    from unsloth import is_bfloat16_supported

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=build_dataset(),
        dataset_text_field="instruction",
        max_seq_length=MAX_SEQ_LENGTH,
        args=TrainingArguments(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_steps=5,
            max_steps=60,
            learning_rate=2e-4,
            fp16=not is_bfloat16_supported(),
            bf16=is_bfloat16_supported(),
            logging_steps=1,
            output_dir=OUTPUT_DIR,
        ),
    )
    trainer.train()
    model.save_pretrained(OUTPUT_DIR)
    print(f"Modelo fine-tuneado guardado en {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

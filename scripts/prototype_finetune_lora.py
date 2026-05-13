from __future__ import annotations

import argparse
import json
from pathlib import Path


def format_training_example(record: dict) -> dict:
    expected = {
        "action": record.get("expected_action", ""),
        "module": record.get("expected_module", ""),
        "response": record.get("expected_response", ""),
    }
    prompt = (
        "Route and answer this Personal OS instruction.\n\n"
        "Instruction: " + record.get("instruction", "") + "\n\n"
        "Return the desired action/module behavior and response."
    )
    return {"text": prompt + "\n\n" + json.dumps(expected, ensure_ascii=False)}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError("Training data not found: " + str(path))
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def require_training_deps():
    try:
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForCausalLM, AutoTokenizer, DataCollatorForLanguageModeling, Trainer, TrainingArguments
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "LoRA runtime dependencies are not installed. Run `make install-finetune` "
            "in a Python 3.11/3.12 environment, ideally with GPU support."
        ) from e
    return Dataset, LoraConfig, get_peft_model, AutoModelForCausalLM, AutoTokenizer, DataCollatorForLanguageModeling, Trainer, TrainingArguments


def train_lora(data_path: Path, output_dir: Path, model_name: str, max_steps: int, batch_size: int):
    (
        Dataset,
        LoraConfig,
        get_peft_model,
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    ) = require_training_deps()

    rows = [format_training_example(row) for row in load_jsonl(data_path)]
    if not rows:
        raise ValueError("No training rows found in " + str(data_path))

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    dataset = Dataset.from_list(rows)

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=1024)

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])
    model = AutoModelForCausalLM.from_pretrained(model_name)
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=1,
        max_steps=max_steps,
        learning_rate=2e-4,
        logging_steps=5,
        save_steps=max(10, max_steps),
        report_to=[],
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )
    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    return {"output_dir": str(output_dir), "records": len(rows), "model": model_name}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/training/labels.jsonl")
    parser.add_argument("--output", default="data/training/lora-adapter")
    parser.add_argument("--model", default="sshleifer/tiny-gpt2")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data_path = Path(args.data)
    output_dir = Path(args.output)
    if args.dry_run:
        rows = [format_training_example(row) for row in load_jsonl(data_path)]
        output_dir.mkdir(parents=True, exist_ok=True)
        preview = output_dir / "training_preview.jsonl"
        preview.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
        print(json.dumps({"dry_run": True, "preview": str(preview), "records": len(rows)}, indent=2))
        return

    print(json.dumps(train_lora(data_path, output_dir, args.model, args.max_steps, args.batch_size), indent=2))


if __name__ == "__main__":
    main()

from scripts.prototype_finetune_lora import format_training_example


def test_format_training_example():
    row = {
        "instruction": "Show my jobs",
        "expected_action": "read_data",
        "expected_module": "jobs",
        "expected_response": "Found jobs",
    }

    example = format_training_example(row)

    assert "Show my jobs" in example["text"]
    assert '"action": "read_data"' in example["text"]

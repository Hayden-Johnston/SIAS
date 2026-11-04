import json
from pathlib import Path

from dotenv import load_dotenv

from data_processing.dataset import DataHandler
from llm_security.pipeline import Pipeline


def main():
    load_dotenv()
    config_path = Path("config.local.json")
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
        f.close()
    with config_path.open("w", encoding="utf-8") as f:
        config["run_count"] += 1
        json.dump(config, f, indent=4)
        f.close()
    dh = DataHandler(config)
    pipeline = Pipeline(config, dh)
    pipeline.run()

if __name__ == "__main__":
    main()
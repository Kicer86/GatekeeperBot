
import json
import logging
import os
import threading

from typing import Any, Dict


class Configuration:
    config_file = "config.json"

    def __init__(self, dir: str, logger: logging.Logger):
        self.config = None
        self.logger = logger
        self.timer = None
        self.path = os.path.join(dir, Configuration.config_file)

    def get_config(self) -> Dict[str, Any]:
        if self.config is None:
            self.config = self._load_config()

        return self.config

    def set_config(self, config: Dict[str, Any]):
        self.config = config

        if self.timer is not None:
            self.timer.cancel()

        self.timer = threading.Timer(5, self._save_config)
        self.timer.start()

    def set_default(self, entry: str, default_value: Any):
        config = self.get_config()
        value = config.get(entry, default_value)
        config[entry] = value
        self.set_config(config)

    def _load_config(self) -> Dict[str, Any]:
        self.logger.info("loading config")
        if not os.path.isfile(self.path):
            self.logger.debug("config file not found, creating new one")
            self.config = {}
            self._save_config()

        with open(self.path, 'r', encoding='utf-8') as config:
            return json.load(config)

    def _save_config(self):
        self.logger.info("saving config")
        with open(self.path, 'w+', encoding='utf-8') as config:
            json.dump(self.config, config, indent = 4, ensure_ascii = False)

from app.models.base import StreamingModel
from app.models.mock import MockModel
from app.models.deepseek import DeepSeekAdapter
from app.models.qwen import QwenAdapter
from app.config import settings

class ModelRegistry:
    @staticmethod
    def get(name: str, script: str = "chat") -> StreamingModel:
        if name.startswith("deepseek"):
            return DeepSeekAdapter()
        elif name.startswith("qwen"):
            return QwenAdapter()
        else:
            return MockModel(name=name, script=script)

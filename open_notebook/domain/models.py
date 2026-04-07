from typing import ClassVar, Dict, Optional, Union

from esperanto import (
    AIFactory,
    EmbeddingModel,
    LanguageModel,
    SpeechToTextModel,
    TextToSpeechModel,
)
from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel, RecordModel
from open_notebook.utils.openrouter_api import create_openrouter_embedding_model

ModelType = Union[LanguageModel, EmbeddingModel, SpeechToTextModel, TextToSpeechModel]


class Model(ObjectModel):
    table_name: ClassVar[str] = "model"
    name: str
    provider: str
    type: str

    @classmethod
    async def get_models_by_type(cls, model_type):
        models = await repo_query(
            "SELECT * FROM model WHERE type=$model_type;", {"model_type": model_type}
        )
        return [Model(**model) for model in models]


class DefaultModels(RecordModel):
    record_id: ClassVar[str] = "open_notebook:default_models"
    default_chat_model: Optional[str] = None
    default_transformation_model: Optional[str] = None
    large_context_model: Optional[str] = None
    default_text_to_speech_model: Optional[str] = None
    default_speech_to_text_model: Optional[str] = None
    # default_vision_model: Optional[str]
    default_embedding_model: Optional[str] = None
    default_tools_model: Optional[str] = None
    default_image_model: Optional[str] = None

    @classmethod
    async def get_instance(cls) -> "DefaultModels":
        """Always fetch fresh defaults from database (override parent caching behavior)"""
        result = await repo_query(
            "SELECT * FROM ONLY $record_id",
            {"record_id": ensure_record_id(cls.record_id)},
        )

        if result:
            if isinstance(result, list) and len(result) > 0:
                data = result[0]
            elif isinstance(result, dict):
                data = result
            else:
                data = {}
        else:
            data = {}

        # Create new instance with fresh data (bypass singleton cache)
        instance = object.__new__(cls)
        object.__setattr__(instance, "__dict__", {})
        super(RecordModel, instance).__init__(**data)
        return instance


class ModelManager:
    def __init__(self):
        pass  # No caching needed

    async def get_model(self, model_id: str, **kwargs) -> Optional[ModelType]:
        """Get a model by ID or name. Esperanto will cache the actual model instance.

        Supports both SurrealDB record IDs (e.g. 'model:abc123') and
        plain model names (e.g. 'gpt-5-mini'). When a plain name is given,
        a lookup by name is performed instead of Model.get().
        """
        if not model_id:
            return None

        model: Optional[Model] = None

        if ":" in model_id:
            # Looks like a SurrealDB record ID (e.g. 'model:abc123')
            try:
                model = await Model.get(model_id)
            except Exception as e:
                logger.error(f"Failed to load model '{model_id}': {e}")
                raise ValueError(f"Model with ID {model_id} not found") from e
        else:
            # Plain model name (e.g. 'gpt-5-mini') — look up by name
            results = await repo_query(
                "SELECT * FROM model WHERE name = $name LIMIT 1",
                {"name": model_id},
            )
            if results:
                model = Model(**results[0])
            else:
                raise ValueError(
                    f"Model '{model_id}' not found by ID or name"
                )

        if model is None:
            raise ValueError(f"Model '{model_id}' could not be resolved")

        if not model.type or model.type not in [
            "language",
            "embedding",
            "speech_to_text",
            "text_to_speech",
        ]:
            raise ValueError(f"Invalid model type: {model.type}")

        # Create model based on type (Esperanto will cache the instance)
        if model.type == "language":
            return AIFactory.create_language(
                model_name=model.name,
                provider=model.provider,
                config=kwargs,
            )
        elif model.type == "embedding":
            if model.provider and model.provider.lower() == "openrouter":
                return create_openrouter_embedding_model(model.name)
            return AIFactory.create_embedding(
                model_name=model.name,
                provider=model.provider,
                config=kwargs,
            )
        elif model.type == "speech_to_text":
            return AIFactory.create_speech_to_text(
                model_name=model.name,
                provider=model.provider,
                config=kwargs,
            )
        elif model.type == "text_to_speech":
            if model.provider and model.provider.lower() == "openrouter":
                import os
                return AIFactory.create_text_to_speech(
                    model_name=model.name,
                    provider="openai-compatible",
                    config={
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
                        **kwargs,
                    },
                )
            return AIFactory.create_text_to_speech(
                model_name=model.name,
                provider=model.provider,
                config=kwargs,
            )
        else:
            raise ValueError(f"Invalid model type: {model.type}")

    async def get_defaults(self) -> DefaultModels:
        """Get the default models configuration from database"""
        defaults = await DefaultModels.get_instance()
        if not defaults:
            raise RuntimeError("Failed to load default models configuration")
        return defaults

    async def get_speech_to_text(self, **kwargs) -> Optional[SpeechToTextModel]:
        """Get the default speech-to-text model"""
        defaults = await self.get_defaults()
        model_id = defaults.default_speech_to_text_model
        if not model_id:
            return None
        model = await self.get_model(model_id, **kwargs)
        assert model is None or isinstance(model, SpeechToTextModel), (
            f"Expected SpeechToTextModel but got {type(model)}"
        )
        return model

    async def get_text_to_speech(self, **kwargs) -> Optional[TextToSpeechModel]:
        """Get the default text-to-speech model"""
        defaults = await self.get_defaults()
        model_id = defaults.default_text_to_speech_model
        if not model_id:
            return None
        model = await self.get_model(model_id, **kwargs)
        assert model is None or isinstance(model, TextToSpeechModel), (
            f"Expected TextToSpeechModel but got {type(model)}"
        )
        return model

    async def get_embedding_model(self, **kwargs) -> Optional[EmbeddingModel]:
        """Get the default embedding model"""
        defaults = await self.get_defaults()
        model_id = defaults.default_embedding_model
        if not model_id:
            return None
        model = await self.get_model(model_id, **kwargs)
        # We only require the app-level contract: an embedding model with `aembed()`.
        # Some provider adapters may not subclass `esperanto.EmbeddingModel` directly,
        # especially when bridging via custom HTTP wrappers.
        assert model is None or callable(getattr(model, "aembed", None)), (
            f"Expected embedding model with callable aembed() but got {type(model)}"
        )
        return model

    async def get_default_model(self, model_type: str, **kwargs) -> Optional[ModelType]:
        """
        Get the default model for a specific type.

        Args:
            model_type: The type of model to retrieve (e.g., 'chat', 'embedding', etc.)
            **kwargs: Additional arguments to pass to the model constructor
        """
        defaults = await self.get_defaults()
        model_id = None

        if model_type == "chat":
            model_id = defaults.default_chat_model
        elif model_type == "transformation":
            model_id = (
                defaults.default_transformation_model
                or defaults.default_chat_model
            )
        elif model_type == "tools":
            model_id = (
                defaults.default_tools_model or defaults.default_chat_model
            )
        elif model_type == "embedding":
            model_id = defaults.default_embedding_model
        elif model_type == "text_to_speech":
            model_id = defaults.default_text_to_speech_model
        elif model_type == "speech_to_text":
            model_id = defaults.default_speech_to_text_model
        elif model_type == "large_context":
            model_id = defaults.large_context_model

        if not model_id:
            return None

        return await self.get_model(model_id, **kwargs)


model_manager = ModelManager()

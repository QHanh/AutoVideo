import warnings
from enum import Enum
from typing import Any, List, Optional, Union

import pydantic
from pydantic import BaseModel

warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="Field name.*shadows an attribute in parent.*",
)


class VideoConcatMode(str, Enum):
    random = "random"
    sequential = "sequential"


class VideoTransitionMode(str, Enum):
    none = None
    shuffle = "Shuffle"
    fade_in = "FadeIn"
    fade_out = "FadeOut"
    slide_in = "SlideIn"
    slide_out = "SlideOut"


class VideoAspect(str, Enum):
    landscape = "16:9"
    portrait = "9:16"
    square = "1:1"

    def to_resolution(self):
        if self == VideoAspect.landscape.value:
            return 1920, 1080
        elif self == VideoAspect.portrait.value:
            return 1080, 1920
        elif self == VideoAspect.square.value:
            return 1080, 1080
        return 1080, 1920


class _Config:
    arbitrary_types_allowed = True


@pydantic.dataclasses.dataclass(config=_Config)
class MaterialInfo:
    provider: str = "pexels"
    url: str = ""
    duration: int = 0


class VideoParams(BaseModel):
    video_subject: str
    video_script: str = "" 
    video_terms: Optional[str | list] = None  # Keywords used to generate the video
    video_aspect: Optional[VideoAspect] = VideoAspect.portrait.value
    video_concat_mode: Optional[VideoConcatMode] = VideoConcatMode.random.value
    video_transition_mode: Optional[VideoTransitionMode] = None
    video_clip_duration: Optional[int] = 5
    video_count: Optional[int] = 1

    video_source: Optional[str] = "pexels"
    video_materials: Optional[List[MaterialInfo]] = (
        None  # Materials used to generate the video
    )

    video_language: Optional[str] = ""  # auto detect
    tts_server: Optional[str] = "azure-tts-v1"
    voice_name: Optional[str] = "vi-VN-NamMinhNeural-Male"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.0
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2

    subtitle_enabled: Optional[bool] = True
    subtitle_position: Optional[str] = "bottom"  # top, bottom, center
    custom_position: float = 70.0
    font_name: Optional[str] = "Charm-Bold.ttf"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = True
    type_subtitle: Optional[str] = "normal"
    font_size: int = 60
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 1.5
    n_threads: Optional[int] = 4
    subtitle_provider: Optional[str] = "edge"
    paragraph_number: Optional[int] = 1
    gemini_key: Optional[str] = ""
    openai_key: Optional[str] = ""
    speech_key: Optional[str] = ""
    speech_region: Optional[str] = ""

class VideoPodcastParams(BaseModel):
    video_subject: str = ""
    video_content: str = ""
    video_script: str = ""
    video_dialogue_tts: str = ""
    video_dialogue_subtitle: str = ""
    video_terms: Optional[str | list] = None
    video_aspect: Optional[VideoAspect] = VideoAspect.portrait.value
    video_concat_mode: Optional[VideoConcatMode] = VideoConcatMode.random.value
    video_transition_mode: Optional[VideoTransitionMode] = None
    video_clip_duration: Optional[int] = 5
    video_count: Optional[int] = 1

    video_source: Optional[str] = "pexels"
    video_materials: Optional[List[MaterialInfo]] = (
        None  # Materials used to generate the video
    )

    video_language: Optional[str] = "Vietnamese"
    host1: Optional[str] = "Mai"
    host2: Optional[str] = "Hoàng"
    voice1: Optional[str] = "Zephyr"
    voice2: Optional[str] = "Puck"
    tone: Optional[str] = "happy"
    
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.0

    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2

    subtitle_enabled: Optional[bool] = True
    subtitle_position: Optional[str] = "bottom"  # top, bottom, center
    custom_position: float = 70.0
    font_name: Optional[str] = "Charm-Bold.ttf"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = True
    type_subtitle: Optional[str] = "normal"
    font_size: int = 60
    subtitle_provider: Optional[str] = "edge"
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 1.5
    n_threads: Optional[int] = 4
    paragraph_number: Optional[int] = 1
    gemini_key: Optional[str] = ""
    openai_key: Optional[str] = ""

class SubtitleRequest(BaseModel):
    video_script: str
    video_language: Optional[str] = "Vietnamese"
    voice_name: Optional[str] = "vi-VN-NamMinhNeural-Female"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.2
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    subtitle_position: Optional[str] = "bottom"
    font_name: Optional[str] = "STHeitiMedium.ttc"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = True
    font_size: int = 60
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 1.5
    video_source: Optional[str] = "local"
    subtitle_enabled: Optional[str] = "true"


class AudioRequest(BaseModel):
    video_script: str
    video_language: Optional[str] = "Vietnamese"
    voice_name: Optional[str] = "vi-VN-NamMinhNeural-Female"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.2
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    video_source: Optional[str] = "local"


class VideoScriptParams:
    """
    {
      "video_subject": "",
      "video_language": "",
      "paragraph_number": 1
    }
    """

    video_subject: Optional[str] = ""
    video_language: Optional[str] = "Vietnamese"
    paragraph_number: Optional[int] = 1
    gemini_key: Optional[str] = ""
    openai_key: Optional[str] = ""

class VideoScriptPodcastParams:
    """
    {
      "video_subject": "",
      "video_content": "",
      "video_language": "",
    }
    """
    video_subject: Optional[str] = ""
    video_content: Optional[str] = ""
    video_language: Optional[str] = "Vietnamese"
    gemini_key: Optional[str] = ""
    openai_key: Optional[str] = ""

class VideoDialogueParams:
    """
    {
      "video_content": "",
      "video_language": "",
      "video_script": "",
      "host1": "",
      "host2": "",
      "tone": "",
    }
    """
    video_content: Optional[str] = ""
    video_script: Optional[str] = ("")
    video_language: Optional[str] = "Vietnamese"
    host1: Optional[str] = "Thu"
    host2: Optional[str] = "Hanh"
    tone: Optional[str] = ""
    gemini_key: Optional[str] = ""

class VideoTermsParams:
    """
    {
      "video_subject": "",
      "video_script": "",
      "amount": 5
    }
    """

    video_subject: Optional[str] = ""
    video_script: Optional[str] = (
        ""
    )
    amount: Optional[int] = 5
    gemini_key: Optional[str] = ""
    openai_key: Optional[str] = ""


class BaseResponse(BaseModel):
    status: int = 200
    message: Optional[str] = "success"
    data: Any = None


class TaskVideoRequest(VideoParams, BaseModel):
    pass

class TaskPodcastVideoRequest(VideoPodcastParams, BaseModel):
    pass

class TaskQueryRequest(BaseModel):
    pass


class VideoScriptRequest(VideoScriptParams, BaseModel):
    pass


class VideoTermsRequest(VideoTermsParams, BaseModel):
    pass


class VideoScriptPodcastRequest(VideoScriptPodcastParams, BaseModel):
    pass


class VideoDialogueRequest(VideoDialogueParams, BaseModel):
    pass


class TaskResponse(BaseResponse):
    class TaskResponseData(BaseModel):
        task_id: str

    data: TaskResponseData

    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558"},
            },
        }


class TaskQueryResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "state": 1,
                    "progress": 100,
                    "videos": [
                        "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/final-1.mp4"
                    ],
                    "combined_videos": [
                        "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/combined-1.mp4"
                    ],
                },
            },
        }


class TaskDeletionResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "state": 1,
                    "progress": 100,
                    "videos": [
                        "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/final-1.mp4"
                    ],
                    "combined_videos": [
                        "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/combined-1.mp4"
                    ],
                },
            },
        }


class VideoScriptResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "video_script": ""
                },
            },
        }


class VideoTermsResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"video_terms": ["sky", "tree"]},
            },
        }


class VideoScriptPodcastResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"video_script_podcast": ""},
            }
        }


class VideoDialogueResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"video_dialogue_tts": "",
                         "video_dialogue_subtitle": ""},
            }
        }


class BgmRetrieveResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "files": [
                        {
                            "name": "output013.mp3",
                            "size": 1891269,
                            "file": "/AutoVideo/resource/songs/output013.mp3",
                        }
                    ]
                },
            },
        }


class BgmUploadResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"file": "/AutoVideo/resource/songs/example.mp3"},
            },
        }


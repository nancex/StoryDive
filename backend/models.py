from typing import Optional, List
from pydantic import BaseModel

class BookBrief(BaseModel):
    id: str
    title: str
    original_author: str
    script_author: str
    genre: list
    protagonist: str
    save_count: int

class BookDetail(BaseModel):
    id: str
    title: str
    original_author: str
    script_author: str
    upload_date: str
    description: str
    cover_image: str
    protagonist: str
    genre: list
    version: str

class SaveBrief(BaseModel):
    id: str
    book_id: str
    book_title: str
    last_modified: str
    preview: list

class SaveDetail(BaseModel):
    id: str
    book_id: str
    book_title: str
    book_author: str
    last_modified: str
    story_preview: list
    memo: str
    reference_sections: list = []

class ActionRequest(BaseModel):
    save_id: str
    action: str
    speak: bool = False
    regret: bool = False
    accelerate: bool = False
    target_paragraph_index: Optional[int] = None

class SettingsData(BaseModel):
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    image_base_url: str = ""
    image_api_key: str = ""
    image_model: str = ""
    tts_endpoint: str = ""
    llm_timeout: int = 60
    llm_debug: bool = False
    llm_extra_body: str = ""

class MemoUpdateRequest(BaseModel):
    memo: str

class ReferenceUpdateRequest(BaseModel):
    sections: List[str]



class ProfileSwitchRequest(BaseModel):
    name: str

class ProfileCreateRequest(BaseModel):
    name: str

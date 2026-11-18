from datetime import date
from pydantic import BaseModel,Field,field_validator
class RescheduleItemInput(BaseModel):
    performance_id:int
    new_date:date
class RescheduleInput(BaseModel):
    note:str=Field(min_length=4,max_length=200)
    items:list[RescheduleItemInput]=Field(min_length=1,max_length=20)
    @field_validator('note')
    @classmethod
    def nonblank(cls,v):
        if not v.strip():raise ValueError('改期事由不能为空')
        return v.strip()
    @field_validator('items')
    @classmethod
    def distinct(cls,v):
        ids=[x.performance_id for x in v]
        if len(set(ids))!=len(ids):raise ValueError('改期单内场次重复')
        return v

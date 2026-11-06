from pydantic import BaseModel,field_validator

class Reasoned(BaseModel):
    @field_validator('reason',check_fields=False)
    @classmethod
    def meaningful_reason(cls,value):
        value=value.strip()
        minimum=10 if cls.__name__=='AppealRequest' else 3
        if len(value)<minimum:raise ValueError('Укажите содержательную причину')
        return value

from fastapi import APIRouter,Depends
from sqlalchemy import select
from .db import db_session
from .auth import current,admin
from .reschedule_models import RescheduleOrder
from .reschedule_schemas import RescheduleInput
from . import reschedule_service as svc
router=APIRouter()
@router.get('/reschedule-orders')
def orders(s=Depends(db_session),u=Depends(current)):return [svc.view(s,x) for x in s.scalars(select(RescheduleOrder).order_by(RescheduleOrder.id.desc()))]
@router.post('/reschedule-orders')
def create(d:RescheduleInput,s=Depends(db_session),u=Depends(admin)):
    x=svc.create(s,d,u);s.commit();return x
@router.post('/reschedule-orders/{oid}/confirm')
def confirm(oid:int,s=Depends(db_session),u=Depends(admin)):
    x=svc.confirm(s,oid,u);s.commit();return x

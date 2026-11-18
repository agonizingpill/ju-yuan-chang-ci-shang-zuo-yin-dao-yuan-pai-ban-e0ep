from sqlalchemy import String,ForeignKey,Date,JSON,CheckConstraint,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from datetime import date as DateValue
from .db import Base
class RescheduleOrder(Base):
    __tablename__='reschedule_orders'
    __table_args__=(CheckConstraint("state in ('draft','applied')"),)
    id:Mapped[int]=mapped_column(primary_key=True)
    note:Mapped[str]=mapped_column(String(200))
    state:Mapped[str]=mapped_column(String(20),default='draft')
    conflicts:Mapped[list|None]=mapped_column(JSON,nullable=True)
    created_by:Mapped[str]=mapped_column(String(100))
    created_at:Mapped[str]=mapped_column(String(40))
    applied_by:Mapped[str|None]=mapped_column(String(100),nullable=True)
    applied_at:Mapped[str|None]=mapped_column(String(40),nullable=True)
class RescheduleItem(Base):
    __tablename__='reschedule_items'
    __table_args__=(UniqueConstraint('order_id','performance_id'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    order_id:Mapped[int]=mapped_column(ForeignKey('reschedule_orders.id'))
    performance_id:Mapped[int]=mapped_column(ForeignKey('performances.id'))
    old_date:Mapped[DateValue]=mapped_column(Date)
    new_date:Mapped[DateValue]=mapped_column(Date)

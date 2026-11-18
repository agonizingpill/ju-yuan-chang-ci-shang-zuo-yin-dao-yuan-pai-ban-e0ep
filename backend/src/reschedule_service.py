from datetime import datetime,timedelta,timezone,date
from collections import Counter
from sqlalchemy import select
from fastapi import HTTPException
from .models import Production,Performance,CrewCall
from .staff_models import StaffMember,CrewAssignment
from .debrief_models import ShowDebrief
from .reschedule_models import RescheduleOrder,RescheduleItem
from .staff_service import locked
from .services import pack,audit

def window(perf,call,prod,day):
    # 值班占用：点名时刻至开场＋演出时长＋30分钟；day 为平移后的场次日期
    delta=day-perf.date
    start=datetime.fromisoformat(call.call_time)+delta
    end=datetime.fromisoformat(day.isoformat()+'T'+perf.curtain)+timedelta(minutes=prod.duration_minutes+30)
    return start,end

def load_moves(s,items):
    moves=[]
    for it in items:
        perf=s.get(Performance,it.performance_id)
        if not perf:raise HTTPException(404,f'场次 #{it.performance_id} 不存在')
        call=s.scalar(select(CrewCall).where(CrewCall.performance_id==perf.id))
        moves.append({'perf':perf,'call':call,'prod':s.get(Production,perf.production_id),'new_date':it.new_date})
    return moves

def eligibility(s,moves):
    # 已有验票、实名到岗或散场交接的场次拒绝改期；仅已确认点名的场次可改期
    bad=[]
    for m in moves:
        p,c=m['perf'],m['call']
        if p.status!='crew_confirmed' or not c or c.status!='confirmed':bad.append(f'场次#{p.id} 点名未确认，不能改期');continue
        if p.arrivals is not None:bad.append(f'场次#{p.id} 已有验票记录，拒绝改期')
        if s.scalar(select(CrewAssignment.id).where(CrewAssignment.crew_call_id==c.id,CrewAssignment.checked_in==True)):bad.append(f'场次#{p.id} 已有实名到岗，拒绝改期')
        if s.scalar(select(ShowDebrief.id).where(ShowDebrief.performance_id==p.id)):bad.append(f'场次#{p.id} 已有散场交接，拒绝改期')
    return bad

def batch_conflicts(s,moves):
    # 按整批新时段核对：日期占用、实名人员跨剧目时段重叠、跨日每日上限
    conflicts=[];move_by_perf={m['perf'].id:m for m in moves}
    by_prod={}
    for m in moves:by_prod.setdefault(m['prod'].id,[]).append(m)
    for pid,group in by_prod.items():
        prod=group[0]['prod'];seen=set()
        for m in group:
            if m['new_date'] in seen:conflicts.append(f"改期单内目标日期重复：{prod.code} 多场同赴 {m['new_date'].isoformat()}")
            seen.add(m['new_date'])
        rows=s.scalars(select(Performance).where(Performance.production_id==pid,Performance.date.in_([m['new_date'] for m in group]))).all()
        for r in rows:
            if r.id not in move_by_perf:conflicts.append(f'日期占用：{prod.code} 在 {r.date.isoformat()} 已有场次#{r.id}')
    call_ids=[m['call'].id for m in moves if m['call']]
    assigned=s.scalars(select(CrewAssignment).where(CrewAssignment.crew_call_id.in_(call_ids))).all() if call_ids else []
    for sid in sorted({a.staff_id for a in assigned}):
        staff=s.get(StaffMember,sid);engagements=[]
        for a in s.scalars(select(CrewAssignment).where(CrewAssignment.staff_id==sid)).all():
            c=s.get(CrewCall,a.crew_call_id);p=s.get(Performance,c.performance_id);pr=s.get(Production,p.production_id)
            m=move_by_perf.get(p.id);day=m['new_date'] if m else p.date
            start,end=window(p,c,pr,day)
            engagements.append({'perf':p,'prod':pr,'day':day,'start':start,'end':end})
        for i in range(len(engagements)):
            for j in range(i+1,len(engagements)):
                x,y=engagements[i],engagements[j]
                if x['start']<y['end'] and y['start']<x['end']:conflicts.append(f"实名人员时段重叠：{staff.name}({staff.code}) 《{x['prod'].title}》{x['day'].isoformat()} 与《{y['prod'].title}》{y['day'].isoformat()} 值班时段相交")
        count=Counter(e['day'] for e in engagements)
        for day in sorted({e['day'] for e in engagements if e['perf'].id in move_by_perf}):
            if count[day]>staff.max_daily_calls:conflicts.append(f'实名人员每日上限：{staff.name}({staff.code}) 在 {day.isoformat()} 值班 {count[day]} 场，超过上限 {staff.max_daily_calls} 场')
    return conflicts

def view(s,order):
    out=pack(order)|{'items':[]}
    for it in s.scalars(select(RescheduleItem).where(RescheduleItem.order_id==order.id).order_by(RescheduleItem.id)):
        p=s.get(Performance,it.performance_id);pr=s.get(Production,p.production_id)
        c=s.scalar(select(CrewCall).where(CrewCall.performance_id==p.id))
        names=[a.staff_name for a in s.scalars(select(CrewAssignment).where(CrewAssignment.crew_call_id==c.id)).all()] if c else []
        out['items'].append(pack(it)|{'production_code':pr.code,'production_title':pr.title,'curtain':p.curtain,'performance_status':p.status,'call_time':c.call_time if c else None,'ushers':c.ushers if c else None,'staff':names})
    return out

def create(s,d,u):
    moves=load_moves(s,d.items)
    for m in moves:
        if m['new_date']==m['perf'].date:raise HTTPException(409,f"场次#{m['perf'].id} 新日期与原日期相同")
    bad=eligibility(s,moves)
    if bad:raise HTTPException(409,'；'.join(bad))
    order=RescheduleOrder(note=d.note,state='draft',conflicts=batch_conflicts(s,moves),created_by=u.email,created_at=datetime.now(timezone.utc).isoformat())
    s.add(order);s.flush()
    for m in moves:s.add(RescheduleItem(order_id=order.id,performance_id=m['perf'].id,old_date=m['perf'].date,new_date=m['new_date']))
    s.flush();audit(s,u,f'编制改期单 #{order.id}（{len(moves)}场）');return view(s,order)

def confirm(s,oid,u):
    order=s.scalar(select(RescheduleOrder).where(RescheduleOrder.id==oid).with_for_update())
    if not order:raise HTTPException(404,'改期单不存在')
    if order.state=='applied':return view(s,order)  # 幂等：重试不重复平移
    items=s.scalars(select(RescheduleItem).where(RescheduleItem.order_id==oid).order_by(RescheduleItem.id)).all()
    pre={it.performance_id:s.scalar(select(CrewCall).where(CrewCall.performance_id==it.performance_id)) for it in items}
    call_ids=[c.id for c in pre.values() if c]
    def staff_set(ids):return sorted({a.staff_id for a in s.scalars(select(CrewAssignment).where(CrewAssignment.crew_call_id.in_(ids))).all()}) if ids else []
    staff_ids=staff_set(call_ids)
    # 与排班/到岗一致的全局锁序：人员→点名→场次→剧目，避免并发占用冲突与死锁
    for sid in staff_ids:locked(s,StaffMember,sid)
    calls={}
    for pid in sorted(pre,key=lambda x:pre[x].id if pre[x] else 0):
        if pre[pid]:calls[pid]=locked(s,CrewCall,pre[pid].id)
    perfs={}
    for pid in sorted(pre):perfs[pid]=locked(s,Performance,pid)
    prods={}
    for pid in sorted({p.production_id for p in perfs.values()}):prods[pid]=locked(s,Production,pid)
    if staff_set([c.id for c in calls.values()])!=staff_ids:raise HTTPException(409,'实名班表在核对期间发生变化，请重试')
    moves=[{'perf':perfs[it.performance_id],'call':calls.get(it.performance_id),'prod':prods[perfs[it.performance_id].production_id],'new_date':it.new_date} for it in items]
    conflicts=eligibility(s,moves)+batch_conflicts(s,moves)
    for pr in prods.values():
        if pr.forecast_state=='calculating':conflicts.append(f'剧目{pr.code} 预测计算中，暂不能改期')
    if conflicts:
        order.conflicts=conflicts;s.flush();s.commit()  # 任一冲突保留全部原安排，仅记录冲突供日历查看
        raise HTTPException(409,'；'.join(conflicts))
    origin={m['perf'].id:m['perf'].date for m in moves}
    base=date(1900,1,1)  # 两阶段改期：先移到占位日期，规避剧目每日一场的唯一约束（如两场互换）
    for m in moves:m['perf'].date=base+timedelta(days=m['perf'].id)
    s.flush()
    for m in moves:
        m['perf'].date=m['new_date']
        c=m['call'];c.call_time=(datetime.fromisoformat(c.call_time)+(m['new_date']-origin[m['perf'].id])).isoformat()  # 点名随开场平移，实名人员不换
    order.state='applied';order.applied_by=u.email;order.applied_at=datetime.now(timezone.utc).isoformat();order.conflicts=[]
    audit(s,u,f'改期单生效 #{order.id}（{len(moves)}场）');return view(s,order)

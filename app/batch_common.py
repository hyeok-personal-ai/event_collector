"""Only public event facts may cross the collector boundary."""
PUBLIC_FIELDS=('canonical_url','title','summary','categories','activity_type','status','apply_deadline','start_at','end_at','last_verified_at','source','organizer','location','price','target','eligibility_target','tech_stack','evidence','application_url')
LIMITS={'title':200,'summary':700,'source':100,'organizer':150,'location':250,'price':100,'target':1500,'eligibility_target':1500,'tech_stack':300,'evidence':1000}

def public_event(event):
    return {k:(event[k][:LIMITS[k]] if k in LIMITS and isinstance(event[k],str) else event[k]) for k in PUBLIC_FIELDS if k in event}

def preserve_club_status(event):
    if event.get('activity_type')=='club' and event.get('status') in ('OPEN','WAITLIST') and not event.get('apply_deadline'):
        event.update(status='CHECK_REQUIRED',evidence='공식 안내는 확인했지만 현재 기수의 신청 마감·모집 여부를 확정하지 못했습니다. 알림 신청과 실제 모집은 다릅니다.')
    return event

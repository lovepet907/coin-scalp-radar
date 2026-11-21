#!/usr/bin/env python3
"""Upbit KRW chart-only scalp radar. Python standard library only."""
import concurrent.futures, datetime as dt, json, math, os, random, statistics, threading, time, urllib.parse, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
BASE='https://api.upbit.com/v1'
HEADERS={'Accept':'application/json','User-Agent':'ChartScalpRadar/1.0'}
MIN_TURNOVER=1_000_000_000
MAX_WORKERS=3
_lock=threading.Lock(); _last=[0.0]

def api(path, params=None, tries=5):
    url=BASE+path+('?' + urllib.parse.urlencode(params, doseq=True) if params else '')
    for attempt in range(tries):
        with _lock:
            delay=max(0,0.16-(time.monotonic()-_last[0]))
            if delay: time.sleep(delay)
            _last[0]=time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=22) as resp:
                return json.load(resp)
        except Exception as e:
            if attempt==tries-1: raise
            time.sleep(min(8,0.8*2**attempt)+random.random()*0.2)

def ema(a,n):
    if len(a)<n: return None
    v=sum(a[:n])/n; k=2/(n+1)
    for x in a[n:]: v=x*k+v*(1-k)
    return v

def rsi(a,n=14):
    if len(a)<n+2:return None
    diff=[a[i]-a[i-1] for i in range(1,len(a))]
    gains=[max(x,0) for x in diff]; losses=[max(-x,0) for x in diff]
    g=sum(gains[:n])/n;l=sum(losses[:n])/n
    for x,y in zip(gains[n:],losses[n:]):g=(g*(n-1)+x)/n;l=(l*(n-1)+y)/n
    return 100 if l==0 else 100-100/(1+g/l)

def macd(a):
    if len(a)<40:return None
    # calculate EMA streams from common starting point
    def stream(n):
        v=sum(a[:n])/n; out=[None]*(n-1)+[v];k=2/(n+1)
        for x in a[n:]:v=v*(1-k)+x*k;out.append(v)
        return out
    e12=stream(12);e26=stream(26)
    m=[x-y for x,y in zip(e12[25:],e26[25:])]
    if len(m)<11:return None
    sig=ema(m,9)
    prevsig=ema(m[:-1],9)
    return m[-1],sig,m[-2],prevsig

def atr(rows,n=14):
    if len(rows)<n+1:return None
    tr=[]
    for i in range(1,len(rows)):
        r=rows[i];p=rows[i-1]['c']
        tr.append(max(r['h']-r['l'],abs(r['h']-p),abs(r['l']-p)))
    v=sum(tr[:n])/n
    for x in tr[n:]:v=(v*(n-1)+x)/n
    return v

def adx(rows,n=14):
    if len(rows)<2*n+2:return None
    tr=[];pdm=[];mdm=[]
    for i in range(1,len(rows)):
        r=rows[i];p=rows[i-1]
        up=r['h']-p['h'];dn=p['l']-r['l']
        pdm.append(up if up>dn and up>0 else 0)
        mdm.append(dn if dn>up and dn>0 else 0)
        tr.append(max(r['h']-r['l'],abs(r['h']-p['c']),abs(r['l']-p['c'])))
    def smooth(arr):
        v=sum(arr[:n]);out=[None]*(n-1)+[v]
        for x in arr[n:]:v=v-v/n+x;out.append(v)
        return out
    t=smooth(tr);p=smooth(pdm);m=smooth(mdm)
    dx=[]
    for i in range(n-1,len(tr)):
        pp=100*p[i]/t[i] if t[i] else 0;mm=100*m[i]/t[i] if t[i] else 0
        dx.append(100*abs(pp-mm)/(pp+mm) if pp+mm else 0)
    if len(dx)<n:return None
    return sum(dx[-n:])/n

def score(rows):
    if len(rows)<65:return None
    a=[r['c'] for r in rows];v=[r['v'] for r in rows]; last=rows[-1];prev=rows[-2]
    ma20=sum(a[-20:])/20;ma50=sum(a[-50:])/50
    r=rsi(a);rp=rsi(a[:-1]); m=macd(a); ap=atr(rows);ax=adx(rows)
    if r is None or m is None:return None
    hist=m[0]-m[1];phist=m[2]-m[3]
    sd=statistics.pstdev(a[-20:]);lo=ma20-2*sd;hi=ma20+2*sd
    low14=min(x['l'] for x in rows[-14:]); high14=max(x['h'] for x in rows[-14:]); k=100*(a[-1]-low14)/(high14-low14) if high14>low14 else 50
    volratio=v[-1]/max(1,sum(v[-21:-1])/20)
    body=abs(last['c']-last['o']);tail=min(last['c'],last['o'])-last['l']
    signals=[
      ('EMA20 회복',a[-1]>ma20 and a[-2]<=sum(a[-21:-1])/20,7,'추세'),
      ('EMA20 위',a[-1]>ma20,6,'추세'),
      ('EMA20·50 정배열',ma20>ma50,7,'추세'),
      ('RSI 45~65',45<=r<=65,7,'모멘텀'),
      ('RSI 상승',r>rp,6,'모멘텀'),
      ('MACD 골든크로스',m[0]>m[1] and m[2]<=m[3],10,'모멘텀'),
      ('MACD 양의 히스토그램',hist>0,6,'모멘텀'),
      ('MACD 히스토그램 개선',hist>phist,7,'모멘텀'),
      ('볼린저 중심선 회복',a[-1]>ma20 and a[-2]<ma20,5,'변동성'),
      ('볼린저 하단 반등',a[-2]<=lo*1.015 and a[-1]>a[-2],6,'변동성'),
      ('스토캐스틱 회복',20<k<75 and a[-1]>a[-2],5,'모멘텀'),
      ('거래량 1.5배',volratio>=1.5,7,'거래량'),
      ('10봉 고점 돌파',a[-1]>max(x['h'] for x in rows[-11:-1]),9,'가격'),
      ('저점 상승',min(x['l'] for x in rows[-5:])>min(x['l'] for x in rows[-10:-5]),5,'가격'),
      ('아래꼬리 매수 반응',last['c']>last['o'] and tail>body*1.5 and tail>0,4,'캔들'),
      ('ADX 추세 강도',ax is not None and ax>=20 and a[-1]>ma20,3,'추세')]
    total=sum(w for _,ok,w,_ in signals if ok)
    warnings=[]
    if r>=75:warnings.append('RSI 과열')
    if hi and a[-1]>hi*1.025:warnings.append('볼린저 상단 과열')
    if len(a)>=25 and a[-1]/a[-25]>1.18:warnings.append('24시간 급등 추격 위험')
    if ap and ap/a[-1]>0.09:warnings.append('높은 ATR 변동성')
    if volratio<0.5:warnings.append('거래량 감소')
    total=max(0,min(100,total-7*len(warnings)))
    return {'score':total,'rsi':round(r,1),'adx':round(ax,1) if ax is not None else None,
            'stoch':round(k,1),'volume_ratio':round(volratio,2),'atr_pct':round(100*ap/a[-1],2) if ap else None,
            'signals':[{'name':name,'hit':bool(ok),'group':group} for name,ok,_,group in signals],
            'warnings':warnings,'close':a[-1], 'ema20':round(ma20,8),'ema50':round(ma50,8)}

def closed_candles(raw,unit,now):
    rows=[]
    for x in raw:
        stamp=x.get('candle_date_time_utc')
        if not stamp:continue
        start=dt.datetime.fromisoformat(stamp).replace(tzinfo=dt.timezone.utc)
        if start+dt.timedelta(minutes=unit)>now:continue
        rows.append({'t':int(start.timestamp()),'o':float(x['opening_price']),'h':float(x['high_price']),
                     'l':float(x['low_price']),'c':float(x['trade_price']),'v':float(x['candle_acc_trade_volume'])})
    return sorted(rows,key=lambda x:x['t'])

def analyze_coin(item,now):
    market=item['market'];turn=float(item.get('acc_trade_price_24h',0))
    try:
        one=closed_candles(api('/candles/minutes/60',{'market':market,'count':200}),60,now)
        four=closed_candles(api('/candles/minutes/240',{'market':market,'count':150}),240,now)
        s1=score(one);s4=score(four)
        if not s1 or not s4:return {'market':market,'status':'insufficient_history','count_1h':len(one),'count_4h':len(four)}
        combined=round(.72*s1['score']+.28*s4['score'])
        if s4['close']<s4['ema20'] and s1['score']>65:combined=max(0,combined-8)
        warnings=list(dict.fromkeys(s1['warnings']+['4시간 추세 약세']*(s4['close']<s4['ema20'])))
        return {'market':market,'status':'ok','name':item.get('name',market),'price':s1['close'],
                'turnover_24h':round(turn),'score':combined,'score_1h':s1['score'],'score_4h':s4['score'],
                'signals':s1['signals'],'warnings':warnings,'indicators':{'rsi_1h':s1['rsi'],'rsi_4h':s4['rsi'],
                'adx_1h':s1['adx'],'stoch_1h':s1['stoch'],'volume_ratio':s1['volume_ratio'],'atr_pct':s1['atr_pct']},
                '_history_samples':historical_samples(one)}
    except Exception as e:return {'market':market,'status':'error','error':str(e)[:160]}

def historical_samples(one):
    # Each sample uses only completed bars available at the signal time.
    # Label: next completed 1h candle close > signal candle close.
    out=[]
    for i in range(70,len(one)-1,3):
        s=score(one[:i+1]);
        if s:out.append((one[i]['t'],s['score'],int(one[i+1]['c']>one[i]['c'])))
    return out

def probability_calibration(results):
    samples=[]
    for x in results:
        for t,s,y in x.get('_history_samples',[]):samples.append((t,s,y))
    if len(samples)<400:return {'status':'insufficient','samples':len(samples)},{}
    samples.sort()
    cutoff=samples[int(len(samples)*.7)][0]
    train=[x for x in samples if x[0]<cutoff];test=[x for x in samples if x[0]>=cutoff]
    if len(train)<200 or len(test)<100:return {'status':'insufficient','samples':len(samples)},{}
    base=(sum(y for _,_,y in train)+1)/(len(train)+2)
    bins=[(0,40),(40,55),(55,70),(70,85),(85,101)]
    def band(s):return next(i for i,(lo,hi) in enumerate(bins) if lo<=s<hi)
    counts=[0]*len(bins);wins=[0]*len(bins)
    for _,s,y in train:i=band(s);counts[i]+=1;wins[i]+=y
    # shrink bins toward training base rate (not an individual coin's measured probability)
    pred=[(wins[i]+100*base)/(counts[i]+100) for i in range(len(bins))]
    brier=sum((pred[band(s)]-y)**2 for _,s,y in test)/len(test)
    baseline=sum((base-y)**2 for _,s,y in test)/len(test)
    acc=sum((pred[band(s)]>=.5)==bool(y) for _,s,y in test)/len(test)
    metrics={'status':'ready','train_samples':len(train),'test_samples':len(test),
             'test_brier':round(brier,4),'baseline_brier':round(baseline,4),'test_accuracy':round(acc,4),
             'base_rate':round(base,4),'caution':'1시간 단독 점수 기반 과거 조건부 상승 빈도 추정; 1h+4h 종합점수의 확률이 아님'}
    bybin={i:{'p':round(pred[i]*100,1),'train_n':counts[i], 'test_n':sum(band(s)==i for _,s,_ in test)} for i in range(len(bins))}
    return metrics,bybin

def main():
    now=dt.datetime.now(dt.timezone.utc)
    markets=api('/market/all',{'isDetails':'false'})
    names={x['market']:x.get('korean_name',x['market']) for x in markets if x['market'].startswith('KRW-')}
    ticks=[];keys=list(names)
    for i in range(0,len(keys),100):
        ticks.extend(api('/ticker',{'markets':','.join(keys[i:i+100])}))
    eligible=[];excluded=0
    for x in ticks:
        if float(x.get('acc_trade_price_24h',0))>=MIN_TURNOVER:
            x['name']=names.get(x['market'],x['market']);eligible.append(x)
        else:excluded+=1
    print(f'KRW={len(keys)} eligible={len(eligible)} excluded={excluded}',flush=True)
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures=[pool.submit(analyze_coin,x,now) for x in eligible]
        for idx,f in enumerate(concurrent.futures.as_completed(futures),1):
            results.append(f.result())
            if idx%40==0:print(f'processed {idx}/{len(futures)}',flush=True)
    good=[x for x in results if x['status']=='ok']
    metrics,bins=probability_calibration(good)
    for x in good:
        # Probability is based on 1h-only historical scores and independently verified bins.
        score1=x['score_1h'];band=0 if score1<40 else 1 if score1<55 else 2 if score1<70 else 3 if score1<85 else 4
        b=bins.get(band)
        x['probability_1h']=(b['p'] if b and b['train_n']>=60 and b['test_n']>=20 else None)
        x['probability_sample_n']=b['train_n'] if b else 0
        x.pop('_history_samples',None)
    good.sort(key=lambda x:(x['score'],x['score_1h'],x['turnover_24h']),reverse=True)
    latest={'schema':1,'generated_at':now.isoformat(),'market':'UPBIT_KRW','min_turnover_24h':MIN_TURNOVER,
            'counts':{'total':len(keys),'eligible':len(eligible),'excluded_liquidity':excluded,'success':len(good),
                      'insufficient_history':sum(x['status']=='insufficient_history' for x in results),
                      'errors':sum(x['status']=='error' for x in results)},
            'backtest':metrics,'top20':[x['market'] for x in good[:20]],'coins':good,
            'issues':[x for x in results if x['status']!='ok'][:30]}
    (DATA/'latest.json').write_text(json.dumps(latest,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    historyfile=DATA/'history.json'
    try:old=json.loads(historyfile.read_text(encoding='utf-8'))
    except (OSError,ValueError):old={'schema':1,'snapshots':[]}
    cutoff=int(now.timestamp())-72*3600
    snaps=[s for s in old.get('snapshots',[]) if s.get('t',0)>=cutoff]
    snaps.append({'t':int(now.timestamp()),'scores':{x['market']:[x['score'],x['probability_1h']] for x in good}})
    # Limit storage even if manually run often
    snaps=snaps[-200:]
    historyfile.write_text(json.dumps({'schema':1,'snapshots':snaps},ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('DONE',json.dumps(latest['counts']),json.dumps(metrics),flush=True)

if __name__=='__main__':main()

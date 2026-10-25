# Exploratory LP simulation from the 25 Oct 2026 reality check (reports/reality-check-2026-10-25.md).
# Expects hl_funding_SOL.json (Hyperliquid fundingHistory) and orca.json (api.orca.so/v2/solana/pools) in the working directory.
import json,urllib.request,time,math,sys
def post(body):
    r=urllib.request.Request('https://api.hyperliquid.xyz/info',data=json.dumps(body).encode(),headers={'content-type':'application/json'})
    return json.load(urllib.request.urlopen(r,timeout=30))
now=int(time.time()*1000); DAYS=30
c=post({"type":"candleSnapshot","req":{"coin":"SOL","interval":"1h","startTime":now-DAYS*86400*1000,"endTime":now}})
px=[float(x['c']) for x in c]
fund={}
for x in json.load(open('hl_funding_SOL.json')): fund[int(x['time'])//3600000]=float(x['fundingRate'])
hours=[int(x['t'])//3600000 for x in c]
pool=json.load(open('orca.json'))['data'][0]
Lpool=int(pool['liquidity']); fees30=float(pool['stats']['30d']['fees'])*(1-pool['protocolFeeRate']/10000)
# fee per unit raw-L per hour, assuming today's active L for the whole window (approximation)
fpl=fees30/(30*24)/Lpool
DEC=1e3  # raw price = usd price / 1000 (SOL 9 dp, USDC 6 dp); amounts below in human units
def amounts(L,p,pa,pb):
    # L in "human" units: x SOL, y USDC
    s,sa,sb=math.sqrt(p),math.sqrt(pa),math.sqrt(pb)
    if p<=pa: return L*(1/sa-1/sb),0.0
    if p>=pb: return 0.0,L*(sb-sa)
    return L*(1/s-1/sb),L*(s-sa)
# human L -> raw L : x_raw = x*1e9, y_raw=y*1e6, L_raw = sqrt(x_raw*y_raw) scale = sqrt(1e15)
LSCALE=math.sqrt(1e15)
def run(width,hedge,cap=10000.0,swap_cost=0.0006,hedge_cost=0.0004):
    cash_usd=0.0; p0=px[0]
    def open_pos(value,p):
        pa,pb=p*(1-width),p*(1+width)
        x1,y1=amounts(1.0,p,pa,pb); v1=x1*p+y1
        return value/v1,pa,pb
    L,pa,pb=open_pos(cap*(1-swap_cost/2),p0)
    fees=0.0; rebal=0; inrange=0; hpos=0.0; hpnl=0.0; fpnl=0.0; hcost=0.0
    if hedge:
        x,_=amounts(L,p0,pa,pb); hpos=-x; hcost+=abs(x)*p0*hedge_cost
    for i in range(1,len(px)):
        p_prev,p=px[i-1],px[i]
        if hedge:
            hpnl+=hpos*(p-p_prev)
            fpnl+=-hpos*p*fund.get(hours[i],0.0)  # short receives positive funding
        if pa<p<pb:
            fees+=L*LSCALE*fpl; inrange+=1
        elif True:
            # out of range: rebalance to new centered range (pay swap cost on ~half the value)
            x,y=amounts(L,p,pa,pb); v=x*p+y
            L,pa,pb=open_pos(v*(1-swap_cost/2),p); rebal+=1
        if hedge:
            x,_=amounts(L,p,pa,pb); tgt=-x
            if abs(tgt-hpos)*p>cap*0.01:  # rehedge when drift > 1% of capital
                hcost+=abs(tgt-hpos)*p*hedge_cost; hpos=tgt
    x,y=amounts(L,px[-1],pa,pb); lp=x*px[-1]+y
    total=lp+fees+hpnl+fpnl-hcost
    hodl=cap/2/p0*px[-1]+cap/2
    return dict(width=width,hedge=hedge,ret=(total/cap-1)*100,lp_val_ret=(lp/cap-1)*100,fees=fees/cap*100,hedge_pnl=hpnl/cap*100,funding=fpnl/cap*100,hcost=hcost/cap*100,rebal=rebal,inrange=inrange/len(px)*100,hodl=(hodl/cap-1)*100)
print(f"SOL {px[0]:.2f} -> {px[-1]:.2f} over {len(px)}h ({(px[-1]/px[0]-1)*100:+.1f}%). Pool 30d LP fees ${fees30:,.0f}, fee APR on TVL {fees30/float(pool['tvlUsdc'])*12*100:.0f}%")
print("USDC lending benchmark over 30d: ~+0.5% (6% APR)")
for hedge in (False,True):
    for w in (0.01,0.02,0.05,0.10,0.25):
        r=run(w,hedge)
        print(f"{'HEDGED  ' if hedge else 'UNHEDGED'} ±{w*100:4.0f}%  total {r['ret']:+6.2f}%  (fees {r['fees']:+5.2f}, LP mark {r['lp_val_ret']:+6.2f}, hedge {r['hedge_pnl']:+6.2f}, funding {r['funding']:+.2f}, costs -{r['hcost']:.2f})  rebalances {r['rebal']:3d} in-range {r['inrange']:.0f}%  | 50/50 HODL {r['hodl']:+.2f}%")

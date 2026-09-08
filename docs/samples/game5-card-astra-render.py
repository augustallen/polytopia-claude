"""Render the game5 social card from source events; Pillow only, no external assets."""
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, S = 1800, 2400, 2
FONT = 'C:/Users/augus/tools/fonts/JosefinSans[wght].ttf'
events = [json.loads(line) for line in (ROOT / 'game5.jsonl').read_text().splitlines()]
turns = {p: sorted([e for e in events if e['event'] == 'turn' and e['player'] == p], key=lambda e:e['turn']) for p in (1,2)}
end = next(e for e in events if e['event'] == 'game_over')
final = {p['id']:p for p in end['players']}
CREAM = '#FFF2D8'
MUTED = '#C1B5C9'
BLUE = '#7BE6EF'
ORANGE = '#FFB07C'
GRID = '#51425F'

# Smooth sunset sky, fading into a plum night behind the charts.
stops = [(0, '#D17F83'), (.18, '#91648B'), (.37, '#493754'), (1, '#211F35')]
rgb = lambda c: tuple(bytes.fromhex(c.lstrip('#')))
row = np.zeros((H*S,3), dtype=np.uint8)
for y in range(H*S):
    t=y/(H*S-1)
    for (a,ca),(b,cb) in zip(stops,stops[1:]):
        if a <= t <= b:
            f=(t-a)/(b-a)
            row[y]=np.array(rgb(ca))*(1-f)+np.array(rgb(cb))*f
            break
im=Image.fromarray(np.repeat(row[:,None,:], W*S, axis=1))
d=ImageDraw.Draw(im)
def box(coords, fill, outline=None, width=1):
    d.rectangle(tuple(int(v*S) for v in coords), fill=fill, outline=outline, width=width*S)
def poly(points, fill): d.polygon([(int(x*S),int(y*S)) for x,y in points], fill=fill)
def line(points, fill, width=2): d.line([(int(x*S),int(y*S)) for x,y in points], fill=fill, width=width*S, joint='curve')
def circle(x,y,r,fill): d.ellipse(((x-r)*S,(y-r)*S,(x+r)*S,(y+r)*S),fill=fill)
def text(x,y,s,size=30,fill=CREAM,weight=500,anchor='lt'):
    f=ImageFont.truetype(FONT,size*S)
    f.set_variation_by_axes([weight])
    d.text((x*S,y*S),str(s),font=f,fill=fill,anchor=anchor)
def star(x,y,r,fill):
    poly([(x+math.cos(-math.pi/2+i*math.pi/5)*(r if i%2==0 else r*.44),y+math.sin(-math.pi/2+i*math.pi/5)*(r if i%2==0 else r*.44)) for i in range(10)],fill)

# Faceted horizon and a decorative Imperius-inspired isometric island.
circle(1410,231,146,'#EBA78F')
poly([(0,441),(225,343),(410,432),(660,312),(911,433),(1150,357),(1470,437),(1660,330),(1800,390),(1800,580),(0,580)],'#785B83')
poly([(0,506),(297,400),(630,513),(941,404),(1243,513),(1615,399),(1800,474),(1800,600),(0,600)],'#5A476B')
def tile(x,y,r=91):
    poly([(x-r,y),(x,y+r*.5),(x+r,y),(x+r,y+34),(x,y+r*.5+34),(x-r,y+34)],'#4B5765')
    poly([(x,y),(x+r,y),(x,y+r*.5),(x-r,y)],'#72A694')
    poly([(x,y-r*.5),(x+r,y),(x,y+r*.5),(x-r,y)],'#91B99C')
    poly([(x,y),(x+r,y),(x,y+r*.5)],'#74A38B')
def tower(x,y,h=125):
    poly([(x-43,y-23),(x,y),(x,y-h),(x-43,y-h-23)],'#D6CABC')
    poly([(x,y),(x+43,y-23),(x+43,y-h-23),(x,y-h)],'#9BAFC0')
    poly([(x-54,y-h-22),(x,y-h-51),(x+54,y-h-22),(x,y-h+7)],'#6AD6E6')
    poly([(x-54,y-h-22),(x,y-h-88),(x,y-h+7)],'#A3F3F0')
    poly([(x,y-h-88),(x+54,y-h-22),(x,y-h+7)],'#4CA5C4')
    box((x-8,y-46,x+8,y-9),'#576378')
def tree(x,y):
    box((x-5,y-10,x+5,y+15),'#675B67')
    poly([(x,y-98),(x-40,y-16),(x+40,y-16)],'#49776D')
    poly([(x,y-98),(x,y-16),(x+40,y-16)],'#315E60')
for xx,yy in [(1405,368),(1314,414),(1496,414),(1223,460),(1405,460),(1587,460),(1314,506),(1496,506)]: tile(xx,yy)
tree(1400,362)
tower(1323,420,91)
tower(1497,424,114)
tree(1218,454)
tower(1406,482,149)
tree(1589,455)
line([(1410,247),(1410,171)],CREAM,5)
poly([(1413,174),(1475,174),(1452,193),(1413,193)],BLUE)

text(90,63,'THE BATTLE OF POLYTOPIA',30,weight=700)
text(90,119,'AI MATCH REPORT   /   07 SEP 2026',25,fill='#F6D7CB',weight=600)
text(85,199,'CODEX WINS',103,weight=700)
text(92,326,'DOMINATION  /  TURN 14',37,weight=700)
text(92,397,'An expanding empire.',38)
text(92,448,'A final capital capture.',38)

# End-of-game leaderboard; the game_over event is authoritative.
box((65,588,1735,917),'#302A44')
text(98,614,'FINAL STANDINGS',27,weight=700)
for x,label in [(1175,'SCORE'),(1398,'CITIES'),(1615,'KILLS')]: text(x,616,label,25,MUTED,600,'mt')
box((88,668,1712,779),'#3D4154')
box((88,668,96,779),BLUE)
text(125,697,'1',46,BLUE,700)
text(195,689,'Codex gpt-6-astra',42,BLUE,700)
text(197,740,'Codex CLI  /  Player 2',25,MUTED)
text(125,817,'2',42,ORANGE,700)
text(195,808,'Claude Fable 5.1',40,ORANGE,600)
text(197,858,'Claude Code  /  Player 1 · moved first',25,MUTED)
for p,y,col in [(2,704,BLUE),(1,821,CREAM)]:
    for x,k in [(1175,'score'),(1398,'cities'),(1615,'kills')]: text(x,y,f'{final[p][k]:,}',46,col,600,'mt')

text(90,963,'THE ECONOMY GAP',39,weight=700)
line([(1164,982),(1213,982)],BLUE,6)
circle(1189,982,6,BLUE)
text(1230,966,'Codex',28,BLUE)
line([(1410,982),(1459,982)],ORANGE,5)
text(1476,966,'Claude',28,ORANGE)

def chart(rect,key,title,subtitle,ymax,ticks,step=False):
    x,y,w,h=rect
    box((x,y,x+w,y+h),'#302A44')
    text(x+30,y+25,title,34,weight=600)
    text(x+30,y+74,subtitle,24,MUTED)
    left,top,right,bottom=x+73,y+139,x+w-91,y+h-68
    xy=lambda t,v:(left+(right-left)*t/14,bottom-(bottom-top)*v/ymax)
    for v in ticks:
        yy=xy(0,v)[1]
        line([(left,yy),(right,yy)],GRID,1)
        text(left-19,yy,str(v),23,MUTED,anchor='rm')
    for t in [0,2,4,6,8,10,12,14]:
        xx=xy(t,0)[0]
        text(xx,bottom+18,str(t),23,MUTED,anchor='mt')
    text(right,bottom+44,'TURN',18,MUTED,anchor='rt')
    for p,col in [(1,ORANGE),(2,BLUE)]:
        pts=[xy(e['turn'],e[key]) for e in turns[p]]
        path=[pts[0]]
        for a,b in zip(pts,pts[1:]):
            if step:path.append((b[0],a[1]))
            path.append(b)
        line(path,col,5)
        for xx,yy in pts: circle(xx,yy,4,col)
        xx,yy=pts[-1]
        circle(xx,yy,7,col)
        text(xx+20,yy,str(turns[p][-1][key]),29,col,700,'lm')

chart((65,1025,1670,452),'stars','Stars in reserve','Unspent stars at the start of each player’s turn',30,[0,10,20,30])
chart((65,1500,817,427),'income','Star income','Stars per turn',20,[0,5,10,15,20],True)
chart((906,1500,829,427),'cities','Cities held','Codex: 6 before final capture → 7 after',6,[0,2,4,6],True)

text(90,1955,'HOW THE GAME TURNED',32,weight=700)
for a,b in [(275,632),(825,1182),(1375,1688)]:
    line([(a,2031),(b,2031)],'#73617B',3)
milestones=[(110,'03','Second city','Codex begins expanding.'),(660,'11','Six cities','Codex captures city #6.'),(1210,'14','Elimination','Claude’s capital falls.')]
for x,t,title,caption in milestones:
    star(x,2031,13,BLUE)
    text(x+26,2015,'TURN '+t,25,BLUE,600)
    text(x,2062,title,36,CREAM,600)
    text(x,2115,caption,25,MUTED)
text(90,2176,'Charts show each seat’s turn-start state, T0–T14. Final standings follow the winning capture.',24,MUTED)
line([(90,2232),(1710,2232)],GRID,2)
text(90,2260,'DOMINATION  ·  TINY 11 × 11  ·  IMPERIUS vs IMPERIUS',27,weight=600)
text(90,2310,'Offline Pass & Play  /  Both models: medium reasoning  /  Source: game5.jsonl',25,MUTED)
im=im.resize((W,H),Image.Resampling.LANCZOS)
im.save(ROOT/'astra-card.png')
im.resize((900,1200),Image.Resampling.LANCZOS).save(ROOT/'astra-card-preview.png')
print(f'Rendered {W} × {H}: {ROOT / "astra-card.png"}')
